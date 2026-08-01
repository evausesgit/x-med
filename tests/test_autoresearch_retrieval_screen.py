from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.api import search as search_api
from experiments.autoresearch_xmed.run_retrieval_screen import (
    RetrievalConfig,
    build_parser,
    screen_case,
    select_batch,
    validate_live_source,
    validate_screen_case,
)
from experiments.autoresearch_xmed.score import InvalidArtifact


def _live_source() -> dict:
    builder = {
        "pubmed_query": "hypertension[tiab]",
        "mesh_terms": ["Hypertension"],
        "keywords_en": ["hypertension", "blood pressure"],
    }
    return {
        "run_kind": "live",
        "complete": True,
        "read_only": True,
        "database": "xmed_autoresearch",
        "expected_query_ids": ["q01"],
        "cases": [
            {
                "query_id": "q01",
                "query": "prise en charge de l'hypertension",
                "pubmed_query": builder["pubmed_query"],
                "mesh_terms": builder["mesh_terms"],
                "keywords_en": builder["keywords_en"],
                "external": {"query_builder": {"data": builder}},
                "error": None,
            }
        ],
    }


def test_live_source_requires_exact_ids_and_query_builder_capture():
    source = _live_source()
    assert validate_live_source(source) == source["cases"]

    source["expected_query_ids"] = ["wrong"]
    with pytest.raises(InvalidArtifact, match="query_id"):
        validate_live_source(source)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda run: run.update(read_only=False), "read-only"),
        (lambda run: run["cases"][0].update(error="boom"), "dégradé"),
        (
            lambda run: run["cases"][0].update(pubmed_query="different[tiab]"),
            "incohérente",
        ),
        (
            lambda run: run["cases"][0]["external"].pop("query_builder"),
            "query-builder absente",
        ),
    ],
)
def test_live_source_rejects_unproven_builder_or_safety(mutation, message):
    source = deepcopy(_live_source())
    mutation(source)
    with pytest.raises(InvalidArtifact, match=message):
        validate_live_source(source)


def test_selection_reserves_local_slots_and_excludes_missing_abstracts():
    config = RetrievalConfig(judge_batch=4, local_floor=2)
    candidates, judgeable, selected = select_batch(
        pubmed_pmids=[10, 11, 12, 13],
        local_pmids=[20, 21],
        abstract_pmids={10, 11, 12, 13, 20, 21},
        config=config,
    )
    assert candidates == [10, 11, 12, 13, 20, 21]
    assert judgeable == candidates
    assert selected == [10, 11, 20, 21]

    _, judgeable, selected = select_batch(
        pubmed_pmids=[10, 11, 12, 13],
        local_pmids=[20, 21],
        abstract_pmids={10, 12, 20},
        config=config,
    )
    assert judgeable == [10, 12, 20]
    assert selected == judgeable


def test_selection_passes_the_declared_rrf_constant(monkeypatch):
    seen = {}

    def candidate_order(pubmed, local, rrf, k=60):
        seen.update(pubmed=pubmed, local=local, rrf=rrf, k=k)
        return [3, 1, 2]

    monkeypatch.setattr(search_api, "_candidate_order", candidate_order)
    config = RetrievalConfig(rrf=True, rrf_k=17, judge_batch=2)
    candidates, judgeable, selected = select_batch([1, 2], [3], {1, 2, 3}, config)
    assert seen == {"pubmed": [1, 2], "local": [3], "rrf": True, "k": 17}
    assert candidates == [3, 1, 2]
    assert judgeable == candidates
    assert selected == [3, 1]


def test_screen_case_requires_exact_selected_ids_and_unique_hierarchy():
    case = {
        "candidate_pmids": [1, 2, 3],
        "judgeable_pmids": [1, 3],
        "judge_pmids": [3],
        "judge_items": [{"pmid": 3}],
        "selected_metadata": [{"pmid": 3}],
    }
    validate_screen_case(case)

    case["selected_metadata"] = [{"pmid": 1}]
    with pytest.raises(ValueError, match="selected_metadata"):
        validate_screen_case(case)


def test_screen_case_reuses_builder_and_stops_before_judgement(monkeypatch):
    case = deepcopy(_live_source()["cases"][0])
    case.update(date_from="2025-01-01", date_to="2026-12-31")
    calls = {}

    def esearch(term, **kwargs):
        calls["esearch"] = (term, kwargs)
        return 100, [1, 2]

    def local_search(case_arg, builder_arg, config_arg, corpus):
        del corpus
        calls["local"] = (case_arg["query_id"], builder_arg, config_arg.k_pubmed)
        return [3], {
            "source": "articles",
            "timed_out": False,
            "error": None,
            "elapsed_s": 0.01,
        }

    articles = {
        1: SimpleNamespace(
            pmid=1,
            title="local 1",
            abstract="abstract 1",
            journal="J1",
            pub_year=2026,
            pub_date=None,
            evidence_level=1,
            doi="doi-1",
        ),
        3: SimpleNamespace(
            pmid=3,
            title="local 3",
            abstract="abstract 3",
            journal="J3",
            pub_year=2026,
            pub_date=None,
            evidence_level=2,
            doi="doi-3",
        ),
    }
    external = SimpleNamespace(pmid=2, title="external 2", journal="J2", pub_year=2025, doi="doi-2")
    monkeypatch.setattr(
        "experiments.autoresearch_xmed.run_retrieval_screen._local_search", local_search
    )
    monkeypatch.setattr(
        "experiments.autoresearch_xmed.run_retrieval_screen.pubmed_eutils.esearch", esearch
    )
    monkeypatch.setattr(search_api, "_fetch_articles", lambda corpus, pmids: articles)
    monkeypatch.setattr(
        "experiments.autoresearch_xmed.run_retrieval_screen.pubmed_eutils.esummary",
        lambda pmids: {2: external},
    )
    monkeypatch.setattr(
        "experiments.autoresearch_xmed.run_retrieval_screen.pubmed_eutils.efetch_abstracts",
        lambda pmids: {2: "abstract 2"},
    )

    config = RetrievalConfig(k_pubmed=50, judge_batch=3)
    result = screen_case(case, config, lambda: nullcontext(object()))

    builder = case["external"]["query_builder"]["data"]
    assert calls["esearch"] == (
        builder["pubmed_query"],
        {"retmax": 50, "mindate": "2025-01-01", "maxdate": "2026-12-31"},
    )
    assert calls["local"] == ("q01", builder, 50)
    assert result["candidate_pmids"] == [1, 2, 3]
    assert result["judge_pmids"] == [1, 2, 3]
    assert [item["pmid"] for item in result["judge_items"]] == [1, 2, 3]
    assert result["selected_metadata"][1]["in_db"] is False
    assert result["selected_metadata"][1]["abstract"] == "abstract 2"

    case["selected_metadata"] = [{"pmid": 3}]
    case["candidate_pmids"] = [1, 1, 3]
    with pytest.raises(ValueError, match="doublons"):
        validate_screen_case(case)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"k_pubmed": 0},
        {"judge_batch": 0},
        {"rrf_k": 0},
        {"max_local": -1},
        {"local_floor": -1},
        {"k_pubmed": True},
        {"rrf": 1},
    ],
)
def test_config_rejects_ambiguous_or_out_of_range_knobs(kwargs):
    with pytest.raises(ValueError):
        RetrievalConfig(**kwargs)


def test_parser_exposes_every_screening_knob():
    args = build_parser().parse_args(
        [
            "live.json",
            "--out",
            "screen.json",
            "--k-pubmed",
            "50",
            "--max-local",
            "100",
            "--judge-batch",
            "32",
            "--rrf",
            "--rrf-k",
            "30",
            "--local-floor",
            "8",
            "--use-narrow-search",
        ]
    )
    assert (
        args.k_pubmed,
        args.max_local,
        args.judge_batch,
        args.rrf,
        args.rrf_k,
        args.local_floor,
        args.use_narrow_search,
    ) == (50, 100, 32, True, 30, 8, True)
