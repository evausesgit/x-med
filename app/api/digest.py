"""Digest en arrière-plan : la pipeline de recherche v2 nourrie par le profil.

Pas de pipeline dédiée ni de cron (décision Eva : on-demand seulement, pour ne
pas brûler de tokens) : quand le médecin connecté clique « Générer mon digest »,
on compose une query depuis son profil (metaprompt + facettes, voir
`services/digest_query.py`) et on la fait avaler par `_run_deep_search`.

La génération tourne dans un thread DÉTACHÉ de la requête HTTP : fermer
l'onglet ne l'interrompt plus. La table `digest_runs` est la source de vérité
et le front la POLLE (GET /digest/runs/{id}) — toute la mécanique commune avec
la recherche en arrière-plan (états, jalons, garde zombie, corps du job) vit
dans `services/run_store.py`. Le digest « officiel » d'une journée est le
dernier run `complete` de cette date : régénérer remplace l'affichage du jour
sans effacer l'audit des tentatives précédentes.

La query composée ne transite JAMAIS par l'URL (le profil clinique n'a rien à
faire dans les logs du proxy) : le front n'envoie que `days`, le backend
reconstruit tout. Le payload et les jalons PERSISTÉS sont assainis avant
écriture (metaprompt remplacé par le libellé, requête PubMed/MeSH retirés) :
la table ne doit pas exposer plus que ce que le digest affiche.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.exc import IntegrityError

from app.api.me import Identity, _find_doctor, current_identity
from app.api.search import DeepSearchRequest
from app.db import SessionLocal
from app.models import DigestRun, Doctor
from app.services import run_store, search_cancel
from app.services.digest_query import build_digest_query, digest_usage_label
from app.services.run_store import ACTIVE_STATUSES, PARIS
from app.services.usage_log import record_usage

router = APIRouter()

# 30 jours par défaut (7 jours donne trop souvent zéro article sur les niches) ;
# le front propose 7/30/90 sans jamais relancer automatiquement une recherche.
DIGEST_DAYS_DEFAULT = 30


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


def _sanitize_digest_payload(label: str):
    """Le payload est PERSISTÉ : on en retire tout ce qui révèle le profil
    clinique (metaprompt, requête PubMed construite, facettes). Le front du
    digest n'utilise aucun de ces champs."""

    def sanitize(result) -> None:
        result.query = label
        result.pubmed_query = None
        result.mesh_terms = []
        result.keywords_en = []

    return sanitize


def mark_orphan_runs() -> None:
    """Au démarrage de l'API (les threads ne survivent pas à un redémarrage)."""
    run_store.mark_orphans(
        DigestRun, "Génération interrompue par un redémarrage du serveur."
    )


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
        run_store.requalify_stale(
            session, DigestRun, doctor.id,
            "Génération abandonnée (aucune activité depuis 2 h).",
        )

        run = DigestRun(
            doctor_id=doctor.id, digest_date=_paris_today(), days=body.days
        )
        session.add(run)
        try:
            # L'INSERT part ici — l'index unique partiel se prononce au flush.
            session.flush()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                409, "Une génération de digest est déjà en cours pour votre profil."
            )
        # Jeton d'annulation enregistré AVANT que la ligne soit visible des
        # autres transactions (commit) : un stop venu d'un autre onglet qui
        # découvre le run trouve toujours un état à annuler.
        cancel_state = search_cancel.register(str(run.id))
        try:
            session.commit()
        except Exception:
            session.rollback()
            search_cancel.unregister(str(run.id))
            raise
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
    try:
        if cancel_state is None:  # impossible : le run id est un UUID neuf
            raise RuntimeError("jeton de génération déjà utilisé")
        Thread(
            target=run_store.run_deep_job,
            args=(DigestRun, summary.id, req, label, ident.email, cancel_state),
            kwargs={
                "sanitize": _sanitize_digest_payload(label),
                # La requête PubMed et les MeSH sont dérivés du profil
                # clinique : ils ne doivent apparaître ni dans les jalons
                # persistés ni dans la notification.
                "strip_log_keys": ("pubmed_query", "mesh_terms"),
                "strip_metric_keys": ("pubmed_query",),
                # Un stop pendant la traduction ne perd pas le digest déjà
                # obtenu : le run finit `complete`, sans les traductions.
                "keep_result_on_stop": True,
            },
            daemon=True,
        ).start()
    except Exception as exc:
        # Sans thread, la ligne resterait `running` pour toujours (et l'index
        # unique bloquerait toute nouvelle génération) : on la clôt en erreur.
        search_cancel.unregister(str(summary.id))
        run_store.set_run(
            DigestRun, summary.id,
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
    """Arrête la génération en cours. Transition SQL d'abord (la table est la
    source de vérité) — mais UNIQUEMENT depuis `running` : pendant
    `translating`, le digest est déjà acquis et un stop ne doit pas le perdre
    (le run finira `complete`, sans les traductions — l'annulation du jeton
    interrompt quand même la traduction en vol). Puis, best-effort : codex
    tué, requête FTS locale annulée (pg_cancel_backend)."""
    from app.api.search import _LOCAL_SEARCH_PIDS

    with SessionLocal() as session:
        _get_own_run(session, ident, run_id)
    token = str(run_id)
    stopped = run_store.stop_run(DigestRun, run_id, from_statuses=("running",))
    cancelled = search_cancel.cancel(token)
    pid = _LOCAL_SEARCH_PIDS.get(token)
    if pid is not None:
        with SessionLocal() as s:
            s.scalar(sql_text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
    return StopRunResponse(stopped=stopped or cancelled)


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
