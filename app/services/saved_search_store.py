"""Recherches sauvegardées : identité d'une recherche, sauvegarde automatique
et nettoyage de l'historique.

Il n'y a plus de bouton « sauvegarder » : **toute recherche aboutie est
enregistrée d'office** (voir `run_store.run_deep_job`, hook `on_complete`). La
table `saved_searches` cesse donc d'être une collection choisie à la main pour
devenir l'historique complet des recherches — d'où les deux règles ci-dessous.

1. **Une ligne par recherche distincte** (`autosave`). Relancer la même
   question, même fenêtre de dates, même tri et même profil ne crée pas une
   nouvelle ligne : le snapshot existant est rafraîchi. Sans ça, chaque
   « Relancer quand même » empilerait un doublon de plusieurs centaines de Ko.

2. **Nettoyage** (`purge`) : l'historique est borné en âge ET en nombre
   (`SAVED_SEARCH_RETENTION_DAYS`, `SAVED_SEARCH_MAX_ROWS`), sinon la table
   grossit indéfiniment — chaque ligne porte le `payload` complet (jusqu'à
   quelques centaines de Ko d'abstracts). Lancé par
   `scripts/cleanup_saved_searches.py`.

L'identité d'une recherche (requête + méthode + fenêtre de dates + tri) est
définie ici et utilisée aux deux bouts : par le `lookup` de l'API (éviter un
appel codex payant en resservant un snapshot) et par la sauvegarde automatique
(reconnaître la recherche à rafraîchir). Une seule définition pour les deux :
si elles divergeaient, on créerait des doublons que le lookup ne retrouverait
jamais.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import SavedSearch

# Tri historique du sélecteur « TRI » (score IA) : c'est le tri sous lequel se
# rangent les lignes sauvegardées avant l'existence du champ.
DEFAULT_SORT = "v1"


# ---------- Identité d'une recherche ----------

def norm(v: Any) -> str | None:
    """Normalise une valeur de paramètre pour la comparaison : "" → None."""
    return (str(v).strip() or None) if v is not None else None


def norm_query(query: str) -> str:
    """Forme normalisée d'une question (la casse et les espaces ne comptent pas)."""
    return query.strip().lower()


def sort_of(params: dict[str, Any] | None) -> str | None:
    """Tri d'une recherche sauvegardée, ou None pour les lignes d'avant ce champ."""
    return norm((params or {}).get("sort"))


def with_sort(
    params: dict[str, Any] | None, sort: str | None
) -> dict[str, Any] | None:
    """Range le tri dans `params` (le champ explicite de l'appelant gagne)."""
    if sort is None:
        return params
    return {**(params or {}), "sort": sort}


def sort_match(stored: str | None, wanted: str | None) -> bool:
    """Deux recherches ne partagent un snapshot que si elles ont le MÊME tri.

    Les lignes sauvegardées avant l'introduction du champ n'ont pas de tri : on
    les rattache au tri par défaut du sélecteur, celui avec lequel elles ont
    presque toujours été produites. Elles restent donc réutilisables en `v1`
    sans jamais être servies à la place d'un vrai résultat `v2`.
    """
    return (stored or DEFAULT_SORT) == (wanted or DEFAULT_SORT)


def params_match(
    stored: dict[str, Any] | None,
    date_from: str | None,
    date_to: str | None,
    sort: str | None = None,
) -> bool:
    """Une recherche est « la même » si la fenêtre de dates ET le tri coïncident
    (vide == absent)."""
    stored = stored or {}
    return (
        norm(stored.get("date_from")) == norm(date_from)
        and norm(stored.get("date_to")) == norm(date_to)
        and sort_match(sort_of(stored), sort)
    )


def sort_of_run(params: dict[str, Any] | None) -> str:
    """Tri d'un run de recherche : le front n'envoie que le drapeau `rrf`
    (v2 = fusion RRF, sinon v1 = score IA) — même conversion que la page."""
    return "v2" if (params or {}).get("rrf") else "v1"


def autosave_params(
    date_from: str | None, date_to: str | None, sort: str | None
) -> dict[str, Any]:
    """Les `params` écrits par la sauvegarde automatique.

    Écrits ici, relus par `params_match` (lookup) : les deux doivent rester
    d'accord, sinon la sauvegarde auto créerait des lignes que le lookup ne
    retrouverait jamais — donc un doublon à chaque relance de la question.
    """
    return {"date_from": date_from, "date_to": date_to, "sort": sort}


def n_results(payload: dict[str, Any]) -> int:
    results = payload.get("results")
    return len(results) if isinstance(results, list) else 0


# ---------- Sauvegarde automatique ----------

def find_existing(
    session: Session,
    *,
    query: str,
    method: str,
    date_from: str | None,
    date_to: str | None,
    sort: str | None,
    doctor_id: uuid.UUID | None,
) -> SavedSearch | None:
    """La ligne à rafraîchir pour cette recherche, ou None.

    Le profil fait partie de la clé : deux médecins qui posent la même question
    gardent chacun leur entrée (le `doctor_id` est un classement, et on ne veut
    pas qu'une recherche change de profil dans le dos de son auteur). Le
    `lookup` de l'API, lui, ignore le profil : le snapshot le plus récent
    évite un appel codex à tout le monde.
    """
    rows = session.scalars(
        select(SavedSearch)
        .where(func.lower(func.trim(SavedSearch.query)) == norm_query(query))
        .where(SavedSearch.method == method)
        .where(
            SavedSearch.doctor_id == doctor_id
            if doctor_id is not None
            else SavedSearch.doctor_id.is_(None)
        )
        .order_by(SavedSearch.created_at.desc())
    ).all()
    for s in rows:
        if params_match(s.params, date_from, date_to, sort):
            return s
    return None


def autosave(
    *,
    query: str,
    payload: dict[str, Any],
    doctor_id: uuid.UUID | None = None,
    method: str = "v2",
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str | None = None,
    session: Session | None = None,
) -> uuid.UUID:
    """Enregistre (ou rafraîchit) le snapshot d'une recherche aboutie.

    Appelée depuis le thread du run : elle ouvre sa propre session courte, sauf
    si l'appelant en fournit une (tests). Renvoie l'id de la ligne écrite.
    """
    if session is not None:
        return _autosave(session, query, payload, doctor_id, method,
                         date_from, date_to, sort)
    with SessionLocal() as s:
        return _autosave(s, query, payload, doctor_id, method,
                         date_from, date_to, sort)


def _autosave(
    session: Session,
    query: str,
    payload: dict[str, Any],
    doctor_id: uuid.UUID | None,
    method: str,
    date_from: str | None,
    date_to: str | None,
    sort: str | None,
) -> uuid.UUID:
    params = autosave_params(date_from, date_to, sort)
    existing = find_existing(
        session,
        query=query,
        method=method,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        doctor_id=doctor_id,
    )
    if existing is not None:
        # Même recherche relancée : on rafraîchit le snapshot au lieu d'empiler
        # un doublon, et `created_at` porte la date du résultat affiché.
        existing.query = query.strip()
        existing.params = params
        existing.payload = payload
        existing.n_results = n_results(payload)
        existing.created_at = datetime.now(timezone.utc)
        session.commit()
        return existing.id

    row = SavedSearch(
        doctor_id=doctor_id,
        query=query.strip(),
        method=method,
        params=params,
        payload=payload,
        n_results=n_results(payload),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.id


# ---------- Nettoyage ----------

def _too_old(rows: list[tuple[uuid.UUID, datetime]], days: int) -> set[uuid.UUID]:
    """Ids des recherches plus vieilles que `days` jours (0 = pas de limite d'âge)."""
    if days <= 0:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return {
        rid
        for rid, created in rows
        if _aware(created) < cutoff
    }


def _over_cap(rows: list[tuple[uuid.UUID, datetime]], max_rows: int) -> set[uuid.UUID]:
    """Ids des recherches au-delà du plafond, les plus vieilles d'abord
    (0 = pas de plafond). `rows` est trié du plus récent au plus ancien."""
    if max_rows <= 0:
        return set()
    return {rid for rid, _ in rows[max_rows:]}


def _aware(dt: datetime) -> datetime:
    """`created_at` est en `timestamp without time zone` (UTC en base)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def to_delete(
    rows: list[tuple[uuid.UUID, datetime]], *, days: int, max_rows: int
) -> set[uuid.UUID]:
    """Recherches à supprimer : trop vieilles OU au-delà du plafond.

    `rows` : (id, created_at) du plus récent au plus ancien. Séparé du SQL pour
    être testable sans base — c'est ici que vit la politique de rétention.
    """
    return _too_old(rows, days) | _over_cap(rows, max_rows)


def purge(
    *,
    days: int | None = None,
    max_rows: int | None = None,
    dry_run: bool = False,
    session: Session | None = None,
) -> int:
    """Applique la politique de rétention. Renvoie le nombre de lignes visées
    (supprimées, ou qui l'auraient été en `dry_run`)."""
    days = settings.saved_search_retention_days if days is None else days
    max_rows = settings.saved_search_max_rows if max_rows is None else max_rows
    if session is not None:
        return _purge(session, days, max_rows, dry_run)
    with SessionLocal() as s:
        return _purge(s, days, max_rows, dry_run)


def _purge(session: Session, days: int, max_rows: int, dry_run: bool) -> int:
    rows = [
        (r.id, r.created_at)
        for r in session.execute(
            select(SavedSearch.id, SavedSearch.created_at).order_by(
                SavedSearch.created_at.desc()
            )
        ).all()
    ]
    doomed = to_delete(rows, days=days, max_rows=max_rows)
    if doomed and not dry_run:
        for row in session.scalars(
            select(SavedSearch).where(SavedSearch.id.in_(doomed))
        ).all():
            session.delete(row)
        session.commit()
    return len(doomed)
