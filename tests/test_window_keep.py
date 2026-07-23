"""Fenêtre temporelle précise des candidats locaux-seuls (cf. `_window_keep`).

Le pré-filtre local ne borne qu'à l'année : ces tests fixent la politique
convenue — exclusion stricte quand `pub_date` prouve la sortie de fenêtre,
repli sur l'année (recall-first) quand la date exacte manque.
"""

from datetime import date

from app.api.search import _window_keep


def test_exact_date_out_of_window_is_dropped():
    # Fenêtre 30 jours dans la même année : janvier ne doit plus passer.
    keep, unverified = _window_keep(
        date(2026, 1, 15), 2026, "2026-06-23", None
    )
    assert keep is False
    assert unverified is False


def test_exact_date_inside_window_is_kept():
    keep, unverified = _window_keep(
        date(2026, 7, 1), 2026, "2026-06-23", None
    )
    assert keep is True
    assert unverified is False


def test_unknown_date_same_year_is_kept_but_flagged():
    # Date inconnue, année dans la fenêtre : conservé (recall-first), signalé.
    keep, unverified = _window_keep(None, 2026, "2026-06-23", None)
    assert keep is True
    assert unverified is True


def test_unknown_date_previous_year_is_dropped():
    keep, unverified = _window_keep(None, 2025, "2026-06-23", None)
    assert keep is False


def test_window_across_new_year():
    # Fenêtre 30 jours à cheval sur le Nouvel An : décembre N-1 reste dedans.
    keep, _ = _window_keep(date(2025, 12, 20), 2025, "2025-12-10", None)
    assert keep is True
    keep, _ = _window_keep(date(2025, 11, 30), 2025, "2025-12-10", None)
    assert keep is False
    # Date inconnue d'année N-1 : l'année (2025 >= année de 2025-12-10) suffit.
    keep, unverified = _window_keep(None, 2025, "2025-12-10", None)
    assert keep is True
    assert unverified is True


def test_upper_bound_and_no_window():
    keep, _ = _window_keep(date(2026, 7, 1), 2026, None, "2026-06-30")
    assert keep is False
    # Sans borne : tout passe, rien à vérifier.
    keep, unverified = _window_keep(None, None, None, None)
    assert keep is True
    assert unverified is False
