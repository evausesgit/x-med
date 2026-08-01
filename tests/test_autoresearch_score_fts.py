from dataclasses import asdict

import pytest

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_fts_screen import (
    BASELINE_MODE,
    FtsConfig,
    build_query_spec,
    paired_schedule,
)
from experiments.autoresearch_xmed.score_fts import FtsScoreError, score


BUILDER = {
    "pubmed_query": "hypertension[tiab]",
    "mesh_terms": ["Hypertension"],
    "keywords_en": ["hypertension", "treatment"],
}
CASE_INPUT = {
    "query_id": "q1",
    "query": "traitement de l'hypertension",
    "date_from": None,
    "date_to": None,
    "external": {"query_builder": {"data": BUILDER}},
}


def _audited_spec(mode: str) -> dict:
    spec = build_query_spec(CASE_INPUT, mode, "articles")
    spec["tsquery"] = "'hypertens' | 'treatment'"
    spec["tsquery_fingerprint"] = fingerprint(spec["tsquery"])
    plan = [{"Plan": {"Node Type": "Limit", "Plans": []}}]
    shape = {"Node Type": "Limit", "Plans": []}
    spec["explain"] = {
        "analyze": False,
        "plan": plan,
        "plan_fingerprint": fingerprint(plan),
        "plan_shape": shape,
        "plan_shape_fingerprint": fingerprint(shape),
    }
    return spec


def _run(spec: dict, pmids: list[int], latency_s: float, *, timed_out: bool = False) -> dict:
    metadata = (
        []
        if timed_out
        else [
            {
                "pmid": pmid,
                "title": f"title {pmid}",
                "journal": "J1" if pmid % 2 else "J2",
                "pub_year": 2025 if pmid % 2 else 2026,
                "evidence_level": 1 if pmid % 2 else 2,
            }
            for pmid in pmids
        ]
    )
    actual_pmids = [] if timed_out else pmids
    return {
        "query_spec_fingerprint": spec["query_spec_fingerprint"],
        "search_latency_s": latency_s,
        "metadata_latency_s": 0.01 if not timed_out else 0.0,
        "statement_timeout": "120s",
        "timed_out": timed_out,
        "error": "OperationalError: canceling statement due to statement timeout"
        if timed_out
        else None,
        "pmids": actual_pmids,
        "metadata": metadata,
        "coverage": {"returned": len(actual_pmids), "limit": 50, "metadata": len(metadata)},
    }


def _artifact(
    *,
    candidate_pmids: list[int] | None = None,
    candidate_latencies: dict[int, float] | None = None,
    candidate_timeout_repetition: int | None = None,
) -> dict:
    candidate_pmids = candidate_pmids or [1, 2, 3, 4]
    candidate_latencies = candidate_latencies or {index: 0.8 for index in range(1, 5)}
    config = FtsConfig(candidate_mode="title_boost")
    config_json = asdict(config)
    specs = {
        BASELINE_MODE: _audited_spec(BASELINE_MODE),
        "title_boost": _audited_spec("title_boost"),
    }
    warmups = [
        {
            "warmup": 1,
            "mode": mode,
            "result": _run(specs[mode], [1, 2, 3, 4], 1.0 if mode == BASELINE_MODE else 0.8),
        }
        for mode in (BASELINE_MODE, "title_boost")
    ]
    repetitions = []
    for repetition, order in enumerate(paired_schedule(config), 1):
        runs = {
            BASELINE_MODE: _run(specs[BASELINE_MODE], [1, 2, 3, 4], 1.0),
            "title_boost": _run(
                specs["title_boost"],
                candidate_pmids,
                candidate_latencies[repetition],
                timed_out=repetition == candidate_timeout_repetition,
            ),
        }
        repetitions.append({"repetition": repetition, "order": order, "runs": runs})
    case = {
        "query_id": "q1",
        "query": CASE_INPUT["query"],
        "width": "broad",
        "date_from": None,
        "date_to": None,
        "source_table": "articles",
        "query_builder": BUILDER,
        "query_builder_fingerprint": fingerprint(BUILDER),
        "eligible": True,
        "ineligibility": None,
        "pruning": None,
        "query_specs": specs,
        "warmups": warmups,
        "repetitions": repetitions,
        "error": None,
    }
    return {
        "schema_version": 1,
        "artifact_type": "fts_paired_screen",
        "run_id": "fts-26-test",
        "round": 26,
        "complete": True,
        "expected_query_ids": ["q1"],
        "database": "xmed_autoresearch",
        "corpus_fingerprint": "corpus-fp",
        "machine_fingerprint": "machine-fp",
        "source_machine_fingerprint": "source-machine-fp",
        "source_run_id": "live-1",
        "source_artifact_sha256": "source-sha",
        "runner_sha256": "runner-sha",
        "read_only": True,
        "config": config_json,
        "config_fingerprint": fingerprint(config_json),
        "anchor_plan_sha256": None,
        "calls": {"network": False, "llm": False, "db_write": False},
        "thermal_protocol": {
            "single_connection": True,
            "warmups_discarded": True,
            "balanced_ab_ba": True,
        },
        "cases": [case],
    }


def _proxy(artifact: dict, grades: dict[int, int] | None = None) -> dict:
    grades = grades or {1: 3, 2: 2, 3: 0, 4: 0}
    pool = {"q1": sorted(grades)}
    return {
        "schema_version": 1,
        "proxy": True,
        "frozen_before_scoring": True,
        "source_artifact_fingerprint": fingerprint(artifact),
        "pool_fingerprint": fingerprint(pool),
        "qrels": {"q1": {str(pmid): grade for pmid, grade in grades.items()}},
    }


def test_keep_requires_proxy_noninferiority_and_ten_percent_in_both_orders():
    artifact = _artifact()

    result = score(artifact, _proxy(artifact))

    assert result["verdict"] == "keep_screen"
    assert result["quality_gate"]["passed"] is True
    assert result["robustness_gate"]["passed"] is True
    assert result["efficiency_gate"]["median_paired_gain"] == pytest.approx(0.2)
    assert result["efficiency_gate"]["median_by_order"] == {
        "baseline_first": pytest.approx(0.2),
        "candidate_first": pytest.approx(0.2),
    }
    assert result["production_promotion"] is False
    assert "proxy" in result["disclaimer"]


def test_quality_loss_is_rejected_even_when_candidate_is_faster():
    artifact = _artifact(candidate_pmids=[3, 4, 1, 2])

    result = score(artifact, _proxy(artifact))

    assert result["verdict"] == "reject"
    assert result["quality_gate"]["passed"] is False
    assert any(
        failure["metric"] == "ndcg_at_10" for failure in result["quality_gate"]["global_failures"]
    )


def test_candidate_timeout_is_a_robustness_rejection():
    artifact = _artifact(candidate_timeout_repetition=2)

    result = score(artifact, _proxy(artifact))

    assert result["verdict"] == "reject"
    assert result["robustness_gate"]["passed"] is False
    assert result["robustness_gate"]["timeout_counts"]["title_boost"] == {"q1": 1}


def test_gain_must_hold_separately_in_ab_and_ba_orders():
    artifact = _artifact(candidate_latencies={1: 0.8, 2: 0.95, 3: 0.8, 4: 0.95})

    result = score(artifact, _proxy(artifact))

    assert result["verdict"] == "reject"
    assert result["efficiency_gate"]["median_by_order"]["baseline_first"] == pytest.approx(0.2)
    assert result["efficiency_gate"]["median_by_order"]["candidate_first"] == pytest.approx(0.05)


def test_qrels_must_exactly_cover_the_symmetric_union_pool():
    artifact = _artifact()
    proxy = _proxy(artifact)
    del proxy["qrels"]["q1"]["4"]
    proxy["pool_fingerprint"] = fingerprint({"q1": [1, 2, 3]})

    result = score(artifact, proxy)

    assert result["verdict"] == "ineligible"
    assert result["pool_mismatch"] == {"q1": {"missing": [4], "unexpected": []}}


def test_qrels_bound_to_another_artifact_are_refused():
    artifact = _artifact()
    proxy = _proxy(artifact)
    proxy["source_artifact_fingerprint"] = "wrong"

    with pytest.raises(FtsScoreError, match="artefact FTS exact"):
        score(artifact, proxy)


def test_title_boost_ineligibility_is_preserved_without_guessing_a_join():
    artifact = _artifact()
    case = artifact["cases"][0]
    case.update(
        source_table="article_search",
        eligible=False,
        ineligibility={
            "reason": "title_absent_from_article_search",
            "cost": "join changes access path",
        },
        query_specs={},
        warmups=[],
        repetitions=[],
    )

    result = score(artifact, {})

    assert result["verdict"] == "ineligible"
    assert result["ineligible_cases"]["q1"]["reason"] == "title_absent_from_article_search"


def test_unbalanced_or_modified_repetition_order_is_refused():
    artifact = _artifact()
    artifact["cases"][0]["repetitions"][1]["order"] = [
        BASELINE_MODE,
        "title_boost",
    ]

    with pytest.raises(FtsScoreError, match="AB/BA"):
        score(artifact, _proxy(artifact))
