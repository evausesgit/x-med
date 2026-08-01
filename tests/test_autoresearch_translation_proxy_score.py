from copy import deepcopy

import pytest

from experiments.autoresearch_xmed.score_translation_proxy import (
    CANDIDATE_ABSOLUTE_FLOOR,
    GLOBAL_NONINFERIORITY_MARGIN,
    STRATUM_NONINFERIORITY_MARGIN,
    TranslationProxyScoreError,
    WORST_QUARTILE_NONINFERIORITY_MARGIN,
    _below_margin,
    score,
)


def _key(count=4):
    return {
        "artifact_type": "translation_comparison_private_key",
        "blind_pool_sha256": "blind",
        "source_pool_sha256": "source",
        "sources": {
            "pool": {"sha256": "source"},
            "baseline": {
                "sha256": "baseline",
                "config_fingerprint": "baseline-config",
                "runner_sha256": "baseline-runner",
                "repetition": 1,
            },
            "candidate": {
                "sha256": "candidate",
                "config_fingerprint": "candidate-config",
                "runner_sha256": "candidate-runner",
                "repetition": 1,
            },
        },
        "items": {
            f"item-{index}": {
                "pmid": index,
                "labels": {"baseline": "A", "candidate": "B"},
                "stratum": {
                    "length": "short" if index <= 2 else "long",
                    "risk": "plain" if index % 2 else "technical",
                    "combined": (
                        "short:plain"
                        if index == 1
                        else "short:technical"
                        if index == 2
                        else "long:plain"
                        if index == 3
                        else "long:technical"
                    ),
                },
            }
            for index in range(1, count + 1)
        },
    }


def _option(label, score_value=4, critical=None):
    return {
        "label": label,
        "clinical_fidelity": score_value,
        "terminology": score_value,
        "readability": score_value,
        "critical_errors": critical or [],
        "omissions": [],
        "hallucinations": [],
        "rationale": "Rationale",
    }


def _judgement(key, candidate_scores=None, critical_item=None):
    candidate_scores = candidate_scores or {}
    evaluations = []
    for item_id, private in key["items"].items():
        evaluations.append(
            {
                "item_id": item_id,
                "pmid": private["pmid"],
                "options": [
                    _option("A", 4),
                    _option(
                        "B",
                        candidate_scores.get(item_id, 4),
                        ["critical"] if item_id == critical_item else [],
                    ),
                ],
            }
        )
    return {
        "artifact_type": "translation_bilingual_judgement",
        "complete": True,
        "proxy_only": True,
        "expected_item_ids": list(key["items"]),
        "source_blind_pool_sha256": key["blind_pool_sha256"],
        "config_fingerprint": "config",
        "judge_contract_fingerprint": "contract",
        "runner_sha256": "runner",
        "machine_fingerprint": "machine",
        "repetitions": [
            {"repetition": 1, "evaluations": deepcopy(evaluations)},
            {"repetition": 2, "evaluations": deepcopy(evaluations)},
        ],
    }


def test_proxy_keeps_only_strict_noninferiority_and_is_explicitly_not_clinical_truth():
    key = _key()
    result = score(key, _judgement(key))

    assert result["verdict"] == "keep_proxy"
    assert result["proxy_only"] is True
    assert result["clinical_truth"] is False
    assert all(gate["passed"] for gate in result["gates"].values())
    assert result["predeclared_policy"] == {
        "score_scale": [1, 5],
        "global_noninferiority_margin_points": 0.15,
        "stratum_noninferiority_margin_points": 0.25,
        "worst_quartile_noninferiority_margin_points": 0.5,
        "candidate_absolute_floor": 3.0,
        "critical_error_margin": 0,
    }


def test_any_additional_critical_error_rejects_proxy():
    key = _key()
    result = score(key, _judgement(key, critical_item="item-2"))

    assert result["verdict"] == "reject_proxy"
    gate = result["gates"]["critical_errors"]
    assert gate["passed"] is False
    assert gate["per_item_failures"]["item-2"] == {"baseline": 0, "candidate": 2}


def test_worst_quartile_blocks_average_compensation():
    key = _key()
    judgement = _judgement(
        key,
        candidate_scores={"item-1": 3, "item-2": 5, "item-3": 4, "item-4": 4},
    )
    result = score(key, judgement)

    assert result["gates"]["global_noninferiority"]["passed"] is True
    assert result["gates"]["worst_quartile_noninferiority"]["passed"] is False
    assert result["verdict"] == "reject_proxy"


def test_stratum_loss_rejects_even_if_global_is_noninferior():
    key = _key()
    judgement = _judgement(
        key,
        candidate_scores={"item-1": 3, "item-2": 3, "item-3": 5, "item-4": 5},
    )
    result = score(key, judgement)

    assert result["gates"]["global_noninferiority"]["passed"] is True
    assert result["gates"]["stratum_noninferiority"]["passed"] is False
    assert "length=short" in result["gates"]["stratum_noninferiority"]["failures"]


def test_scorer_refuses_wrong_blind_pool_or_incomplete_repetitions():
    key = _key()
    judgement = _judgement(key)
    judgement["source_blind_pool_sha256"] = "other"
    with pytest.raises(TranslationProxyScoreError, match="différent"):
        score(key, judgement)

    judgement = _judgement(key)
    judgement["repetitions"].pop()
    with pytest.raises(TranslationProxyScoreError, match="répétitions"):
        score(key, judgement)


@pytest.mark.parametrize(
    ("margin", "boundary", "beyond"),
    [
        (GLOBAL_NONINFERIORITY_MARGIN, -0.15, -0.150001),
        (STRATUM_NONINFERIORITY_MARGIN, -0.25, -0.250001),
        (WORST_QUARTILE_NONINFERIORITY_MARGIN, -0.50, -0.500001),
    ],
)
def test_predeclared_margin_boundaries_are_inclusive_and_excess_is_rejected(
    margin, boundary, beyond
):
    assert _below_margin(boundary, margin) is False
    assert _below_margin(beyond, margin) is True


def test_candidate_absolute_floor_rejects_low_scores_even_without_relative_loss():
    key = _key()
    judgement = _judgement(key, candidate_scores={item_id: 2 for item_id in key["items"]})
    for repetition in judgement["repetitions"]:
        for evaluation in repetition["evaluations"]:
            evaluation["options"][0]["clinical_fidelity"] = 2
            evaluation["options"][0]["terminology"] = 2
            evaluation["options"][0]["readability"] = 2
    result = score(key, judgement)

    assert CANDIDATE_ABSOLUTE_FLOOR == 3.0
    assert result["gates"]["global_noninferiority"]["passed"] is True
    assert result["gates"]["candidate_absolute_floor"]["passed"] is False
    assert result["verdict"] == "reject_proxy"
