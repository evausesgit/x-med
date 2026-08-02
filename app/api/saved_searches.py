"""Recherches sauvegardées : enregistrer le résultat d'une recherche pour y
revenir, le relire et le réutiliser plus tard.

On stocke un snapshot complet (`payload`, forme `DeepSearchResponse`) : rouvrir
une recherche n'appelle donc PAS codex à nouveau. Pour l'instant pas de contrôle
d'accès — tout le monde voit toutes les recherches (le profil n'est qu'un
classement). Voir le modèle `app/models/saved_search.py`.

Le **tri** utilisé (sélecteur « TRI » : `v1` = score IA, `v2` = fusion RRF) fait
partie de l'identité d'une recherche : la MÊME question triée autrement donne un
autre classement, donc un autre snapshot. Il est rangé dans `params["sort"]`
(pas de colonne dédiée : `params` est déjà le sac des réglages de la recherche)
et entre dans la comparaison du `lookup`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
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
    # Tri du résultat sauvegardé ("v1" score IA / "v2" fusion RRF). Champ à part
    # pour l'appelant, rangé dans `params["sort"]` en base (cf. `_with_sort`).
    sort: str | None = None


class SavedSearchSummary(BaseModel):
    id: str
    doctor_id: str | None
    doctor_name: str | None
    query: str
    method: str
    sort: str | None  # tri utilisé, lu dans params["sort"] (None = avant ce champ)
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


def _norm(v: Any) -> str | None:
    """Normalise une valeur de paramètre pour la comparaison : "" → None."""
    return (str(v).strip() or None) if v is not None else None


DEFAULT_SORT = "v1"  # tri historique du sélecteur « TRI » (score IA)


def _sort_of(params: dict[str, Any] | None) -> str | None:
    """Tri d'une recherche sauvegardée, ou None pour les lignes d'avant ce champ."""
    return _norm((params or {}).get("sort"))


def _with_sort(params: dict[str, Any] | None, sort: str | None) -> dict[str, Any] | None:
    """Range le tri dans `params` (le champ explicite de l'appelant gagne)."""
    if sort is None:
        return params
    return {**(params or {}), "sort": sort}


def _sort_match(stored: str | None, wanted: str | None) -> bool:
    """Deux recherches ne partagent un snapshot que si elles ont le MÊME tri.

    Les lignes sauvegardées avant l'introduction du champ n'ont pas de tri : on
    les rattache au tri par défaut du sélecteur, celui avec lequel elles ont
    presque toujours été produites. Elles restent donc réutilisables en `v1`
    sans jamais être servies à la place d'un vrai résultat `v2`.
    """
    return (stored or DEFAULT_SORT) == (wanted or DEFAULT_SORT)


def _params_match(
    stored: dict[str, Any] | None,
    date_from: str | None,
    date_to: str | None,
    sort: str | None = None,
) -> bool:
    """Une recherche est « la même » si la fenêtre de dates ET le tri coïncident
    (vide == absent)."""
    stored = stored or {}
    return (
        _norm(stored.get("date_from")) == _norm(date_from)
        and _norm(stored.get("date_to")) == _norm(date_to)
        and _sort_match(_sort_of(stored), sort)
    )


def _summary(s: SavedSearch) -> SavedSearchSummary:
    return SavedSearchSummary(
        id=str(s.id),
        doctor_id=str(s.doctor_id) if s.doctor_id else None,
        doctor_name=_doctor_name(s),
        query=s.query,
        method=s.method,
        sort=_sort_of(s.params),
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
        params=_with_sort(body.params, body.sort),
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


@router.get("/saved-searches/lookup", response_model=SavedSearchDetail | None)
def lookup_saved_search(
    query: str,
    method: str = "v2",
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str | None = None,
    session: Session = Depends(get_session),
):
    """Cherche une recherche déjà sauvegardée identique (même requête normalisée,
    même méthode, même fenêtre de dates, même tri) pour éviter de relancer codex.
    Renvoie le snapshot le plus récent, ou `null` si rien ne correspond.

    Le tri fait partie de la clé : la même question sauvegardée en `v1` et en
    `v2` donne deux snapshots distincts, chacun retrouvé par son propre tri.

    ⚠ Doit rester déclarée AVANT `/saved-searches/{search_id}`, sinon « lookup »
    serait capturé comme un identifiant.
    """
    normalized = query.strip().lower()
    rows = session.scalars(
        select(SavedSearch)
        .where(func.lower(func.trim(SavedSearch.query)) == normalized)
        .where(SavedSearch.method == method)
        .order_by(SavedSearch.created_at.desc())
    ).all()
    for s in rows:
        if _params_match(s.params, date_from, date_to, sort):
            return _detail(s)
    return None


@router.get("/saved-searches/{search_id}", response_model=SavedSearchDetail)
def get_saved_search(search_id: str, session: Session = Depends(get_session)):
    return _detail(_get(session, search_id))


@router.delete("/saved-searches/{search_id}", status_code=204)
def delete_saved_search(search_id: str, session: Session = Depends(get_session)):
    session.delete(_get(session, search_id))
    session.commit()
