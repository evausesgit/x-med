"""Trace du jugement : le verdict de CHAQUE abstract soumis à codex.

Sans elle, un « 50 jugés → 3 retenus » est une boîte noire : les 47 écartés ne
figurent ni dans `results` (filtrés par `min_score`) ni dans `remaining` (le
vivier jamais soumis), et la sortie brute de codex n'est pas conservée
(`run_codex` écrit dans un `TemporaryDirectory`). `_judge_detail` est la seule
trace persistée de ces articles — elle part dans les jalons du run.

Fonction pure : ni base ni réseau.
"""

from app.api.search import JUDGE_LOG_TITLE_CHARS, _judge_detail
from app.services.codex_judge import Judgement

TITLES = {
    1: "Sleep apnea and floppy eyelid syndrome",
    2: "Marginal paper on eyelids",
    3: "Off-topic paper about turbines",
    4: "Submitted but never answered",
}


def _titles(p: int) -> str:
    return TITLES[p]


SCORES = {
    1: Judgement(score=3, reason="Mesure la prévalence.", relevance_pct=91),
    2: Judgement(score=1, reason="Lien indirect.", relevance_pct=40),
    3: Judgement(score=0, reason="Hors sujet.", relevance_pct=5),
    # Le PMID 4 est volontairement absent : codex n'a rien renvoyé pour lui.
}


def test_rejected_articles_are_traced():
    """Le cœur du besoin : les écartés existent dans la trace, avec leur raison."""
    rows = _judge_detail([1, 2, 3, 4], _titles, SCORES, min_score=2)
    assert len(rows) == 4, "un article soumis = une ligne, retenu ou non"
    by_pmid = {r["pmid"]: r for r in rows}
    assert by_pmid[3]["kept"] is False
    assert by_pmid[3]["score"] == 0
    assert by_pmid[3]["reason"] == "Hors sujet."


def test_kept_flag_follows_min_score():
    """`kept` reproduit exactement le filtre de `_run_deep_search` (score ≥ seuil)."""
    rows = {r["pmid"]: r["kept"] for r in _judge_detail(
        [1, 2, 3], _titles, SCORES, min_score=2
    )}
    assert rows == {1: True, 2: False, 3: False}
    # Seuil abaissé : le marginal (score 1) devient retenu.
    relaxed = {r["pmid"]: r["kept"] for r in _judge_detail(
        [1, 2, 3], _titles, SCORES, min_score=1
    )}
    assert relaxed == {1: True, 2: True, 3: False}


def test_unanswered_article_is_not_a_rejection():
    """Un article soumis dont codex n'a rien dit garde `score: null` — il ne doit
    pas être confondu avec un rejet argumenté."""
    row = next(r for r in _judge_detail([4], _titles, SCORES, min_score=2))
    assert row["score"] is None
    assert row["relevance_pct"] is None
    assert row["kept"] is False


def test_rows_are_sorted_like_the_final_ranking():
    """Ordre score décroissant puis % : la trace se lit comme les résultats."""
    rows = _judge_detail([4, 3, 2, 1], _titles, SCORES, min_score=2)
    assert [r["pmid"] for r in rows] == [1, 2, 3, 4]


def test_titles_are_truncated():
    """La trace est persistée en JSONB dans les jalons : on borne les titres."""
    long_titles = {9: "T" * 500}
    rows = _judge_detail([9], lambda p: long_titles[p], {}, min_score=2)
    assert len(rows[0]["title"]) == JUDGE_LOG_TITLE_CHARS


def test_empty_batch_is_empty_trace():
    assert _judge_detail([], _titles, {}, min_score=2) == []
