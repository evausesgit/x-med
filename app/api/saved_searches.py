"""Recherches sauvegardées : enregistrer le résultat d'une recherche pour y
revenir, le relire et le réutiliser plus tard.

On stocke un snapshot complet (`payload`, forme `DeepSearchResponse`) : rouvrir
une recherche n'appelle donc PAS codex à nouveau. Pour l'instant pas de contrôle
d'accès — tout le monde voit toutes les recherches (le profil n'est qu'un
classement). Voir le modèle `app/models/saved_search.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Doctor, SavedSearch

router = APIRouter()


# ---------- Schémas ----------

class SavedSearchIn(BaseModel):
    query: str
    payload: dict[str, Any]  # réponse complète de la recherche (DeepSearchResponse)
    doctor_id: str | None = None
    method: str = "v2"
    params: dict[str, Any] | None = None


class SavedSearchSummary(BaseModel):
    id: str
    doctor_id: str | None
    doctor_name: str | None
    query: str
    method: str
    n_results: int
    created_at: datetime


class SavedSearchDetail(SavedSearchSummary):
    params: dict[str, Any] | None
    payload: dict[str, Any]


def _doctor_name(s: SavedSearch) -> str | None:
    return s.doctor.name if s.doctor is not None else None


def _n_results(payload: dict[str, Any]) -> int:
    results = payload.get("results")
    return len(results) if isinstance(results, list) else 0


def _summary(s: SavedSearch) -> SavedSearchSummary:
    return SavedSearchSummary(
        id=str(s.id),
        doctor_id=str(s.doctor_id) if s.doctor_id else None,
        doctor_name=_doctor_name(s),
        query=s.query,
        method=s.method,
        n_results=s.n_results,
        created_at=s.created_at,
    )


def _detail(s: SavedSearch) -> SavedSearchDetail:
    return SavedSearchDetail(
        **_summary(s).model_dump(),
        params=s.params,
        payload=s.payload,
    )


def _get(session: Session, search_id: str) -> SavedSearch:
    try:
        sid = uuid.UUID(search_id)
    except ValueError:
        raise HTTPException(400, "Identifiant de recherche invalide")
    s = session.get(SavedSearch, sid)
    if s is None:
        raise HTTPException(404, "Recherche sauvegardée introuvable")
    return s


# ---------- Endpoints ----------

@router.post("/saved-searches", response_model=SavedSearchDetail, status_code=201)
def create_saved_search(body: SavedSearchIn, session: Session = Depends(get_session)):
    doctor_id: uuid.UUID | None = None
    if body.doctor_id:
        try:
            doctor_id = uuid.UUID(body.doctor_id)
        except ValueError:
            raise HTTPException(400, "Identifiant médecin invalide")
        if session.get(Doctor, doctor_id) is None:
            raise HTTPException(404, "Médecin introuvable")

    s = SavedSearch(
        doctor_id=doctor_id,
        query=body.query,
        method=body.method,
        params=body.params,
        payload=body.payload,
        n_results=_n_results(body.payload),
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return _detail(s)


@router.get("/saved-searches", response_model=list[SavedSearchSummary])
def list_saved_searches(session: Session = Depends(get_session)):
    """Toutes les recherches sauvegardées, plus récentes d'abord (vue partagée)."""
    rows = session.scalars(
        select(SavedSearch).order_by(SavedSearch.created_at.desc())
    ).all()
    return [_summary(s) for s in rows]


@router.get("/saved-searches/{search_id}", response_model=SavedSearchDetail)
def get_saved_search(search_id: str, session: Session = Depends(get_session)):
    return _detail(_get(session, search_id))


@router.delete("/saved-searches/{search_id}", status_code=204)
def delete_saved_search(search_id: str, session: Session = Depends(get_session)):
    session.delete(_get(session, search_id))
    session.commit()
