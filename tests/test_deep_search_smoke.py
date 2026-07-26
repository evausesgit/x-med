"""Recherche PubMed+IA de bout en bout, avec doublures — test 4 de l'étape 0.

Écrit **avant** le nettoyage (voir `PLAN_NETTOYAGE.md` § Étape 0, test 4).

C'est le test le plus proche du réel : il exécute la vraie fonction
`_run_deep_search` contre la vraie base, en remplaçant seulement les **trois
appels externes** (constructeur de requête GPT-5.6, PubMed E-utilities, juge
codex). Il couvre donc tout ce que les tests 1 à 3 ne voient pas : le pré-filtre
FTS, la fenêtre de dates, l'assemblage et le tri de la réponse, la pagination
`remaining`, et les replis quand codex tombe.

Le remplacement est facile parce que `_run_deep_search` fait ses imports **à
l'intérieur** de la fonction : `monkeypatch` sur l'attribut du module suffit.

**Nécessite Postgres** — le module entier est ignoré (`skip`) si la base n'est pas
joignable, pour ne pas casser la suite sur un poste sans base.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.api.search import DeepSearchRequest, _prefilter_source, _run_deep_search
from app.config import settings
from app.models import Article
from app.services import codex_judge, pubmed_eutils, query_builder
from app.services.codex_cli import CodexUsage
from app.services.codex_judge import Judgement, JudgeError
from app.services.query_builder import QueryBuildError

# Deux sujets rares et disjoints : le pré-filtre FTS répond vite (~1 s chacun) et
# les deux listes ne se recoupent pas, ce qui rend « local » et « PubMed » séparables.
LOCAL_TERM = "vismodegib"
PUBMED_ONLY_TERM = "isthmocele"
DATE_FROM, DATE_TO = "2025-01-01", "2026-12-31"


def _db_session():
    from app.db import SessionLocal

    return SessionLocal()


try:
    with _db_session() as _s:
        _s.execute(select(1))
    _DB_OK = True
except Exception:  # pragma: no cover - dépend de l'environnement
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="Postgres indisponible")


@pytest.fixture(scope="module")
def session():
    with _db_session() as s:
        yield s


def _top_pmids(session, term: str, n: int) -> list[int]:
    tsq = func.websearch_to_tsquery("english", term)
    return list(
        session.scalars(
            select(Article.pmid)
            .where(Article.fts.op("@@")(tsq), Article.pub_year >= 2025)
            .order_by(func.ts_rank(Article.fts, tsq).desc())
            .limit(n)
        ).all()
    )


@pytest.fixture(scope="module")
def corpus(session):
    """PMID réels tirés de la base — le test s'adapte au corpus local plutôt que
    de figer des identifiants qui n'existeraient pas sur un autre poste."""
    overlap = _top_pmids(session, LOCAL_TERM, 3)  # seront aussi trouvés en local
    pubmed_only = _top_pmids(session, PUBMED_ONLY_TERM, 3)  # PubMed seulement
    if len(overlap) < 3 or len(pubmed_only) < 3:
        pytest.skip("corpus local trop pauvre pour ce test")
    # Les PMID communs sont placés en FIN de liste PubMed : en v1 ils restent
    # derrière, en v2 la fusion RRF doit les faire remonter.
    return {"overlap": overlap, "pubmed_only": pubmed_only,
            "a_pmids": [*pubmed_only, *overlap]}


class _Spy:
    """Doublures des trois appels externes + trace de ce que le juge a reçu."""

    def __init__(self):
        self.judged_pmids: list[int] = []
        self.judge_calls = 0
        self.events: list[tuple[str, str]] = []

    def progress(self, phase, msg, data):
        self.events.append((phase, msg))


@pytest.fixture
def spy(monkeypatch, corpus):
    s = _Spy()

    def fake_build(question, timeout=180):
        return (
            {
                "pubmed_query": f"{LOCAL_TERM}[tiab]",
                "mesh_terms": ["Neoplasms"],
                "keywords_en": [LOCAL_TERM],
            },
            CodexUsage(input_tokens=100, output_tokens=20),
        )

    def fake_esearch(term, retmax=20, sort="relevance", reldate=None,
                     mindate=None, maxdate=None):
        pmids = corpus["a_pmids"][:retmax]
        return len(pmids), pmids

    def _forbidden(*a, **k):
        raise AssertionError(
            "esummary/efetch ne doivent pas être appelés : tous les PMID PubMed "
            "de ce test sont déjà en base"
        )

    def fake_judge(query, items):
        s.judge_calls += 1
        s.judged_pmids = [i["pmid"] for i in items]
        assert all((i.get("abstract") or "").strip() for i in items), (
            "le juge ne doit recevoir que des articles avec abstract"
        )
        scores = {
            i["pmid"]: Judgement(score=3, reason="doublure", relevance_pct=90)
            for i in items
        }
        return scores, CodexUsage(input_tokens=500, output_tokens=50)

    monkeypatch.setattr(query_builder, "build_pubmed_query", fake_build)
    monkeypatch.setattr(pubmed_eutils, "esearch", fake_esearch)
    monkeypatch.setattr(pubmed_eutils, "esummary", _forbidden)
    monkeypatch.setattr(pubmed_eutils, "efetch_abstracts", _forbidden)
    monkeypatch.setattr(codex_judge, "judge_articles", fake_judge)
    return s


def _req(**kw) -> DeepSearchRequest:
    base = dict(
        query="intérêt du vismodegib en traitement néoadjuvant",
        date_from=DATE_FROM,
        date_to=DATE_TO,
        k_pubmed=6,
        max_local=30,
        judge_batch=10,
    )
    return DeepSearchRequest(**{**base, **kw})


# --------------------------------------------------------------------------- #
# Le chemin nominal
# --------------------------------------------------------------------------- #


def test_v1_runs_end_to_end(session, spy, corpus):
    resp = _run_deep_search(_req(rrf=False), session, spy.progress)

    assert resp.query_builder == "codex"
    assert resp.judge == "codex"
    assert resp.pubmed_query == f"{LOCAL_TERM}[tiab]"
    assert resp.counts["pubmed"] == len(corpus["a_pmids"])
    assert resp.counts["local"] > 0, "le pré-filtre FTS local n'a rien trouvé"
    assert resp.counts["judged"] == len(spy.judged_pmids)
    assert resp.results, "aucun article retenu alors que la doublure note tout à 3"
    assert spy.judge_calls == 1


def test_results_are_sorted_by_judged_relevance(session, spy):
    resp = _run_deep_search(_req(rrf=True), session, spy.progress)
    keys = [
        (-(h.score or -1), -(h.relevance_pct or -1),
         h.evidence_level if h.evidence_level is not None else 99, -(h.pub_year or 0))
        for h in resp.results
    ]
    assert keys == sorted(keys), "le tri final doit rester le score du juge"


def test_date_window_is_respected(session, spy):
    resp = _run_deep_search(_req(rrf=True), session, spy.progress)
    for h in resp.results:
        if h.pub_year is not None:
            assert 2025 <= h.pub_year <= 2026, f"{h.pmid} hors fenêtre : {h.pub_year}"


def test_sources_are_labelled(session, spy, corpus):
    resp = _run_deep_search(_req(rrf=True), session, spy.progress)
    by_pmid = {h.pmid: h for h in resp.results}
    for pmid in corpus["pubmed_only"]:
        if pmid in by_pmid:
            assert by_pmid[pmid].source == "pubmed"
            assert by_pmid[pmid].in_db is True
    for pmid in corpus["overlap"]:
        if pmid in by_pmid:
            assert by_pmid[pmid].source in ("both", "pubmed")


def test_judge_batch_is_capped_and_rest_is_paginated(session, spy):
    resp = _run_deep_search(_req(rrf=True, judge_batch=5), session, spy.progress)

    assert len(spy.judged_pmids) <= 5
    assert set(resp.remaining).isdisjoint(spy.judged_pmids), (
        "`remaining` ne doit pas reproposer des articles déjà jugés"
    )


# --------------------------------------------------------------------------- #
# v1 vs v2 : la différence se voit sur ce que le juge reçoit
# --------------------------------------------------------------------------- #


def test_v1_and_v2_send_different_candidates_to_the_judge(session, spy, corpus):
    """Le cœur du test : les deux modes doivent choisir différemment QUI est jugé.
    Les PMID communs aux deux listes sont volontairement placés en fin de liste
    PubMed — v1 les laisse derrière, la fusion RRF de v2 doit les remonter."""
    _run_deep_search(_req(rrf=False), session, spy.progress)
    sent_v1 = list(spy.judged_pmids)

    _run_deep_search(_req(rrf=True), session, spy.progress)
    sent_v2 = list(spy.judged_pmids)

    assert sent_v1 != sent_v2, "v1 et v2 soumettent le même lot : la fusion RRF ne joue plus"
    assert sent_v1[: len(corpus["pubmed_only"])] == corpus["pubmed_only"], (
        "v1 doit garder l'ordre PubMed d'abord"
    )
    common = [p for p in corpus["overlap"] if p in sent_v2]
    if common:
        assert sent_v2.index(common[0]) < sent_v1.index(common[0]), (
            "v2 doit faire remonter un article trouvé des deux côtés"
        )


def test_local_floor_reserves_slots_in_the_real_pipeline(session, spy, corpus):
    """Le plancher testé unitairement (test 3) doit produire l'effet attendu
    dans le vrai pipeline : des candidats locaux-seuls dans le lot jugé."""
    a_set = set(corpus["a_pmids"])
    _run_deep_search(_req(rrf=True, judge_batch=8, local_floor=4), session, spy.progress)
    local_only = [p for p in spy.judged_pmids if p not in a_set]
    assert len(local_only) >= 4


# --------------------------------------------------------------------------- #
# Les replis quand codex tombe
# --------------------------------------------------------------------------- #


def test_query_builder_failure_falls_back_to_the_raw_question(session, spy, monkeypatch):
    def boom(question, timeout=180):
        raise QueryBuildError("codex indisponible")

    monkeypatch.setattr(query_builder, "build_pubmed_query", boom)
    resp = _run_deep_search(_req(rrf=True), session, spy.progress)

    assert resp.query_builder == "fallback"
    assert resp.judge == "codex"
    assert resp.results, "un échec du constructeur ne doit pas vider la recherche"


def test_judge_failure_degrades_without_losing_results(session, spy, monkeypatch):
    def boom(query, items):
        raise JudgeError("codex indisponible")

    monkeypatch.setattr(codex_judge, "judge_articles", boom)
    resp = _run_deep_search(_req(rrf=True), session, spy.progress)

    assert resp.judge == "skipped"
    assert resp.results, "sans juge on rend le vivier brut, pas une page vide"
    assert all(h.score is None for h in resp.results)
    assert resp.remaining == [], "pas de « 50 de plus » quand le juge est HS"


def test_progress_events_cover_the_pipeline(session, spy):
    _run_deep_search(_req(rrf=True), session, spy.progress)
    phases = [p for p, _ in spy.events]
    for expected in ("codex", "esearch", "filter_start", "judge", "done"):
        assert expected in phases, f"jalon de progression manquant : {expected}"


# --------------------------------------------------------------------------- #
# Routage du pré-filtre (pas de requête exécutée : instantané)
# --------------------------------------------------------------------------- #


def test_prefilter_routes_to_the_narrow_table_inside_the_window(session, monkeypatch):
    from app.models import ArticleSearch

    monkeypatch.setattr(settings, "use_narrow_search", True)
    min_year = session.scalar(select(func.article_search_min_year()))

    assert _prefilter_source(session, f"{min_year}-01-01") is ArticleSearch
    assert _prefilter_source(session, f"{min_year - 1}-01-01") is Article
    assert _prefilter_source(session, None) is Article, (
        "sans borne basse la recherche couvre tout l'historique"
    )


def test_prefilter_falls_back_to_full_table_when_disabled(session, monkeypatch):
    monkeypatch.setattr(settings, "use_narrow_search", False)
    assert _prefilter_source(session, "2026-01-01") is Article
