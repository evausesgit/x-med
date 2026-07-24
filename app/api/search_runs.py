"""Recherche en arrière-plan : la recherche v2 détachée de la connexion.

Même modèle que le digest (voir `services/run_store.py`) : POSTer lance la
pipeline dans un thread détaché de la requête HTTP, la table `search_runs`
est la source de vérité et le front la POLLE. Verrouiller son téléphone,
changer d'app ou fermer l'onglet n'interrompt plus la recherche — le résultat
attend en base, et chaque run abouti devient une entrée de l'historique de
recherche du compte.

Contrairement au digest, AUCUNE sanitisation du payload : la query est celle
que l'utilisateur a tapée (l'historique est fait pour la garder), et la page
affiche la requête PubMed construite et les MeSH. La table reste protégée par
l'ACL par médecin.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.exc import IntegrityError

from app.api.digest import StopRunResponse
from app.api.me import Identity, _find_doctor, current_identity, ensure_doctor
from app.api.search import DeepSearchRequest
from app.db import SessionLocal
from app.models import SearchRun
from app.services import run_store, search_cancel
from app.services.run_store import ACTIVE_STATUSES, PARIS
from app.services.usage_log import record_usage

router = APIRouter()

# Nombre de recherches abouties renvoyées par l'historique.
HISTORY_LIMIT = 20


class SearchRunCreate(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    date_from: date | None = None
    date_to: date | None = None
    k_pubmed: int = Field(default=20, ge=1, le=200)
    rrf: bool = False
    judge_batch: int = Field(default=50, ge=10, le=100)
    local_floor: int = Field(default=0, ge=0, le=100)


class SearchRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query: str
    date_from: date | None = None
    date_to: date | None = None
    params: dict
    status: str
    n_results: int
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class SearchRunOut(SearchRunSummary):
    logs: list[dict]
    payload: dict | None = None


class SearchRunHistory(BaseModel):
    # Run actif éventuel (running/translating) + derniers runs aboutis. Les
    # runs error/stopped restent en base (audit) mais pas dans l'historique.
    current: SearchRunSummary | None
    runs: list[SearchRunSummary]


def mark_orphan_runs() -> None:
    """Au démarrage de l'API (les threads ne survivent pas à un redémarrage)."""
    run_store.mark_orphans(
        SearchRun, "Recherche interrompue par un redémarrage du serveur."
    )


@router.post("/search/runs", response_model=SearchRunSummary)
def create_search_run(
    body: SearchRunCreate,
    request: Request,
    ident: Identity = Depends(current_identity),
):
    """Lance une recherche en arrière-plan et rend la main tout de suite (le
    front polle ensuite GET /search/runs/{id}). 409 si une recherche est déjà
    en cours pour ce compte — exclusivité garantie par l'index unique partiel
    `uq_search_runs_active` (indépendant de celui du digest : un digest et une
    recherche peuvent tourner en même temps)."""
    query = body.query.strip()
    if not query:
        raise HTTPException(422, "La question ne peut pas être vide.")
    with SessionLocal() as session:
        # La recherche n'exige pas de profil rempli : on crée la ligne Doctor
        # du compte au premier besoin (même logique guardée que /me/bootstrap).
        doctor = ensure_doctor(session, ident)
        run_store.requalify_stale(
            session, SearchRun, doctor.id,
            "Recherche abandonnée (aucune activité depuis 2 h).",
        )

        run = SearchRun(
            doctor_id=doctor.id,
            query=query,
            date_from=body.date_from,
            date_to=body.date_to,
            params={
                "k_pubmed": body.k_pubmed,
                "rrf": body.rrf,
                "judge_batch": body.judge_batch,
                "local_floor": body.local_floor,
            },
        )
        session.add(run)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                409, "Une recherche est déjà en cours pour votre compte."
            )
        session.refresh(run)
        summary = SearchRunSummary.model_validate(run)

    record_usage(
        request, "search.deep", query=query,
        params={
            "date_from": body.date_from.isoformat() if body.date_from else None,
            "date_to": body.date_to.isoformat() if body.date_to else None,
            "rrf": body.rrf,
            "background": True,
        },
    )

    req = DeepSearchRequest(
        query=query,
        date_from=body.date_from.isoformat() if body.date_from else None,
        date_to=body.date_to.isoformat() if body.date_to else None,
        k_pubmed=body.k_pubmed,
        rrf=body.rrf,
        judge_batch=body.judge_batch,
        local_floor=body.local_floor,
        # Le run id sert de jeton d'annulation (stop + pg_cancel du FTS local).
        local_token=str(summary.id),
    )
    # Le jeton d'annulation est enregistré AVANT le démarrage du thread : un
    # stop qui arrive juste après le POST trouve toujours un état à annuler.
    cancel_state = search_cancel.register(str(summary.id))
    try:
        if cancel_state is None:  # impossible : le run id est un UUID neuf
            raise RuntimeError("jeton de recherche déjà utilisé")
        Thread(
            target=run_store.run_deep_job,
            args=(SearchRun, summary.id, req, query, ident.email, cancel_state),
            daemon=True,
        ).start()
    except Exception as exc:
        # Sans thread, la ligne resterait `running` pour toujours (et l'index
        # unique bloquerait toute nouvelle recherche) : on la clôt en erreur.
        search_cancel.unregister(str(summary.id))
        run_store.set_run(
            SearchRun, summary.id,
            status="error",
            error=f"Impossible de démarrer la recherche : {exc}",
            finished_at=datetime.now(PARIS),
        )
        raise HTTPException(500, "Impossible de démarrer la recherche. Réessayez.")
    return summary


def _get_own_run(session, ident: Identity, run_id: uuid.UUID) -> SearchRun:
    """Charge un run en vérifiant qu'il appartient au médecin connecté."""
    doctor = _find_doctor(session, ident)
    run = session.get(SearchRun, run_id)
    if doctor is None or run is None or run.doctor_id != doctor.id:
        raise HTTPException(404, "Recherche introuvable.")
    return run


@router.get("/search/runs/{run_id}", response_model=SearchRunOut)
def get_search_run(
    run_id: uuid.UUID, ident: Identity = Depends(current_identity)
):
    """État complet d'un run (statut + jalons + payload) — l'endpoint que le
    front polle pendant la recherche et pour rouvrir une recherche passée."""
    with SessionLocal() as session:
        return SearchRunOut.model_validate(_get_own_run(session, ident, run_id))


@router.post("/search/runs/{run_id}/stop", response_model=StopRunResponse)
def stop_search_run(
    run_id: uuid.UUID, ident: Identity = Depends(current_identity)
):
    """Arrête la recherche en cours : l'appel codex en vol est tué, la requête
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


@router.get("/search/runs", response_model=SearchRunHistory)
def search_run_history(ident: Identity = Depends(current_identity)):
    """Historique du compte connecté : le run actif éventuel + les dernières
    recherches abouties (récent d'abord). Compte sans ligne Doctor = historique
    vide (la ligne n'est créée qu'au premier lancement)."""
    with SessionLocal() as session:
        doctor = _find_doctor(session, ident)
        if doctor is None:
            return SearchRunHistory(current=None, runs=[])
        current = session.scalars(
            select(SearchRun)
            .where(
                SearchRun.doctor_id == doctor.id,
                SearchRun.status.in_(ACTIVE_STATUSES),
            )
            .order_by(SearchRun.created_at.desc())
            .limit(1)
        ).first()
        runs = session.scalars(
            select(SearchRun)
            .where(
                SearchRun.doctor_id == doctor.id,
                SearchRun.status == "complete",
            )
            .order_by(SearchRun.created_at.desc())
            .limit(HISTORY_LIMIT)
        ).all()
    return SearchRunHistory(
        current=SearchRunSummary.model_validate(current) if current else None,
        runs=[SearchRunSummary.model_validate(r) for r in runs],
    )
