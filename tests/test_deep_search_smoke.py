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
    """Session CORPUS — celle qui porte le pré-filtre FTS et les lectures articles."""
    from app.db import CorpusSessionLocal

    return CorpusSessionLocal()


def _app_session():
    """Session APP — celle du cache de traduction `article_fr`."""
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


@pytest.fixture(scope="module")
def app_db():
    with _app_session() as s:
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
        # Bornes de dates reçues par esearch — doivent rester None (cf. le test
        # `test_esearch_is_not_date_bounded`).
        self.esearch_dates: tuple[str | None, str | None] | None = None
        self.events: list[tuple[str, str]] = []
        # Données portées par les jalons (le jalon `judge_detail` transporte le
        # verdict de chaque abstract soumis).
        self.event_data: dict[str, dict] = {}

    def progress(self, phase, msg, data):
        self.events.append((phase, msg))
        self.event_data[phase] = data


@pytest.fixture
def spy(monkeypatch, corpus):
    s = _Spy()

    def fake_build(question, timeout=180, session=None):
        return (
            {
                "pubmed_query": f"{LOCAL_TERM}[tiab]",
                "mesh_terms": ["Neoplasms"],
                "keywords_en": [LOCAL_TERM],
                # Mots-clés groupés par concept : c'est cette structure que le
                # pré-filtre local rejoue en ET (voir _local_tsquery).
                "concepts_en": [[LOCAL_TERM]],
            },
            CodexUsage(input_tokens=100, output_tokens=20),
        )

    def fake_esearch(term, retmax=20, sort="relevance", reldate=None,
                     mindate=None, maxdate=None):
        s.esearch_dates = (mindate, maxdate)
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


def test_v1_runs_end_to_end(session, app_db, spy, corpus):
    resp = _run_deep_search(_req(rrf=False), session, app_db, spy.progress)

    assert resp.query_builder == "codex"
    assert resp.judge == "codex"
    assert resp.pubmed_query == f"{LOCAL_TERM}[tiab]"
    assert resp.counts["pubmed"] == len(corpus["a_pmids"])
    assert resp.counts["local"] > 0, "le pré-filtre FTS local n'a rien trouvé"
    assert resp.counts["judged"] == len(spy.judged_pmids)
    assert resp.results, "aucun article retenu alors que la doublure note tout à 3"
    assert spy.judge_calls == 1


def test_results_are_sorted_by_judged_relevance(session, app_db, spy):
    resp = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    keys = [
        (-(h.score or -1), -(h.relevance_pct or -1),
         h.evidence_level if h.evidence_level is not None else 99, -(h.pub_year or 0))
        for h in resp.results
    ]
    assert keys == sorted(keys), "le tri final doit rester le score du juge"


def test_esearch_is_not_date_bounded(session, app_db, spy):
    """PubMed est interrogé SANS bornes de dates, même quand la recherche en a.

    Régression : avec le défaut « depuis 2025 », un sujet à littérature ancienne
    (floppy eyelid syndrome × glaucome à pression normale) renvoyait 0 article
    alors que PubMed en a une douzaine. La fenêtre ne filtre plus le rappel, elle
    ne sert plus qu'à signaler les articles hors période.
    """
    _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    assert spy.esearch_dates == (None, None), (
        "esearch ne doit plus recevoir mindate/maxdate : le filtrage amont "
        f"vidait les résultats des sujets anciens (reçu : {spy.esearch_dates})"
    )


def test_local_only_candidates_stay_date_bounded(session, app_db, spy):
    """Le vivier LOCAL reste borné : `_prefilter_source` s'appuie sur la borne
    basse pour rester sur la table chaude. Seul PubMed est débridé."""
    resp = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    for h in resp.results:
        if h.source == "local" and h.pub_year is not None:
            assert 2025 <= h.pub_year <= 2026, f"{h.pmid} hors fenêtre : {h.pub_year}"
        assert h.out_of_window is False, (
            f"{h.pmid} ({h.pub_year}) est dans la fenêtre, il ne doit pas être marqué"
        )


def test_ranking_follows_relevance_even_when_the_best_is_out_of_window(
    session, app_db, spy, corpus, monkeypatch
):
    """Le plus pertinent est premier, même publié hors de la fenêtre demandée.

    Mesuré en conditions réelles : trier la période demandée en premier enterrait
    la vraie réponse sur les sujets à littérature ancienne (les recommandations de
    traitement du syndrome de Susac, 98 % de pertinence, passaient sous un article
    à 82 % dont le seul mérite était sa date). La date n'entre donc pas dans le
    tri, elle est signalée par `out_of_window`.

    Le cas est DISCRIMINANT : on donne à l'article ancien le MEILLEUR score
    (3 contre 2), et on le place en tête de la liste PubMed. S'il repassait
    dernier, c'est qu'une clé de date se serait réintroduite dans le tri.
    """
    OLD_PMID = 999_000_002

    def with_old(term, retmax=20, sort="relevance", reldate=None,
                 mindate=None, maxdate=None):
        return 1, [OLD_PMID, *corpus["a_pmids"][:retmax - 1]]

    def judge_old_best(query, items):
        scores = {
            i["pmid"]: Judgement(
                score=3 if i["pmid"] == OLD_PMID else 2,
                reason="doublure",
                relevance_pct=99 if i["pmid"] == OLD_PMID else 50,
            )
            for i in items
        }
        return scores, CodexUsage(input_tokens=500, output_tokens=50)

    monkeypatch.setattr(codex_judge, "judge_articles", judge_old_best)
    monkeypatch.setattr(pubmed_eutils, "esearch", with_old)
    monkeypatch.setattr(
        pubmed_eutils, "esummary",
        lambda pmids: {
            OLD_PMID: pubmed_eutils.PubmedHit(
                pmid=OLD_PMID, title="Article ancien mais pertinent",
                journal="J. Ancien", pub_year=1997, doi=None,
            )
        },
    )
    monkeypatch.setattr(
        pubmed_eutils, "efetch_abstracts",
        lambda pmids: {OLD_PMID: "Un abstract jugé aussi pertinent que les autres."},
    )

    resp = _run_deep_search(_req(rrf=False), session, app_db, spy.progress)

    ordre = [(h.pmid, h.pub_year, h.out_of_window) for h in resp.results]
    assert resp.results[0].pmid == OLD_PMID, (
        "l'article de 1997 est le mieux jugé (score 3 / 99 %) : il doit être PREMIER "
        f"malgré sa date, sinon la fenêtre s'est réinvitée dans le tri — {ordre}"
    )
    assert resp.results[0].out_of_window is True, (
        "…et il doit rester marqué « hors période » : on le montre en tête, mais on "
        "ne cache pas au médecin qu'il est ancien"
    )
    flags = [h.out_of_window for h in resp.results]
    assert any(not f for f in flags), "le test n'a pas de témoin dans la fenêtre"


def test_out_of_window_pubmed_article_is_kept_and_flagged(
    session, app_db, spy, monkeypatch
):
    """Un article PubMed ANCIEN, jugé pertinent, est rendu — marqué, pas écarté.

    C'est la contrepartie du débridage d'esearch : plutôt qu'une page vide, le
    médecin voit l'article de 1997 avec un badge « hors période ».
    """
    OLD_PMID, OLD_YEAR = 999_000_001, 1997

    def only_old(term, retmax=20, sort="relevance", reldate=None,
                 mindate=None, maxdate=None):
        spy.esearch_dates = (mindate, maxdate)
        return 1, [OLD_PMID]

    monkeypatch.setattr(pubmed_eutils, "esearch", only_old)
    monkeypatch.setattr(
        pubmed_eutils, "esummary",
        lambda pmids: {
            OLD_PMID: pubmed_eutils.PubmedHit(
                pmid=OLD_PMID, title="Floppy eyelid syndrome and normal tension glaucoma",
                journal="Ophthalmology", pub_year=OLD_YEAR, doi=None,
            )
        },
    )
    monkeypatch.setattr(
        pubmed_eutils, "efetch_abstracts",
        lambda pmids: {OLD_PMID: "Association between floppy eyelid syndrome and NTG."},
    )

    resp = _run_deep_search(_req(rrf=False, max_local=0), session, app_db, spy.progress)

    hit = next((h for h in resp.results if h.pmid == OLD_PMID), None)
    assert hit is not None, "l'article hors fenêtre a été écarté au lieu d'être rendu"
    assert hit.pub_year == OLD_YEAR
    assert hit.out_of_window is True, "il doit porter le badge « hors période »"
    assert resp.counts["kept_out_of_window"] == 1
    assert any(p == "out_of_window" for p, _ in spy.events), (
        "le déroulé doit annoncer les articles retenus hors fenêtre"
    )


def test_sources_are_labelled(session, app_db, spy, corpus):
    resp = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    by_pmid = {h.pmid: h for h in resp.results}
    for pmid in corpus["pubmed_only"]:
        if pmid in by_pmid:
            assert by_pmid[pmid].source == "pubmed"
            assert by_pmid[pmid].in_db is True
    for pmid in corpus["overlap"]:
        if pmid in by_pmid:
            assert by_pmid[pmid].source in ("both", "pubmed")


def test_judge_batch_is_capped_and_rest_is_paginated(session, app_db, spy):
    resp = _run_deep_search(_req(rrf=True, judge_batch=5), session, app_db, spy.progress)

    assert len(spy.judged_pmids) <= 5
    assert set(resp.remaining).isdisjoint(spy.judged_pmids), (
        "`remaining` ne doit pas reproposer des articles déjà jugés"
    )


# --------------------------------------------------------------------------- #
# v1 vs v2 : la différence se voit sur ce que le juge reçoit
# --------------------------------------------------------------------------- #


def test_v1_and_v2_send_different_candidates_to_the_judge(session, app_db, spy, corpus):
    """Le cœur du test : les deux modes doivent choisir différemment QUI est jugé.
    Les PMID communs aux deux listes sont volontairement placés en fin de liste
    PubMed — v1 les laisse derrière, la fusion RRF de v2 doit les remonter."""
    _run_deep_search(_req(rrf=False), session, app_db, spy.progress)
    sent_v1 = list(spy.judged_pmids)

    _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
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


def test_local_floor_reserves_slots_in_the_real_pipeline(session, app_db, spy, corpus):
    """Le plancher testé unitairement (test 3) doit produire l'effet attendu
    dans le vrai pipeline : des candidats locaux-seuls dans le lot jugé."""
    a_set = set(corpus["a_pmids"])
    _run_deep_search(_req(rrf=True, judge_batch=8, local_floor=4), session, app_db, spy.progress)
    local_only = [p for p in spy.judged_pmids if p not in a_set]
    assert len(local_only) >= 4


# --------------------------------------------------------------------------- #
# Les replis quand codex tombe
# --------------------------------------------------------------------------- #


def test_query_builder_failure_falls_back_to_the_raw_question(session, app_db, spy, monkeypatch):
    def boom(question, timeout=180, session=None):
        raise QueryBuildError("codex indisponible")

    monkeypatch.setattr(query_builder, "build_pubmed_query", boom)
    resp = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)

    assert resp.query_builder == "fallback"
    assert resp.judge == "codex"
    assert resp.results, "un échec du constructeur ne doit pas vider la recherche"
    # Sans codex il n'y a pas de mot-clé ANGLAIS : le pré-filtre local est sauté
    # au lieu d'envoyer la question FRANÇAISE à un index anglais (vivier 0 muet).
    phases = [p for p, _ in spy.events]
    assert "filter_skipped" in phases
    assert "filter_start" not in phases
    assert resp.counts["local"] == 0


def test_the_and_of_concepts_actually_restricts_the_pool(session, app_db, spy, monkeypatch):
    """Deux concepts en ET ⊂ un concept seul — le ET filtre vraiment (vraie base).

    C'est la propriété qui rend le pré-filtre rapide : chaque concept ajouté
    réduit le nombre de lignes que `ORDER BY ts_rank` doit détoaster.
    """
    def two_concepts(question, timeout=180, session=None):
        return (
            {
                "pubmed_query": f"{LOCAL_TERM}[tiab]",
                "mesh_terms": [],
                "keywords_en": [LOCAL_TERM, PUBMED_ONLY_TERM],
                "concepts_en": [[LOCAL_TERM], [PUBMED_ONLY_TERM]],
            },
            CodexUsage(input_tokens=100, output_tokens=20),
        )

    wide = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    monkeypatch.setattr(query_builder, "build_pubmed_query", two_concepts)
    narrow = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)

    assert wide.counts["local"] > 0, "le pré-filtre FTS local n'a rien trouvé"
    # Les deux sujets sont disjoints (dermatologie / gynécologie) : leur ET est vide.
    assert narrow.counts["local"] < wide.counts["local"]


def test_judge_failure_degrades_without_losing_results(session, app_db, spy, monkeypatch):
    def boom(query, items):
        raise JudgeError("codex indisponible")

    monkeypatch.setattr(codex_judge, "judge_articles", boom)
    resp = _run_deep_search(_req(rrf=True), session, app_db, spy.progress)

    assert resp.judge == "skipped"
    assert resp.results, "sans juge on rend le vivier brut, pas une page vide"
    assert all(h.score is None for h in resp.results)
    assert resp.remaining == [], "pas de « 50 de plus » quand le juge est HS"


def test_progress_events_cover_the_pipeline(session, app_db, spy):
    _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    phases = [p for p, _ in spy.events]
    for expected in ("codex", "esearch", "filter_start", "judge", "judge_detail", "done"):
        assert expected in phases, f"jalon de progression manquant : {expected}"


def test_judge_detail_traces_the_articles_dropped_by_the_judge(
    session, app_db, spy, monkeypatch
):
    """Le besoin qui a motivé le jalon : après un « 10 jugés → 5 retenus », les
    5 écartés ne sont dans AUCUNE autre sortie (ni `results`, ni `remaining`).
    Le jalon `judge_detail` doit les porter, avec leur note et leur raison."""

    def alternating_judge(query, items):
        spy.judge_calls += 1
        spy.judged_pmids = [i["pmid"] for i in items]
        scores = {
            i["pmid"]: Judgement(
                score=3 if k % 2 == 0 else 0,
                reason="retenu" if k % 2 == 0 else "hors sujet",
                relevance_pct=90 if k % 2 == 0 else 5,
            )
            for k, i in enumerate(items)
        }
        return scores, CodexUsage(input_tokens=500, output_tokens=50)

    monkeypatch.setattr(codex_judge, "judge_articles", alternating_judge)
    resp = _run_deep_search(_req(rrf=True, judge_batch=10), session, app_db, spy.progress)

    rows = spy.event_data["judge_detail"]["judgements"]
    assert len(rows) == len(spy.judged_pmids), "une ligne par abstract soumis"

    kept_pmids = {h.pmid for h in resp.results}
    dropped = [r for r in rows if not r["kept"]]
    assert dropped, "la doublure écarte un article sur deux"
    for r in dropped:
        assert r["pmid"] not in kept_pmids
        assert r["pmid"] not in resp.remaining, (
            "un écarté n'est pas dans le vivier restant : le jalon est sa seule trace"
        )
        assert r["reason"] == "hors sujet", "la raison du rejet doit être conservée"
    assert {r["pmid"] for r in rows if r["kept"]} == kept_pmids


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


# --------------------------------------------------------------------------- #
# Frontière app/corpus : chaque moteur reste de son côté
# --------------------------------------------------------------------------- #

CORPUS_TABLES = ("articles", "article_search", "mesh_descriptors", "ftp_state")
APP_TABLES = ("article_fr", "doctors", "doctor_profiles", "saved_searches",
              "search_runs", "digest_runs", "usage_events")


def _tables_hit(statements: list[str], names: tuple[str, ...]) -> set[str]:
    import re

    hit: set[str] = set()
    for st in statements:
        for name in names:
            if re.search(rf"\b{name}\b", st):
                hit.add(name)
    return hit


def test_engines_stay_on_their_side_of_the_frontier(session, app_db, spy):
    """Contrat de séparation (PLAN_BASES_SEPAREES.md) : pendant une recherche
    complète, le moteur APP n'émet aucune requête vers les tables corpus et le
    moteur CORPUS aucune vers les tables métier. Tant que les deux URLs pointent
    sur la même base, seul ce test prouve le routage — une session mal aiguillée
    y trouverait toutes les tables sans erreur."""
    from sqlalchemy import event

    from app.db import corpus_engine, engine as app_engine

    seen: dict[str, list[str]] = {"app": [], "corpus": []}

    def _watch(key):
        def listener(conn, cursor, statement, parameters, context, executemany):
            seen[key].append(statement)

        return listener

    app_l, corpus_l = _watch("app"), _watch("corpus")
    event.listen(app_engine, "before_cursor_execute", app_l)
    event.listen(corpus_engine, "before_cursor_execute", corpus_l)
    try:
        _run_deep_search(_req(rrf=True), session, app_db, spy.progress)
    finally:
        event.remove(app_engine, "before_cursor_execute", app_l)
        event.remove(corpus_engine, "before_cursor_execute", corpus_l)

    crossed_app = _tables_hit(seen["app"], CORPUS_TABLES)
    crossed_corpus = _tables_hit(seen["corpus"], APP_TABLES)
    assert not crossed_app, f"le moteur app a touché le corpus : {crossed_app}"
    assert not crossed_corpus, f"le moteur corpus a touché l'app : {crossed_corpus}"
    # Sanity : le test a bien observé les deux mondes travailler (sinon il ne
    # prouverait rien — ex. listeners inopérants ou pipeline court-circuité).
    assert _tables_hit(seen["corpus"], ("articles",)), "pré-filtre corpus non observé"
    assert _tables_hit(seen["app"], ("article_fr",)), "cache FR (app) non observé"
