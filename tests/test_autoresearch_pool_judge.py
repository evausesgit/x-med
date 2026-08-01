from app.services.codex_cli import CodexUsage
import pytest

from experiments.autoresearch_xmed.judge_annotation_pool import evaluate, merge_proxy_qrels


def test_pool_judge_aggregates_three_blind_repetitions():
    calls = []

    def runner(prompt, schema, **kwargs):
        del prompt, schema, kwargs
        grade = (1, 3, 2)[len(calls)]
        calls.append(grade)
        return {
            "judgements": [{"item_id": "item", "grade": grade, "confidence": 80, "reason": "ok"}]
        }, CodexUsage(input_tokens=10, output_tokens=2)

    result = evaluate(
        [
            {
                "item_id": "item",
                "query_id": "q1",
                "query": "question",
                "pmid": 1,
                "title": "title",
                "abstract": "abstract",
            }
        ],
        repetitions=3,
        batch_size=20,
        model="evaluator",
        reasoning="high",
        runner=runner,
    )
    assert result["qrels"] == {"q1": {"1": 2}}
    assert result["total_tokens"] == 36
    assert result["proxy"] is True


def test_merge_proxy_qrels_adds_only_compatible_delta():
    common = {
        "schema_version": 1,
        "proxy": True,
        "model": "model",
        "reasoning": "high",
        "repetitions": 3,
    }
    existing = {
        **common,
        "total_tokens": 10,
        "qrels": {"q1": {"1": 3}},
        "raw": [{"item_id": "one"}],
    }
    delta = {
        **common,
        "total_tokens": 20,
        "qrels": {"q1": {"2": 2}, "q2": {"3": 1}},
        "raw": [{"item_id": "two"}],
    }

    merged = merge_proxy_qrels(existing, delta)

    assert merged["total_tokens"] == 30
    assert merged["qrels"] == {"q1": {"1": 3, "2": 2}, "q2": {"3": 1}}
    assert [row["item_id"] for row in merged["raw"]] == ["one", "two"]

    conflicting = {**delta, "qrels": {"q1": {"1": 0}}}
    with pytest.raises(RuntimeError, match="conflictuels"):
        merge_proxy_qrels(existing, conflicting)
