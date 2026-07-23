"""Digest en arrière-plan : la pipeline de recherche v2 nourrie par le profil.

Pas de pipeline dédiée ni de cron (décision Eva : on-demand seulement, pour ne
pas brûler de tokens) : quand le médecin connecté clique « Générer mon digest »,
on compose une query depuis son profil (metaprompt + facettes, voir
`services/digest_query.py`) et on la fait avaler par `_run_deep_search`.

Contrairement à la recherche (SSE lié à la connexion), la génération tourne dans
un thread DÉTACHÉ de la requête HTTP : fermer l'onglet ne l'interrompt plus. La
table `digest_runs` est la source de vérité — jalons de progression, payload,
statut — et le front la POLLE (GET /digest/runs/{id}) au lieu d'écouter un flux.
Cycle de vie : running → translating (payload visible, traductions FR en cours)
→ complete ; ou error / stopped. Le digest « officiel » d'une journée est le
dernier run `complete` de cette date : régénérer remplace l'affichage du jour
sans effacer l'audit des tentatives précédentes.

La query composée ne transite JAMAIS par l'URL (le profil clinique n'a rien à
faire dans les logs du proxy) : le front n'envoie que `days`, le backend
reconstruit tout. Le payload et les jalons PERSISTÉS sont assainis avant
écriture (metaprompt remplacé par le libellé, requête PubMed/MeSH retirés) :
la table ne doit pas exposer plus que ce que le digest affiche.

⚠️ Mono-process : comme `search_cancel` et `_LOCAL_SEARCH_PIDS`, l'annulation
suppose UN seul process uvicorn (le thread et le registre d'annulation vivent
dans le même process que l'endpoint stop). L'exclusivité « un run actif par
médecin », elle, est garantie en base (index unique partiel).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timedelta
from threading import Thread
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text as sql_text, update
from sqlalchemy.exc import IntegrityError

from app.api.me import Identity, _find_doctor, current_identity
from app.api.search import (
    DeepSearchRequest,
    _deep_metrics,
    _run_deep_search,
    _translate_kept,
)
from app.db import SessionLocal
from app.models import DigestRun, Doctor
from app.services import search_cancel
from app.services.digest_query import build_digest_query, digest_usage_label
from app.services.search_cancel import SearchCancelled
from app.services.usage_log import record_usage

router = APIRouter()

# 30 jours par défaut (7 jours donne trop souvent zéro article sur les niches) ;
# le front propose 7/30/90 sans jamais relancer automatiquement une recherche.
DIGEST_DAYS_DEFAULT = 30

# La journée d'un digest est celle du médecin, pas celle du serveur (UTC) : un
# lancement à 0h30 heure française doit dater du bon jour.
PARIS = ZoneInfo("Europe/Paris")

# Un run actif sans battement de cœur (updated_at) depuis ce délai est un
# zombie (thread tué sans écrire son état, ex. kill -9) : on le requalifie en
# erreur pour libérer l'index unique partiel. Les jalons du pipeline arrivent
# au pire toutes les ~2 min (jugement codex) — 2 h est très large.
STALE_ACTIVE_AFTER = timedelta(hours=2)

ACTIVE_STATUSES = ("running", "translating")


def _paris_today() -> date:
    return datetime.now(PARIS).date()


class GenerateDigestRequest(BaseModel):
    days: int = Field(default=DIGEST_DAYS_DEFAULT, ge=1, le=365)
    k_pubmed: int = Field(default=20, ge=1, le=200)
    judge_batch: int = Field(default=50, ge=10, le=100)


class DigestRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    digest_date: date
    days: int
    status: str
    n_results: int
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class DigestRunOut(DigestRunSummary):
    logs: list[dict]
    payload: dict | None = None


class DigestHistory(BaseModel):
    # Run actif éventuel (running/translating) ET digest complet du même jour
    # peuvent coexister : l'ancien reste le digest officiel tant que la
    # régénération n'a pas abouti.
    current: DigestRunSummary | None
    days: list[DigestRunSummary]


class StopRunResponse(BaseModel):
    stopped: bool  # True si une génération en cours a bien été annulée


def _require_doctor(session, ident: Identity) -> Doctor:
    doctor = _find_doctor(session, ident)
    if doctor is None or doctor.profile is None:
        raise HTTPException(
            404, "Complétez votre profil pour générer votre digest personnalisé."
        )
    return doctor


def _set_run(run_id: uuid.UUID, **values) -> None:
    """Écrit l'état d'un run dans une session courte dédiée (le thread de
    génération ne doit pas committer dans la session de `_run_deep_search`).

    Transition CONDITIONNELLE : n'écrit que si le run est encore actif. Un run
    requalifié en zombie (garde 2 h, redémarrage) ne peut donc pas être
    « ressuscité » par son ancien thread qui écrirait translating/complete
    par-dessus l'erreur — l'écriture devient un no-op."""
    with SessionLocal() as s:
        s.execute(
            update(DigestRun)
            .where(DigestRun.id == run_id, DigestRun.status.in_(ACTIVE_STATUSES))
            .values(updated_at=datetime.now(PARIS), **values)
        )
        s.commit()


def _append_log(run_id: uuid.UUID, event: dict) -> None:
    """Ajoute un jalon par UPDATE atomique `logs = logs || …` — pas de liste
    JSONB mutée côté ORM (SQLAlchemy ne détecterait pas la mutation). Touche
    aussi `updated_at` : c'est le battement de cœur du run."""
    with SessionLocal() as s:
        s.execute(
            sql_text(
                "UPDATE digest_runs SET logs = logs || CAST(:ev AS jsonb), "
                "updated_at = now() WHERE id = :id"
            ),
            {"ev": json.dumps([event], ensure_ascii=False), "id": run_id},
        )
        s.commit()


def _run_digest_job(
    run_id: uuid.UUID,
    req: DeepSearchRequest,
    notif_query: str,
    user_email: str,
    cancel_state: search_cancel.CancelState,
) -> None:
    """Corps du run, exécuté dans un thread détaché de la requête HTTP.

    Le jeton d'annulation est enregistré par l'ENDPOINT, avant le démarrage du
    thread : un stop qui arrive entre le POST et le premier jalon trouve donc
    toujours un état à annuler (pas de fenêtre aveugle).

    Volontairement indépendant du thread qui le porte : basculer un jour sur un
    vrai worker (Celery/RQ) reviendra à appeler cette fonction ailleurs.
    """
    from app.services.search_notifications import send_search_notification

    token = req.local_token
    # Contextvar par thread : les appels codex du pipeline deviennent annulables
    # (le endpoint stop tue le sous-processus en vol).
    search_cancel.current_search.set(cancel_state)

    t0 = time.monotonic()
    progress_events: list[dict] = []

    def progress(phase: str, msg: str, data: dict) -> None:
        # Point d'arrêt coopératif : une annulation prend effet au prochain jalon.
        cancel_state.raise_if_cancelled()
        elapsed = round(time.monotonic() - t0, 1)
        # La requête PubMed et les MeSH sont dérivés du profil clinique : ils ne
        # doivent apparaître ni dans les logs persistés ni dans la notification.
        data = {k: v for k, v in data.items() if k not in ("pubmed_query", "mesh_terms")}
        event = {"phase": phase, "msg": f"{msg} ({elapsed}s)", "elapsed_s": elapsed, **data}
        progress_events.append(event)
        _append_log(run_id, event)

    notified = False
    try:
        with SessionLocal() as session:
            result = _run_deep_search(req, session, progress)
            # Le payload est PERSISTÉ : on en retire tout ce qui révèle le
            # profil clinique (metaprompt, requête PubMed construite, facettes).
            # Le front du digest n'utilise aucun de ces champs.
            result.query = notif_query
            result.pubmed_query = None
            result.mesh_terms = []
            result.keywords_en = []
            metrics = _deep_metrics(result)
            # Requête PubMed dérivée du profil clinique : elle le révélerait.
            metrics.pop("pubmed_query", None)
            # Notif dès que la recherche a abouti (la traduction qui suit est un
            # post-traitement best-effort, pas un échec de génération).
            send_search_notification(
                status="ok", query=notif_query,
                duration_s=time.monotonic() - t0,
                metrics=metrics,
                progress_events=progress_events,
                user=user_email,
            )
            notified = True
            # Payload visible dès maintenant : le médecin qui revient sur la
            # page voit ses articles pendant que les traductions se terminent.
            _set_run(
                run_id,
                status="translating",
                payload=result.model_dump(),
                n_results=len(result.results),
            )
            # Traductions best-effort : ni un échec ni un stop pendant cette
            # phase ne doivent faire perdre le digest déjà obtenu.
            try:
                fr = _translate_kept(result, session, progress)
            except Exception:
                fr = {}
            for h in result.results:
                t = fr.get(str(h.pmid))
                if t:
                    h.title_fr = t.get("title_fr") or h.title_fr
                    h.abstract_fr = t.get("abstract_fr") or h.abstract_fr
            _set_run(
                run_id,
                status="complete",
                payload=result.model_dump(),
                finished_at=datetime.now(PARIS),
            )
    except SearchCancelled:
        # Arrêt volontaire (bouton stop) : pas une erreur.
        if not notified:
            send_search_notification(
                status="stopped", query=notif_query,
                duration_s=time.monotonic() - t0,
                metrics={"method": "v2 (filtre lexical/MeSH + jugement codex)"},
                progress_events=progress_events,
                user=user_email,
            )
        _set_run(run_id, status="stopped", finished_at=datetime.now(PARIS))
    except Exception as exc:
        if not notified:
            send_search_notification(
                status="error", query=notif_query,
                duration_s=time.monotonic() - t0,
                metrics={"method": "v2 (filtre lexical/MeSH + jugement codex)"},
                progress_events=progress_events,
                error=str(exc),
                user=user_email,
            )
        msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _set_run(run_id, status="error", error=str(msg),
                 finished_at=datetime.now(PARIS))
    finally:
        search_cancel.unregister(token)


def mark_orphan_runs() -> None:
    """Au démarrage de l'API : les runs restés actifs appartiennent à un process
    mort (les threads ne survivent pas à un redémarrage) → erreur explicite.
    Best-effort : une base pas encore migrée ne doit pas empêcher l'API de
    démarrer (dev_up applique les migrations juste avant)."""
    try:
        with SessionLocal() as s:
            s.execute(
                update(DigestRun)
                .where(DigestRun.status.in_(ACTIVE_STATUSES))
                .values(
                    status="error",
                    error="Génération interrompue par un redémarrage du serveur.",
                    finished_at=datetime.now(PARIS),
                )
            )
            s.commit()
    except Exception:
        pass


@router.post("/digest/generate", response_model=DigestRunSummary)
def generate_digest(
    body: GenerateDigestRequest,
    request: Request,
    ident: Identity = Depends(current_identity),
):
    """Lance une génération de digest en arrière-plan et rend la main tout de
    suite (le front polle ensuite GET /digest/runs/{id}). 409 si une génération
    est déjà en cours pour ce médecin — exclusivité garantie par l'index unique
    partiel `uq_digest_runs_active`, pas par un SELECT préalable."""
    with SessionLocal() as session:
        doctor = _require_doctor(session, ident)
        query = build_digest_query(doctor, doctor.profile)
        label = digest_usage_label(doctor.profile, body.days)
        # Libérer l'index unique d'un éventuel run zombie avant d'insérer :
        # actif mais sans battement de cœur (updated_at) depuis 2 h. On annule
        # aussi son jeton — si son thread vit encore malgré tout, il s'arrête
        # au prochain jalon (et ses écritures d'état sont devenues des no-ops,
        # cf. `_set_run`).
        stale_ids = session.scalars(
            select(DigestRun.id).where(
                DigestRun.doctor_id == doctor.id,
                DigestRun.status.in_(ACTIVE_STATUSES),
                DigestRun.updated_at < datetime.now(PARIS) - STALE_ACTIVE_AFTER,
            )
        ).all()
        if stale_ids:
            session.execute(
                update(DigestRun)
                .where(DigestRun.id.in_(stale_ids))
                .values(
                    status="error",
                    error="Génération abandonnée (aucune activité depuis 2 h).",
                    finished_at=datetime.now(PARIS),
                )
            )
            session.commit()
            for stale_id in stale_ids:
                search_cancel.cancel(str(stale_id))

        run = DigestRun(
            doctor_id=doctor.id, digest_date=_paris_today(), days=body.days
        )
        session.add(run)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                409, "Une génération de digest est déjà en cours pour votre profil."
            )
        session.refresh(run)
        summary = DigestRunSummary.model_validate(run)

    record_usage(
        request, "digest.run", query=label,
        params={"days": body.days, "k_pubmed": body.k_pubmed, "background": True},
    )

    # Fenêtre : exactement `days` dates calendaires, bornée des deux côtés
    # (PubMed contient des dates de publication futures). `require_builder=True` :
    # sans query-builder GPT-5.6, le digest échoue proprement plutôt que
    # d'envoyer le metaprompt français brut à PubMed.
    today = summary.digest_date
    req = DeepSearchRequest(
        query=query,
        date_from=(today - timedelta(days=body.days - 1)).isoformat(),
        date_to=today.isoformat(),
        k_pubmed=body.k_pubmed,
        rrf=True,
        judge_batch=body.judge_batch,
        # Le run id sert de jeton d'annulation (stop + pg_cancel du FTS local).
        local_token=str(summary.id),
        require_builder=True,
    )
    # Le jeton d'annulation est enregistré AVANT le démarrage du thread : un
    # stop qui arrive juste après le POST trouve toujours un état à annuler.
    cancel_state = search_cancel.register(str(summary.id))
    try:
        if cancel_state is None:  # impossible : le run id est un UUID neuf
            raise RuntimeError("jeton de génération déjà utilisé")
        Thread(
            target=_run_digest_job,
            args=(summary.id, req, label, ident.email, cancel_state),
            daemon=True,
        ).start()
    except Exception as exc:
        # Sans thread, la ligne resterait `running` pour toujours (et l'index
        # unique bloquerait toute nouvelle génération) : on la clôt en erreur.
        search_cancel.unregister(str(summary.id))
        _set_run(
            summary.id,
            status="error",
            error=f"Impossible de démarrer la génération : {exc}",
            finished_at=datetime.now(PARIS),
        )
        raise HTTPException(500, "Impossible de démarrer la génération. Réessayez.")
    return summary


def _get_own_run(session, ident: Identity, run_id: uuid.UUID) -> DigestRun:
    """Charge un run en vérifiant qu'il appartient au médecin connecté (ne pas
    reproduire l'absence d'ACL des saved_searches : le digest est personnel)."""
    doctor = _find_doctor(session, ident)
    run = session.get(DigestRun, run_id)
    if doctor is None or run is None or run.doctor_id != doctor.id:
        raise HTTPException(404, "Génération de digest introuvable.")
    return run


@router.get("/digest/runs/{run_id}", response_model=DigestRunOut)
def get_digest_run(
    run_id: uuid.UUID, ident: Identity = Depends(current_identity)
):
    """État complet d'un run (statut + jalons + payload) — l'endpoint que le
    front polle pendant la génération et pour rouvrir un digest passé."""
    with SessionLocal() as session:
        return DigestRunOut.model_validate(_get_own_run(session, ident, run_id))


@router.post("/digest/runs/{run_id}/stop", response_model=StopRunResponse)
def stop_digest_run(
    run_id: uuid.UUID, ident: Identity = Depends(current_identity)
):
    """Arrête la génération en cours : l'appel codex en vol est tué, la requête
    FTS locale annulée (pg_cancel_backend), le pipeline s'arrête au prochain
    jalon. Sans run actif sous ce jeton, ne fait rien (stopped=False)."""
    from app.api.search import _LOCAL_SEARCH_PIDS

    with SessionLocal() as session:
        _get_own_run(session, ident, run_id)
    token = str(run_id)
    stopped = search_cancel.cancel(token)
    pid = _LOCAL_SEARCH_PIDS.get(token)
    if pid is not None:
        with SessionLocal() as s:
            s.scalar(sql_text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
    return StopRunResponse(stopped=stopped)


@router.get("/digest/history", response_model=DigestHistory)
def digest_history(ident: Identity = Depends(current_identity)):
    """Historique du médecin connecté : le run actif éventuel + le dernier run
    `complete` de chaque journée (une régénération aboutie supplante donc la
    précédente pour sa date, sans suppression)."""
    with SessionLocal() as session:
        doctor = _find_doctor(session, ident)
        if doctor is None:
            raise HTTPException(404, "Aucun profil rattaché à ce compte")
        current = session.scalars(
            select(DigestRun)
            .where(
                DigestRun.doctor_id == doctor.id,
                DigestRun.status.in_(ACTIVE_STATUSES),
            )
            .order_by(DigestRun.created_at.desc())
            .limit(1)
        ).first()
        days = session.scalars(
            select(DigestRun)
            .where(
                DigestRun.doctor_id == doctor.id,
                DigestRun.status == "complete",
            )
            .distinct(DigestRun.digest_date)
            .order_by(DigestRun.digest_date.desc(), DigestRun.created_at.desc())
        ).all()
    return DigestHistory(
        current=DigestRunSummary.model_validate(current) if current else None,
        days=[DigestRunSummary.model_validate(r) for r in days],
    )
