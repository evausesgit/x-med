import json
from dataclasses import asdict

import pytest

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_judge_screen import JudgeConfig
from experiments.autoresearch_xmed.score_judge import (
    QUALITY_KEYS,
    JudgeScoreError,
    _quality_noninferiority,
    _worst_quartile_ndcg,
    compare,
)


QUERIES = (
    ("q1", "broad", "question clinique large", (101, 102, 103, 104)),
    ("q2", "narrow", "question clinique étroite", (201, 202, 203, 204)),
)


def _usage(total_tokens: int) -> dict[str, int]:
    return {
        "input_tokens": total_tokens - 20,
        "cached_input_tokens": 0,
        "output_tokens": 20,
        "reasoning_output_tokens": 0,
        "total_tokens": total_tokens,
    }


def _repeated_usage(total_tokens: int, repetitions: int) -> dict[str, int]:
    usage = _usage(total_tokens)
    return {key: value * repetitions for key, value in usage.items()}


def _artifact(
    *,
    scores: dict[str, list[int]] | None = None,
    latency_s: float = 1.0,
    total_tokens: int = 100,
    config: JudgeConfig | None = None,
) -> dict:
    config = config or JudgeConfig()
    config_json = asdict(config)
    scores = scores or {query_id: [3, 2, 0, 0] for query_id, *_ in QUERIES}
    cases = []
    for query_id, _width, query, pmids in QUERIES:
        repetitions = []
        for repetition_number in range(1, config.repetitions + 1):
            usage = _usage(total_tokens)
            judgements = [
                {
                    "pmid": pmid,
                    "score": score,
                    "relevance_pct": min(100, score * 25 + 10 - pool_index),
                    "reason": f"jugement candidat {query_id} {pmid}",
                }
                for pool_index, (pmid, score) in enumerate(
                    zip(pmids, scores[query_id], strict=True)
                )
            ]
            repetitions.append(
                {
                    "repetition": repetition_number,
                    "latency_s": latency_s,
                    "tokens": usage,
                    "prompt_hashes": ["a" * 64],
                    "calls": [
                        {
                            "batch_index": 1,
                            "shard_index": 1,
                            "pmids": list(pmids),
                            "latency_s": latency_s,
                            "prompt_sha256": "a" * 64,
                            "usage": usage,
                        }
                    ],
                    "judgements": judgements,
                }
            )
        cases.append(
            {
                "query_id": query_id,
                "query": query,
                "item_ids": [f"item-{query_id}-{pmid}" for pmid in pmids],
                "pmids": list(pmids),
                "config": config_json,
                "repetitions": repetitions,
                "tokens": _repeated_usage(total_tokens, config.repetitions),
                "error": None,
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "judge_screen",
        "complete": True,
        "expected_query_ids": [query_id for query_id, *_ in QUERIES],
        "source_pool_sha256": "pool-sha",
        "runner_sha256": "runner-sha",
        "machine_fingerprint": "machine-sha",
        "config": config_json,
        "config_fingerprint": fingerprint(config_json),
        "exact_production_prompt": config.exact_production_prompt,
        "calls": {"database": False, "retrieval": False, "translate": False},
        "cases": cases,
    }


def _proxy() -> dict:
    return {
        "schema_version": 1,
        "proxy": True,
        "qrels": {
            query_id: {
                str(pmids[0]): 3,
                str(pmids[1]): 2,
                str(pmids[2]): 0,
                str(pmids[3]): 0,
            }
            for query_id, _width, _query, pmids in QUERIES
        },
    }


@pytest.fixture
def queries_path(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text(
        "".join(
            json.dumps({"id": query_id, "width": width, "query": query}) + "\n"
            for query_id, width, query, _pmids in QUERIES
        ),
        encoding="utf-8",
    )
    return path


def test_different_relevant_judgements_are_accepted_for_screening(queries_path):
    baseline = _artifact()
    candidate = _artifact(
        scores={query_id: [3, 3, 0, 0] for query_id, *_ in QUERIES},
        latency_s=0.8,
    )

    result = compare(baseline, candidate, _proxy(), queries_path)

    assert result["verdict"] == "keep_screen"
    assert result["quality_gate"]["passed"] is True
    assert result["quality_gate"]["global_margins"] == {key: 0.02 for key in QUALITY_KEYS}
    assert result["quality_gate"]["width_margins"]["broad"] == {key: 0.02 for key in QUALITY_KEYS}
    assert result["efficiency_gate"]["passed_via"] == "latency"
    assert result["production_promotion"] is False
    assert "proxy" in result["disclaimer"]


def test_quality_decrease_is_rejected_even_with_a_latency_gain(queries_path):
    baseline = _artifact()
    candidate = _artifact(
        scores={"q1": [0, 0, 3, 2], "q2": [3, 2, 0, 0]},
        latency_s=0.5,
    )

    result = compare(baseline, candidate, _proxy(), queries_path)

    assert result["verdict"] == "reject"
    assert result["quality_gate"]["passed"] is False
    assert "ndcg_at_10" in result["quality_gate"]["global_failures"]
    assert "broad" in result["quality_gate"]["width_failures"]
    assert result["quality_gate"]["worst_quartile"]["passed"] is False
    assert result["quality_gate"]["worst_quartile"]["floor"] == -0.05


def test_quality_margin_is_inclusive_and_rejects_just_beyond_boundary():
    baseline = {key: 0.50 for key in QUALITY_KEYS}
    at_boundary = {key: 0.48 for key in QUALITY_KEYS}

    failures, margins, deltas = _quality_noninferiority(baseline, at_boundary)

    assert failures == []
    assert margins == {key: 0.02 for key in QUALITY_KEYS}
    assert all(delta == pytest.approx(-0.02) for delta in deltas.values())

    beyond = dict(at_boundary)
    beyond["recall_pool"] = 0.479
    assert _quality_noninferiority(baseline, beyond)[0] == ["recall_pool"]


def test_worst_quartile_floor_is_inclusive_and_rejects_just_beyond_boundary():
    at_boundary = _worst_quartile_ndcg({"q1": -0.05, "q2": 0.10, "q3": 0.10, "q4": 0.10})
    assert at_boundary["passed"] is True
    assert at_boundary["floor"] == -0.05

    beyond = _worst_quartile_ndcg({"q1": -0.050001, "q2": 0.10, "q3": 0.10, "q4": 0.10})
    assert beyond["passed"] is False


def test_latency_gain_rejects_more_than_five_percent_token_regression(queries_path):
    result = compare(
        _artifact(),
        _artifact(latency_s=0.9, total_tokens=106),
        _proxy(),
        queries_path,
    )

    assert result["verdict"] == "reject"
    assert result["efficiency_gate"]["latency_gain"] == pytest.approx(0.1)
    assert result["efficiency_gate"]["token_gain"] == pytest.approx(-0.06)


def test_token_gain_accepts_less_than_five_percent_latency_regression(queries_path):
    result = compare(
        _artifact(),
        _artifact(latency_s=1.04, total_tokens=80),
        _proxy(),
        queries_path,
    )

    assert result["verdict"] == "keep_screen"
    assert result["efficiency_gate"]["passed_via"] == "tokens"
    assert result["efficiency_gate"]["token_gain"] == pytest.approx(0.2)


def test_missing_pool_qrel_makes_comparison_ineligible(queries_path):
    proxy = _proxy()
    del proxy["qrels"]["q1"]["101"]

    result = compare(_artifact(), _artifact(latency_s=0.8), proxy, queries_path)

    assert result["verdict"] == "ineligible"
    assert result["qrel_gaps"] == {"q1": [101]}


def test_identity_mismatch_makes_comparison_ineligible(queries_path):
    candidate = _artifact(latency_s=0.8)
    candidate["machine_fingerprint"] = "another-machine"

    result = compare(_artifact(), candidate, _proxy(), queries_path)

    assert result["verdict"] == "ineligible"
    assert "machine_fingerprint" in result["identity_mismatches"]


def test_missing_repetition_and_bad_config_fingerprint_are_refused(queries_path):
    missing = _artifact(config=JudgeConfig(repetitions=2))
    missing["cases"][0]["repetitions"].pop()
    with pytest.raises(JudgeScoreError, match="répétitions incomplètes"):
        compare(missing, _artifact(), _proxy(), queries_path)

    bad_fingerprint = _artifact()
    bad_fingerprint["config_fingerprint"] = "wrong"
    with pytest.raises(JudgeScoreError, match="config_fingerprint"):
        compare(bad_fingerprint, _artifact(), _proxy(), queries_path)


def test_different_repetition_counts_are_ineligible(queries_path):
    result = compare(
        _artifact(),
        _artifact(config=JudgeConfig(repetitions=2), latency_s=0.8),
        _proxy(),
        queries_path,
    )

    assert result["verdict"] == "ineligible"
    assert "config.repetitions" in result["identity_mismatches"]
