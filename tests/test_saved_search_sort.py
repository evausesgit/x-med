"""Le tri fait partie de l'identité d'une recherche sauvegardée.

Une même question, triée « v1 · score IA » ou « v2 · fusion RRF », donne deux
classements différents : ce sont deux snapshots distincts, et le `lookup` (qui
sert à éviter un appel codex payant) ne doit jamais servir l'un pour l'autre.
Tests purs sur les helpers de `app/services/saved_search_store.py` (l'identité
d'une recherche, partagée par le lookup et la sauvegarde automatique) — pas de
base.
"""

from __future__ import annotations

from app.services.saved_search_store import (
    DEFAULT_SORT,
    params_match as _params_match,
    sort_of as _sort_of,
    with_sort as _with_sort,
)


def _params(sort=None, date_from="2025-01-01", date_to="2025-12-31"):
    p = {"date_from": date_from, "date_to": date_to}
    if sort is not None:
        p["sort"] = sort
    return p


def test_same_query_two_sorts_are_two_distinct_searches():
    """Le cœur de la fonctionnalité : v1 et v2 ne se recouvrent pas."""
    v1 = _params(sort="v1")
    v2 = _params(sort="v2")
    assert _params_match(v1, "2025-01-01", "2025-12-31", "v1")
    assert not _params_match(v1, "2025-01-01", "2025-12-31", "v2")
    assert _params_match(v2, "2025-01-01", "2025-12-31", "v2")
    assert not _params_match(v2, "2025-01-01", "2025-12-31", "v1")


def test_dates_still_part_of_the_key():
    """Le tri s'ajoute à la fenêtre de dates, il ne la remplace pas."""
    stored = _params(sort="v2")
    assert not _params_match(stored, "2024-01-01", "2025-12-31", "v2")
    assert not _params_match(stored, "2025-01-01", None, "v2")


def test_legacy_rows_answer_for_the_default_sort_only():
    """Les lignes d'avant le champ n'ont pas de tri : elles restent réutilisables
    sous le tri par défaut du sélecteur, jamais servies à la place d'un v2."""
    legacy = _params()
    assert _sort_of(legacy) is None
    assert _params_match(legacy, "2025-01-01", "2025-12-31", DEFAULT_SORT)
    assert _params_match(legacy, "2025-01-01", "2025-12-31", None)
    assert not _params_match(legacy, "2025-01-01", "2025-12-31", "v2")


def test_with_sort_writes_into_params_without_losing_the_rest():
    assert _with_sort({"date_from": "2025-01-01"}, "v2") == {
        "date_from": "2025-01-01",
        "sort": "v2",
    }
    assert _with_sort(None, "v1") == {"sort": "v1"}
    # Aucun tri fourni (vieux client) : on n'invente pas de valeur.
    assert _with_sort({"date_to": "2025-12-31"}, None) == {"date_to": "2025-12-31"}
    assert _with_sort(None, None) is None


def test_sort_of_normalises_blank_values():
    """« » ou None → pas de tri (même normalisation que les dates)."""
    assert _sort_of({"sort": "  v2 "}) == "v2"
    assert _sort_of({"sort": ""}) is None
    assert _sort_of({"sort": None}) is None
    assert _sort_of(None) is None
