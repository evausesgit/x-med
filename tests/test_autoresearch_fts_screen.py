import json
from copy import deepcopy

import pytest

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_fts_screen import (
    BASELINE_MODE,
    FtsConfig,
    FtsScreenError,
    build_query_spec,
    choose_source_table,
    freeze_pruning,
    load_anchor_plan,
    paired_schedule,
    run_paired_specs,
    seal_anchor_plan,
    validate_fts_source,
)
from experiments.autoresearch_xmed.score import InvalidArtifact


def _live_source() -> dict:
    builder = {
        "pubmed_query": "hypertension[tiab]",
        "mesh_terms": ["Hypertension"],
        "keywords_en": ["hypertension", "high blood pressure", "treatment"],
    }
    return {
        "run_kind": "live",
        "run_id": "live-1",
        "complete": True,
        "read_only": True,
        "database": "xmed_autoresearch",
        "corpus_fingerprint": "corpus-fp",
        "machine_fingerprint": "machine-fp",
        "experiment": {"use_narrow_search": True},
        "expected_query_ids": ["q01"],
        "cases": [
            {
                "query_id": "q01",
                "query": "prise en charge de l'hypertension",
                "date_from": "2025-01-01",
                "date_to": "2026-12-31",
                "pubmed_query": builder["pubmed_query"],
                "mesh_terms": builder["mesh_terms"],
                "keywords_en": builder["keywords_en"],
                "external": {"query_builder": {"data": builder}},
                "error": None,
            }
        ],
    }


def test_source_requires_safe_complete_live_and_nonambiguous_keywords():
    source = _live_source()
    assert validate_fts_source(source) == source["cases"]

    unsafe = deepcopy(source)
    unsafe["read_only"] = False
    with pytest.raises(InvalidArtifact, match="read-only"):
        validate_fts_source(unsafe)

    ambiguous = deepcopy(source)
    ambiguous["cases"][0]["external"]["query_builder"]["data"]["keywords_en"] = [
        "same",
        "same",
    ]
    ambiguous["cases"][0]["keywords_en"] = ["same", "same"]
    with pytest.raises(InvalidArtifact, match="dupliqués"):
        validate_fts_source(ambiguous)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"candidate_mode": BASELINE_MODE},
        {"candidate_mode": "prune_frequent", "repetitions": 3},
        {"candidate_mode": "prune_frequent", "repetitions": 5},
        {"candidate_mode": "prune_frequent", "max_est_selectivity": 0},
        {"candidate_mode": "title_boost", "title_boost_weight": 0},
    ],
)
def test_config_refuses_ambiguous_or_thermally_unbalanced_protocol(kwargs):
    with pytest.raises(ValueError):
        FtsConfig(**kwargs)


def test_source_routing_matches_captured_narrow_mode():
    case = _live_source()["cases"][0]
    assert choose_source_table(case, use_narrow_search=True, min_year=2024) == "article_search"
    assert choose_source_table(case, use_narrow_search=False, min_year=2024) == "articles"
    old = {**case, "date_from": "2020-01-01"}
    assert choose_source_table(old, use_narrow_search=True, min_year=2024) == "articles"


def test_anchor_groups_must_be_a_frozen_exact_partition(tmp_path):
    source = _live_source()
    case = source["cases"][0]
    builder = case["external"]["query_builder"]["data"]
    plan = seal_anchor_plan(
        {
            "schema_version": 1,
            "mode": "anchors_and",
            "frozen_before_qrels": True,
            "expected_query_ids": ["q01"],
            "queries": {
                "q01": {
                    "query_builder_fingerprint": fingerprint(builder),
                    "groups": [["hypertension", "high blood pressure"], ["treatment"]],
                }
            },
        }
    )
    path = tmp_path / "anchors.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert load_anchor_plan(path, source["cases"]) == {
        "q01": [["hypertension", "high blood pressure"], ["treatment"]]
    }

    plan["queries"]["q01"]["groups"] = [["treatment"], ["hypertension"]]
    plan = seal_anchor_plan(plan)
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(FtsScreenError, match="ambigus"):
        load_anchor_plan(path, source["cases"])


def test_sql_modes_are_select_only_audited_and_title_boost_refuses_narrow_table():
    case = _live_source()["cases"][0]
    baseline = build_query_spec(case, BASELINE_MODE, "article_search")
    assert baseline["sql"].startswith("WITH q AS (SELECT websearch_to_tsquery")
    assert baseline["sql_kind"] == "select_only"
    assert baseline["sql_fingerprint"] == fingerprint(baseline["sql"])
    assert "ORDER BY rank DESC, s.pmid ASC" in baseline["sql"]

    anchors = build_query_spec(
        case,
        "anchors_and",
        "articles",
        anchor_groups=[["hypertension", "high blood pressure"], ["treatment"]],
    )
    assert "phraseto_tsquery" in anchors["sql"]
    assert " && " in anchors["sql"]
    assert " || " in anchors["sql"]

    title = build_query_spec(case, "title_boost", "articles", title_boost_weight=2.0)
    assert title["cost"]["extra_runtime_expression"] is True
    assert "to_tsvector('english', coalesce(s.title, ''))" in title["sql"]
    with pytest.raises(FtsScreenError, match="title est absente"):
        build_query_spec(case, "title_boost", "article_search")


class _PlannerConnection:
    def scalar(self, statement, params):
        sql = str(statement)
        if "reltuples" in sql:
            return 1_000
        rows = 100 if params["term"] == "hypertension" else 10
        return [{"Plan": {"Node Type": "Bitmap Heap Scan", "Plan Rows": rows}}]


def test_prune_uses_only_frozen_planner_estimates_without_analyze():
    frozen = freeze_pruning(
        _PlannerConnection(),
        _live_source()["cases"][0],
        "articles",
        max_est_selectivity=0.05,
    )

    assert frozen["method"] == "planner_estimated_selectivity_explain_without_analyze"
    assert frozen["leakage_inputs"] == "captured_keywords_and_corpus_statistics_only"
    assert [row["kept"] for row in frozen["decisions"]] == [False, True, True]
    assert all(row["explain_analyze"] is False for row in frozen["decisions"])
    assert frozen["fingerprint"] == fingerprint(
        {key: value for key, value in frozen.items() if key != "fingerprint"}
    )


def test_warmups_are_discarded_and_measured_orders_are_balanced_ab_ba():
    config = FtsConfig(candidate_mode="prune_frequent", repetitions=4)
    specs = {BASELINE_MODE: {"id": "a"}, "prune_frequent": {"id": "b"}}
    calls = []

    def execute(mode, spec):
        calls.append((mode, spec["id"]))
        return {"mode": mode}

    result = run_paired_specs(specs, config, execute)

    assert [(row["warmup"], row["mode"]) for row in result["warmups"]] == [
        (1, BASELINE_MODE),
        (1, "prune_frequent"),
    ]
    assert [row["order"] for row in result["repetitions"]] == paired_schedule(config)
    assert [row["order"] for row in result["repetitions"]] == [
        [BASELINE_MODE, "prune_frequent"],
        ["prune_frequent", BASELINE_MODE],
        [BASELINE_MODE, "prune_frequent"],
        ["prune_frequent", BASELINE_MODE],
    ]
    assert len(calls) == 10
