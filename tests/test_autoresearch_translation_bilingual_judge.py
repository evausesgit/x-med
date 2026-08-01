import json
import re

import pytest

from app.services.codex_cli import CodexUsage
from experiments.autoresearch_xmed.run_translation_bilingual_judge import (
    BilingualJudgeConfig,
    BilingualJudgeError,
    JUDGE_TIMEOUT_S,
    _SCHEMA,
    build_prompt,
    load_blind_pool,
    run_judge,
    run_repetition,
)


def _item(pmid):
    return {
        "item_id": f"item-{pmid}",
        "query_id": "q01",
        "pmid": pmid,
        "source": {"title": f"Title {pmid}", "abstract": f"Abstract {pmid}"},
        "options": {
            "A": {"title_fr": f"Titre A {pmid}", "abstract_fr": f"Résumé A {pmid}"},
            "B": {"title_fr": f"Titre B {pmid}", "abstract_fr": f"Résumé B {pmid}"},
        },
    }


def _write(path, items):
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def _identities(prompt):
    return [
        (item_id, int(pmid))
        for item_id, pmid in re.findall(r"^- item_id (\S+) · PMID (\d+)$", prompt, re.MULTILINE)
    ]


def _response(identities, *, candidate_score=4):
    return {
        "evaluations": [
            {
                "item_id": item_id,
                "pmid": pmid,
                "options": [
                    {
                        "label": label,
                        "clinical_fidelity": candidate_score if label == "B" else 4,
                        "terminology": candidate_score if label == "B" else 4,
                        "readability": candidate_score if label == "B" else 4,
                        "critical_errors": [],
                        "omissions": [],
                        "hallucinations": [],
                        "rationale": "Comparaison fidèle au texte source.",
                    }
                    for label in ("A", "B")
                ],
            }
            for item_id, pmid in identities
        ]
    }


def test_prompt_is_blind_bilingual_and_exposes_explicit_scales():
    prompt = build_prompt([_item(1)], repetition=1)
    assert "anglais-français" in prompt
    assert "clinical_fidelity" in prompt
    assert "1=contre-sens" in prompt
    assert "critical_errors" in prompt
    assert "Option A" in prompt and "Option B" in prompt
    assert "baseline" not in prompt.lower()
    assert "candidate" not in prompt.lower()


def test_judge_uses_schema_and_repeats_with_strict_bijection():
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        calls.append((schema, timeout, kwargs))
        return _response(_identities(prompt)), CodexUsage(input_tokens=5, output_tokens=2)

    config = BilingualJudgeConfig(batch_size=2, repetitions=2)
    result = run_repetition([_item(1), _item(2)], config, runner, 1)

    assert calls == [
        (
            _SCHEMA,
            JUDGE_TIMEOUT_S,
            {"model": config.model, "reasoning": config.reasoning},
        )
    ]
    assert [value["item_id"] for value in result["evaluations"]] == ["item-1", "item-2"]


@pytest.mark.parametrize("defect", ["missing_item", "extra_item", "missing_label", "bad_score"])
def test_judge_refuses_invalid_response_bijections_and_scores(defect):
    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        response = _response(_identities(prompt))
        if defect == "missing_item":
            response["evaluations"].pop()
        elif defect == "extra_item":
            response["evaluations"].extend(_response([("extra", 999)])["evaluations"])
        elif defect == "missing_label":
            response["evaluations"][0]["options"].pop()
        else:
            response["evaluations"][0]["options"][0]["terminology"] = 0
        return response, CodexUsage()

    with pytest.raises(BilingualJudgeError):
        run_repetition([_item(1), _item(2)], BilingualJudgeConfig(repetitions=2), runner, 1)


def test_blind_pool_rejects_system_identity_leak(tmp_path):
    path = tmp_path / "blind.jsonl"
    item = _item(1)
    item["baseline"] = "A"
    _write(path, [item])
    with pytest.raises(BilingualJudgeError, match="champs aveugles"):
        load_blind_pool(path)


def test_run_judge_is_complete_repeated_fingerprinted_and_atomic(tmp_path):
    blind = tmp_path / "blind.jsonl"
    out = tmp_path / "judge.json"
    _write(blind, [_item(1), _item(2)])
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        calls.append(prompt)
        return _response(_identities(prompt)), CodexUsage(input_tokens=3, output_tokens=1)

    result = run_judge(blind, out, BilingualJudgeConfig(repetitions=2), runner)

    assert json.loads(out.read_text()) == result
    assert result["complete"] is True
    assert result["proxy_only"] is True
    assert len(result["repetitions"]) == 2
    assert len(calls) == 2
    assert len(result["source_blind_pool_sha256"]) == 64
    assert len(result["config_fingerprint"]) == 64
    assert len(result["judge_contract_fingerprint"]) == 64
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("values", [{"batch_size": 0}, {"repetitions": 1}, {"repetitions": 4}])
def test_judge_config_requires_two_or_three_repetitions(values):
    with pytest.raises(BilingualJudgeError):
        BilingualJudgeConfig(**values)
