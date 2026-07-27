"""Plomberie partagée des runs en arrière-plan (digest_runs, search_runs).

Un « run » est une exécution de la pipeline de recherche v2 dans un thread
DÉTACHÉ de la requête HTTP : la table est la source de vérité (statut, jalons,
payload) et le front la POLLE au lieu d'écouter un flux. Cycle de vie :
running → translating (payload disponible, traductions FR en cours) →
complete ; ou error / stopped.

Tout ce qui est identique entre le digest et la recherche vit ici, paramétré
par le modèle SQLAlchemy (`DigestRun` ou `SearchRun`, mêmes colonnes de cycle
de vie) : écritures d'état conditionnelles, jalons appendus atomiquement,
garde zombie, requalification des orphelins au démarrage, et le corps du job
lui-même (les différences — sanitisation du payload du digest — sont des
paramètres, pas des copies).

⚠️ Mono-process : comme `search_cancel`, l'annulation (jeton = run id)
suppose UN seul process uvicorn — le thread et le registre d'annulation
vivent dans le même process que l'endpoint stop. L'exclusivité « un run actif
par médecin », elle, est garantie en base (index unique partiel par table).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text as sql_text, update

from app.db import CorpusSessionLocal, SessionLocal
from app.services import search_cancel
from app.services.search_cancel import SearchCancelled

# La journée d'un run est celle du médecin, pas celle du serveur (UTC).
PARIS = ZoneInfo("Europe/Paris")

ACTIVE_STATUSES = ("running", "translating")

# Un run actif sans battement de cœur (updated_at) depuis ce délai est un
# zombie (thread tué sans écrire son état, ex. kill -9) : on le requalifie en
# erreur pour libérer l'index unique partiel. Les jalons du pipeline arrivent
# au pire toutes les ~2 min (jugement codex) — 2 h est très large.
STALE_ACTIVE_AFTER = timedelta(hours=2)


def set_run(model, run_id: uuid.UUID, **values) -> int:
    """Écrit l'état d'un run dans une session courte dédiée (le thread de
    génération ne doit pas committer dans la session de `_run_deep_search`).

    Transition CONDITIONNELLE : n'écrit que si le run est encore actif. Un run
    requalifié en zombie (garde 2 h, redémarrage) ou arrêté par l'endpoint
    stop ne peut donc pas être « ressuscité » par son ancien thread qui
    écrirait translating/complete par-dessus — l'écriture devient un no-op.
    Renvoie le nombre de lignes réellement modifiées (0 ou 1)."""
    with SessionLocal() as s:
        res = s.execute(
            update(model)
            .where(model.id == run_id, model.status.in_(ACTIVE_STATUSES))
            .values(updated_at=datetime.now(PARIS), **values)
        )
        s.commit()
        return res.rowcount


def stop_run(
    model, run_id: uuid.UUID, from_statuses: tuple[str, ...] = ACTIVE_STATUSES
) -> bool:
    """Transition SQL d'un arrêt demandé par l'utilisateur — la table est la
    source de vérité : le run cesse IMMÉDIATEMENT d'être actif (l'index unique
    partiel est libéré, une nouvelle recherche peut partir sans attendre que
    le thread observe l'annulation ; ses écritures deviennent des no-ops).

    `from_statuses` permet au digest de ne stopper que la phase `running` :
    pendant `translating`, le résultat est déjà acquis et la politique du
    digest est qu'un stop de traduction ne le perd pas (le run finit
    `complete`, seules les traductions manquent)."""
    now = datetime.now(PARIS)
    with SessionLocal() as s:
        res = s.execute(
            update(model)
            .where(model.id == run_id, model.status.in_(from_statuses))
            .values(status="stopped", finished_at=now, updated_at=now)
        )
        s.commit()
        return bool(res.rowcount)


def append_log(model, run_id: uuid.UUID, event: dict) -> None:
    """Ajoute un jalon par UPDATE atomique `logs = logs || …` — pas de liste
    JSONB mutée côté ORM (SQLAlchemy ne détecterait pas la mutation). Touche
    aussi `updated_at` : c'est le battement de cœur du run. Conditionné aux
    statuts actifs, comme `set_run` : un run stoppé/requalifié n'est plus
    modifié par son ancien thread."""
    with SessionLocal() as s:
        s.execute(
            sql_text(
                f"UPDATE {model.__tablename__} SET logs = logs || CAST(:ev AS jsonb), "  # noqa: S608 — nom de table constant, jamais utilisateur
                "updated_at = now() "
                "WHERE id = :id AND status IN ('running', 'translating')"
            ),
            {"ev": json.dumps([event], ensure_ascii=False), "id": run_id},
        )
        s.commit()


def requalify_stale(session, model, doctor_id: uuid.UUID, error_msg: str) -> None:
    """Libère l'index unique d'éventuels runs zombies du médecin avant d'en
    insérer un nouveau : actifs mais sans battement de cœur depuis 2 h.

    UN SEUL UPDATE portant tous les prédicats (pas de SELECT-puis-UPDATE par
    id : un heartbeat arrivé entre les deux ferait tuer un run redevenu
    vivant) ; on n'annule que les jetons des lignes réellement requalifiées
    (RETURNING) — si leur thread vit encore malgré tout, il s'arrête au
    prochain jalon (et ses écritures d'état sont devenues des no-ops)."""
    stale_ids = session.scalars(
        update(model)
        .where(
            model.doctor_id == doctor_id,
            model.status.in_(ACTIVE_STATUSES),
            model.updated_at < datetime.now(PARIS) - STALE_ACTIVE_AFTER,
        )
        .values(status="error", error=error_msg, finished_at=datetime.now(PARIS))
        .returning(model.id)
    ).all()
    session.commit()
    for stale_id in stale_ids:
        search_cancel.cancel(str(stale_id))


def mark_orphans(model, error_msg: str) -> None:
    """Au démarrage de l'API : les runs restés actifs appartiennent à un
    process mort (les threads ne survivent pas à un redémarrage) → erreur
    explicite. Best-effort : une base pas encore migrée ne doit pas empêcher
    l'API de démarrer (dev_up applique les migrations juste avant)."""
    try:
        with SessionLocal() as s:
            s.execute(
                update(model)
                .where(model.status.in_(ACTIVE_STATUSES))
                .values(
                    status="error", error=error_msg, finished_at=datetime.now(PARIS)
                )
            )
            s.commit()
    except Exception:
        pass


def run_deep_job(
    model,
    run_id: uuid.UUID,
    req,  # DeepSearchRequest (import local — voir plus bas)
    notif_query: str,
    user_email: str,
    cancel_state: search_cancel.CancelState,
    *,
    sanitize: Callable[[object], None] | None = None,
    strip_log_keys: tuple[str, ...] = (),
    strip_metric_keys: tuple[str, ...] = (),
    keep_result_on_stop: bool = False,
) -> None:
    """Corps d'un run, exécuté dans un thread détaché de la requête HTTP.

    Le jeton d'annulation est enregistré par l'ENDPOINT, avant le démarrage du
    thread : un stop qui arrive entre le POST et le premier jalon trouve donc
    toujours un état à annuler (pas de fenêtre aveugle).

    `sanitize` : hook appliqué au résultat AVANT persistance et notification —
    le digest y retire tout ce qui révèle le profil clinique (metaprompt,
    requête PubMed, facettes) ; la recherche n'assainit rien (la query est
    celle que l'utilisateur a tapée, l'historique est fait pour la garder).
    `strip_log_keys` / `strip_metric_keys` : même hygiène pour les jalons
    persistés et les métriques de notification.
    `keep_result_on_stop` : politique du stop pendant la phase de traduction —
    True (digest) : le résultat déjà acquis n'est pas perdu, le run finit
    `complete` sans les traductions ; False (recherche) : l'arrêt est honoré,
    le run finit `stopped` (le payload posé en `translating` reste en base).

    Volontairement indépendant du thread qui le porte : basculer un jour sur
    un vrai worker (Celery/RQ) reviendra à appeler cette fonction ailleurs.
    """
    # Imports locaux : app.api.search importe déjà des services — un import de
    # module ici recréerait le cycle au chargement.
    from app.api.search import _deep_metrics, _run_deep_search, _translate_kept
    from app.services.search_notifications import send_search_notification

    token = req.local_token
    # Contextvar par thread : les appels codex du pipeline deviennent
    # annulables (le endpoint stop tue le sous-processus en vol).
    search_cancel.current_search.set(cancel_state)

    t0 = time.monotonic()
    progress_events: list[dict] = []

    def progress(phase: str, msg: str, data: dict) -> None:
        # Point d'arrêt coopératif : une annulation prend effet au prochain jalon.
        cancel_state.raise_if_cancelled()
        elapsed = round(time.monotonic() - t0, 1)
        data = {k: v for k, v in data.items() if k not in strip_log_keys}
        event = {"phase": phase, "msg": f"{msg} ({elapsed}s)", "elapsed_s": elapsed, **data}
        progress_events.append(event)
        append_log(model, run_id, event)

    notified = False
    try:
        # Deux sessions, une par monde : la recherche lit le corpus, le cache de
        # traduction (article_fr) vit côté app. Voir app/db.py.
        with CorpusSessionLocal() as corpus, SessionLocal() as session:
            result = _run_deep_search(req, corpus, session, progress)
            if sanitize is not None:
                sanitize(result)
            metrics = _deep_metrics(result)
            for key in strip_metric_keys:
                metrics.pop(key, None)
            # Notif dès que la recherche a abouti (la traduction qui suit est
            # un post-traitement best-effort, pas un échec du run).
            send_search_notification(
                status="ok", query=notif_query,
                duration_s=time.monotonic() - t0,
                metrics=metrics,
                progress_events=progress_events,
                user=user_email,
            )
            notified = True
            # Payload visible dès maintenant : l'utilisateur qui revient sur la
            # page voit ses articles pendant que les traductions se terminent.
            set_run(
                model, run_id,
                status="translating",
                payload=result.model_dump(),
                n_results=len(result.results),
            )
            # Traductions best-effort : un échec ne doit jamais faire perdre
            # le résultat déjà obtenu. Un STOP, lui, suit la politique de
            # l'appelant (voir `keep_result_on_stop`) — ne pas laisser le
            # except générique avaler l'annulation.
            try:
                fr = _translate_kept(result, corpus, session, progress)
            except SearchCancelled:
                if not keep_result_on_stop:
                    raise
                fr = {}
            except Exception:
                fr = {}
            for h in result.results:
                t = fr.get(str(h.pmid))
                if t:
                    h.title_fr = t.get("title_fr") or h.title_fr
                    h.abstract_fr = t.get("abstract_fr") or h.abstract_fr
            set_run(
                model, run_id,
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
        set_run(model, run_id, status="stopped", finished_at=datetime.now(PARIS))
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
        set_run(
            model, run_id,
            status="error", error=str(msg), finished_at=datetime.now(PARIS),
        )
    finally:
        search_cancel.unregister(token)
