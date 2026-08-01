from copy import deepcopy
import json

import pytest

from experiments.autoresearch_xmed.score import (
    InvalidArtifact,
    _diversity_margin,
    _diversity_tail,
    _diversity_worst_quartile_floor,
    _metric_failures_by_stratum,
    _qrels_payload,
    _quality_margin,
    _quality_tail,
    compare,
    load_json,
)


def _run(latency=10.0):
    return {
        "schema_version": 1,
        "cases": [
            {
                "query_id": "q1",
                "latency_s": latency,
                "tokens": {"total": 100},
                "judge_input_sha256": "input",
                "judge_prompt_sha256": "judge",
                "translate_prompt_sha256": "translate",
                "results": [
                    {
                        "pmid": 1,
                        "score": 3,
                        "relevance_pct": 95,
                        "reason": "Répond directement.",
                        "source": "both",
                        "title": "A",
                        "abstract": "B",
                        "title_fr": "A fr",
                        "abstract_fr": "B fr",
                        "journal": "J1",
                        "pub_year": 2026,
                    },
                    {
                        "pmid": 2,
                        "score": 2,
                        "relevance_pct": 70,
                        "reason": "Complète la réponse.",
                        "source": "local",
                        "title": "C",
                        "abstract": "D",
                        "title_fr": "C fr",
                        "abstract_fr": "D fr",
                        "journal": "J2",
                        "pub_year": 2024,
                    },
                ],
            }
        ],
    }


def test_fidelity_gate_keeps_byte_identical_faster_candidate():
    result = compare(_run(10), _run(8), "fidelity")
    assert result["verdict"] == "keep"
    assert result["gates"][0]["passed"] is True


def test_fidelity_gate_rejects_changed_result_even_if_faster():
    candidate = _run(1)
    candidate["cases"][0]["results"][0]["reason"] = "Texte différent."
    result = compare(_run(10), candidate, "fidelity")
    assert result["verdict"] == "reject"
    assert result["gates"][0]["failures"] == ["q1"]


def test_fidelity_gate_rejects_efficiency_gain_below_ten_percent():
    result = compare(_run(10), _run(9.5), "fidelity")
    assert result["gates"][0]["passed"] is True
    assert result["verdict"] == "reject"


def test_clinical_gate_is_ineligible_without_qrels():
    assert compare(_run(10), _run(8), "clinical")["verdict"] == "ineligible"


def test_qrels_artifact_wrapper_is_unwrapped_without_losing_proxy_identity():
    qrels = {"q1": {"1": 3}}
    assert _qrels_payload({"schema_version": 1, "proxy": True, "qrels": qrels}) == (qrels, True)
    assert _qrels_payload(qrels) == (qrels, None)
    with pytest.raises(InvalidArtifact, match="proxy"):
        _qrels_payload({"schema_version": 1, "qrels": qrels})


def test_auto_gate_accepts_exact_replay_without_qrels():
    assert compare(_run(10), _run(8), "auto")["verdict"] == "keep"


def test_auto_gate_allows_different_llm_output_when_quality_is_noninferior():
    baseline = _run(10)
    candidate = deepcopy(baseline)
    candidate["cases"][0]["latency_s"] = 8
    candidate["cases"][0]["results"][0]["reason"] = "Formulation LLM différente."
    qrels = {"q1": {"1": 3, "2": 2}}
    result = compare(baseline, candidate, "auto", qrels)
    assert result["verdict"] == "keep"
    assert result["gates"][0]["name"] == "relative_quality_noninferiority"


def test_auto_gate_is_ineligible_for_changed_output_without_evidence():
    candidate = _run(8)
    candidate["cases"][0]["results"][0]["reason"] = "Formulation LLM différente."
    assert compare(_run(10), candidate, "auto")["verdict"] == "ineligible"


def test_live_and_replay_latencies_cannot_produce_a_keep():
    baseline = _run(10)
    baseline["run_kind"] = "live"
    candidate = _run(1)
    candidate["run_kind"] = "replay"
    result = compare(baseline, candidate, "fidelity")
    assert result["verdict"] == "ineligible"
    gate = next(
        item for item in result["gates"] if item["name"] == "performance_measurement_comparability"
    )
    assert gate["passed"] is False


def test_real_artifact_must_be_complete(tmp_path):
    run = _run(10)
    run.update(
        {
            "run_kind": "replay",
            "complete": False,
            "expected_query_ids": ["q1"],
            "database": "xmed_autoresearch",
            "corpus_scope": "full",
            "corpus_fingerprint": "corpus",
            "machine_fingerprint": "machine",
        }
    )
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(run))
    with pytest.raises(InvalidArtifact, match="incomplet"):
        load_json(path)


def test_changed_translation_requires_independent_bilingual_scores():
    baseline = _run(10)
    candidate = _run(8)
    candidate["cases"][0]["results"][0]["abstract_fr"] = "traduction différente"
    qrels = {"q1": {"1": 3, "2": 2}}
    assert compare(baseline, candidate, "auto", qrels)["verdict"] == "ineligible"

    base_score = {
        "fidelity": 3.5,
        "terminology": 3.5,
        "readability": 3.5,
        "critical_errors": 0,
    }
    better_score = {
        "fidelity": 4.0,
        "terminology": 4.0,
        "readability": 4.0,
        "critical_errors": 0,
    }
    scores = {
        "baseline": {"q1": {"1": base_score, "2": base_score}},
        "candidate": {"q1": {"1": better_score, "2": base_score}},
    }
    result = compare(baseline, candidate, "auto", qrels, scores)
    assert result["verdict"] == "keep"
    gate = next(item for item in result["gates"] if item["name"].startswith("translation"))
    assert gate["passed"] is True

    scores["candidate"]["q1"]["1"] = {**better_score, "critical_errors": 1}
    result = compare(baseline, candidate, "auto", qrels, scores)
    assert result["verdict"] == "reject"
    gate = next(item for item in result["gates"] if item["name"].startswith("translation"))
    assert gate["critical_error_failures"] == {"q1": ["1"]}


def test_same_v2_translation_contract_accepts_stochastic_wording():
    baseline = _run(10)
    candidate = _run(8)
    candidate["cases"][0]["results"][0]["abstract_fr"] = "Formulation différente."
    for run in (baseline, candidate):
        run["protocol_fingerprint"] = "protocol-v2"
        run["variant_config"] = {"reuse_hydrated_translation_input": False}

    result = compare(baseline, candidate, "auto", {"q1": {"1": 3, "2": 2}})

    assert result["verdict"] == "keep"
    gate = next(item for item in result["gates"] if item["name"].startswith("translation"))
    assert gate["name"] == "translation_same_contract"
    assert gate["passed"] is True
    assert gate["mode"] == "same_v2_contract_stochastic_outputs"


def test_same_translation_contract_still_rejects_coverage_regression():
    baseline = _run(10)
    candidate = _run(8)
    candidate["cases"][0]["results"][0]["abstract_fr"] = ""
    for run in (baseline, candidate):
        run["protocol_fingerprint"] = "protocol-v2"
        run["variant_config"] = {"reuse_hydrated_translation_input": False}

    result = compare(baseline, candidate, "auto", {"q1": {"1": 3, "2": 2}})

    assert result["verdict"] == "reject"
    gate = next(item for item in result["gates"] if item["name"].startswith("translation"))
    assert gate["coverage_failures"] == {"q1": 1}


def test_changed_translation_behavior_still_requires_bilingual_evidence():
    baseline = _run(10)
    candidate = _run(8)
    candidate["cases"][0]["results"][0]["abstract_fr"] = "Formulation différente."
    baseline["protocol_fingerprint"] = candidate["protocol_fingerprint"] = "protocol-v2"
    baseline["variant_config"] = {"reuse_hydrated_translation_input": False}
    candidate["variant_config"] = {"reuse_hydrated_translation_input": True}

    result = compare(baseline, candidate, "auto", {"q1": {"1": 3, "2": 2}})

    assert result["verdict"] == "ineligible"
    gate = next(item for item in result["gates"] if item["name"].startswith("translation"))
    assert gate["name"] == "translation_quality_evidence"


def test_clinical_gate_does_not_treat_unlabelled_candidates_as_irrelevant():
    candidate = _run(8)
    candidate["cases"][0]["results"].append(
        {"pmid": 3, "source": "pubmed", "journal": "J3", "pub_year": 2025}
    )
    qrels = {"q1": {"1": 3, "2": 2}}
    result = compare(_run(10), candidate, "clinical", qrels)
    assert result["verdict"] == "ineligible"
    assert result["gates"][0]["gaps"]["q1"]["missing_pmids"] == ["3"]


def test_clinical_gate_rejects_aggregate_quality_loss():
    baseline = _run(10)
    candidate = deepcopy(baseline)
    candidate["cases"][0]["latency_s"] = 1
    candidate["cases"][0]["results"].reverse()
    qrels = {"q1": {"1": 3, "2": 0}}
    result = compare(baseline, candidate, "clinical", qrels)
    assert result["verdict"] == "reject"
    quality_gate = next(g for g in result["gates"] if g["name"].startswith("relative_quality"))
    assert "ndcg@10" in quality_gate["aggregate_failures"]


def test_clinical_gate_allows_bounded_per_query_tradeoff():
    baseline = _run(10)
    first = baseline["cases"][0]
    first["width"] = "narrow"
    for pmid in range(3, 11):
        first["results"].append(
            {
                "pmid": pmid,
                "score": 2,
                "relevance_pct": 60,
                "reason": "Pertinent.",
                "source": "local",
                "title": f"T{pmid}",
                "abstract": f"A{pmid}",
                "title_fr": f"TF{pmid}",
                "abstract_fr": f"AF{pmid}",
                "journal": f"J{pmid}",
                "pub_year": 2026 - (pmid % 3),
            }
        )
    second = deepcopy(first)
    second["query_id"] = "q2"
    second["results"][-2:] = reversed(second["results"][-2:])
    baseline["cases"].append(second)

    candidate = deepcopy(baseline)
    candidate["cases"][0]["results"][-2:] = reversed(candidate["cases"][0]["results"][-2:])
    candidate["cases"][1]["results"][-2:] = reversed(candidate["cases"][1]["results"][-2:])
    for case in candidate["cases"]:
        case["latency_s"] = 8
        case["judge_input_sha256"] = "changed"

    labels = {str(pmid): 3 for pmid in range(1, 11)}
    labels["10"] = 2
    qrels = {"q1": labels, "q2": labels}
    result = compare(baseline, candidate, "clinical", qrels)
    assert result["verdict"] == "keep"
    gate = next(g for g in result["gates"] if g["name"] == "relative_quality_noninferiority")
    assert gate["stratum_failures"] == {}
    assert -0.05 <= gate["worst_quartile_ndcg_mean"] < 0
    assert gate["statistically_supported"] is True
    assert gate["per_query_deltas_diagnostic"]["q1"]["ndcg@10"] < 0
    assert gate["per_query_deltas_diagnostic"]["q2"]["ndcg@10"] > 0

    excessive = deepcopy(candidate)
    excessive["cases"][0]["results"] = deepcopy(baseline["cases"][0]["results"])
    excessive["cases"][0]["results"][0], excessive["cases"][0]["results"][-1] = (
        excessive["cases"][0]["results"][-1],
        excessive["cases"][0]["results"][0],
    )
    excessive_result = compare(baseline, excessive, "clinical", qrels)
    assert excessive_result["verdict"] == "reject"
    excessive_gate = next(
        gate
        for gate in excessive_result["gates"]
        if gate["name"] == "relative_quality_noninferiority"
    )
    assert excessive_gate["worst_quartile_ndcg_mean"] < -0.05


def test_live_quality_margin_passes_at_boundary_and_fails_beyond_it():
    base_cases = {"q1": {"width": "narrow", "value": 0.50}}

    def metric(case, _qid):
        return {"ndcg@10": case["value"]}

    at_boundary = {"q1": {"width": "narrow", "value": 0.48}}
    failures, deltas, margins = _metric_failures_by_stratum(
        base_cases,
        at_boundary,
        ("ndcg@10",),
        metric,
        _quality_margin,
    )
    assert failures == {}
    assert deltas["narrow"]["ndcg@10"] == pytest.approx(-0.02)
    assert margins["narrow"]["ndcg@10"] == 0.02

    beyond = {"q1": {"width": "narrow", "value": 0.479}}
    failures, _, _ = _metric_failures_by_stratum(
        base_cases,
        beyond,
        ("ndcg@10",),
        metric,
        _quality_margin,
    )
    assert failures == {"narrow": ["ndcg@10"]}


def test_live_tail_floors_are_inclusive_and_reject_excess():
    assert _quality_tail([-0.05, 0.1, 0.1, 0.1])["passed"] is True
    excessive_tail = _quality_tail([-0.050001, 0.1, 0.1, 0.1])
    assert excessive_tail["worst_quartile_passed"] is False

    assert _quality_tail([-0.02] * 4)["passed"] is True
    excessive_uncertainty = _quality_tail([-0.020001] * 4)
    assert excessive_uncertainty["bootstrap_passed"] is False


def test_live_diversity_margins_match_metric_scales():
    assert _diversity_margin("journal_entropy@10", 2.0) == 0.05
    assert _diversity_margin("journal_entropy@10", 3.0) == pytest.approx(0.06)
    assert _diversity_margin("journal_coverage@10", 0.8) == 0.02
    assert _diversity_worst_quartile_floor("journal_entropy@10") == -0.10
    assert _diversity_worst_quartile_floor("journal_coverage@10") == -0.10


def test_live_diversity_boundaries_are_inclusive_and_reject_excess():
    keys = (
        "journal_entropy@10",
        "source_entropy@10",
        "year_entropy@10",
        "journal_coverage@10",
        "source_coverage@10",
        "year_coverage@10",
    )
    at_boundary = {
        "q1": {
            **{key: -0.10 for key in keys if "entropy" in key},
            **{key: -0.10 for key in keys if "coverage" in key},
        }
    }
    assert _diversity_tail(at_boundary)["passed"] is True

    beyond_entropy = deepcopy(at_boundary)
    beyond_entropy["q1"]["journal_entropy@10"] = -0.100001
    assert _diversity_tail(beyond_entropy)["failures"] == ["journal_entropy@10"]

    beyond_coverage = deepcopy(at_boundary)
    beyond_coverage["q1"]["journal_coverage@10"] = -0.100001
    assert _diversity_tail(beyond_coverage)["failures"] == ["journal_coverage@10"]
