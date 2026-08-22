"""Sauvegarde automatique des recherches + nettoyage de l'historique.

Depuis la suppression du bouton « sauvegarder », toute recherche aboutie entre
d'office dans `saved_searches`. Deux propriétés à protéger :

1. ce que la sauvegarde auto ÉCRIT est exactement ce que le lookup CHERCHE —
   sinon chaque relance de la même question ajouterait un doublon que personne
   ne retrouve (et un appel codex payant à chaque fois) ;
2. la politique de rétention supprime bien les recherches trop vieilles ou en
   trop, et rien d'autre.

Tests purs sur `app/services/saved_search_store.py` — pas de base.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.services.saved_search_store import (
    autosave_params,
    n_results,
    params_match,
    sort_of_run,
    to_delete,
)


# ---------- Ce qui est écrit est ce qui est cherché ----------

def test_autosaved_params_are_found_back_by_the_lookup():
    """La ligne écrite par la sauvegarde auto doit matcher le lookup de la même
    recherche : c'est ce qui évite le doublon (et l'appel codex) à la relance."""
    p = autosave_params("2025-01-01", "2025-12-31", "v2")
    assert params_match(p, "2025-01-01", "2025-12-31", "v2")


def test_autosaved_params_do_not_collide_across_sorts_or_windows():
    p = autosave_params("2025-01-01", "2025-12-31", "v2")
    assert not params_match(p, "2025-01-01", "2025-12-31", "v1")
    assert not params_match(p, "2024-01-01", "2025-12-31", "v2")


def test_search_without_dates_is_also_found_back():
    """Recherche sans fenêtre de dates : None écrit, None cherché."""
    p = autosave_params(None, None, "v1")
    assert params_match(p, None, None, "v1")
    assert not params_match(p, "2025-01-01", None, "v1")


def test_sort_of_run_reads_the_rrf_flag():
    """Le run ne connaît que `rrf` ; l'historique parle en v1/v2."""
    assert sort_of_run({"rrf": True}) == "v2"
    assert sort_of_run({"rrf": False}) == "v1"
    assert sort_of_run({}) == "v1"
    assert sort_of_run(None) == "v1"


def test_n_results_counts_the_kept_articles():
    assert n_results({"results": [{"pmid": 1}, {"pmid": 2}]}) == 2
    assert n_results({}) == 0
    assert n_results({"results": None}) == 0


# ---------- Rétention ----------

def _rows(ages_days: list[int]) -> list[tuple[uuid.UUID, datetime]]:
    """(id, created_at) du plus récent au plus ancien, à partir d'âges en jours."""
    now = datetime.now(timezone.utc)
    return [(uuid.uuid4(), now - timedelta(days=d)) for d in sorted(ages_days)]


def test_old_searches_are_deleted():
    rows = _rows([1, 10, 100, 200])
    doomed = to_delete(rows, days=90, max_rows=0)
    assert {r[0] for r in rows[2:]} == doomed  # 100 j et 200 j
    assert not {r[0] for r in rows[:2]} & doomed


def test_cap_deletes_the_oldest_beyond_the_limit():
    rows = _rows([1, 2, 3, 4, 5])
    doomed = to_delete(rows, days=0, max_rows=3)
    assert doomed == {r[0] for r in rows[3:]}


def test_both_limits_apply_together():
    rows = _rows([1, 2, 200])
    doomed = to_delete(rows, days=90, max_rows=2)
    assert doomed == {rows[2][0]}  # la vieille, visée par les deux règles


def test_limits_at_zero_delete_nothing():
    """0 = limite désactivée : un historique non borné reste possible."""
    rows = _rows([1, 500, 5000])
    assert to_delete(rows, days=0, max_rows=0) == set()


def test_empty_history_is_a_no_op():
    assert to_delete([], days=90, max_rows=500) == set()


def test_naive_timestamps_are_read_as_utc():
    """`created_at` est un timestamp sans fuseau en base : le comparer à un
    « maintenant » aware ne doit pas lever."""
    old = (datetime.now(timezone.utc) - timedelta(days=200)).replace(tzinfo=None)
    rid = uuid.uuid4()
    assert to_delete([(rid, old)], days=90, max_rows=0) == {rid}
