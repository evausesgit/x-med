import json
from pathlib import Path

from app.services.codex_cli import CodexUsage
from experiments.autoresearch_xmed.score_warm_query_cache import _summary
from experiments.autoresearch_xmed.warm_query_cache import ExactQueryBuilderCache


def test_exact_adapter_bills_only_the_miss(tmp_path: Path):
    calls = []

    def builder(question: str, timeout: int = 180):
        calls.append((question, timeout))
        return {"pubmed_query": "A", "mesh_terms": [], "keywords_en": ["A"]}, CodexUsage(
            input_tokens=10, output_tokens=2
        )

    cached = ExactQueryBuilderCache(tmp_path, builder)
    cold_data, cold_usage = cached("question", timeout=12)
    assert cached.contains("question") is True
    assert cached.contains("question différente") is False
    warm_data, warm_usage = cached("question", timeout=99)

    assert calls == [("question", 12)]
    assert warm_data == cold_data
    assert cold_usage.total_tokens == 12
    assert warm_usage.total_tokens == 0
    assert [event.hit for event in cached.events] == [False, True]
    assert [event.billed_tokens for event in cached.events] == [12, 0]


def test_counterfactual_removes_only_query_phase_and_tokens():
    run = {
        "cases": [
            {
                "query_id": "q01",
                "error": None,
                "usable_latency_s": 100.0,
                "complete_latency_s": 200.0,
                "tokens": {"query": 20, "total": 100},
                "phases": [
                    {"phase": "codex", "elapsed_s": 1.0},
                    {"phase": "codex_done", "elapsed_s": 21.0},
                ],
            }
        ]
    }

    result = _summary(run, hit_latency_s=0.5)

    assert result["warm_candidate"] == {
        "usable_p50_s": 80.5,
        "usable_p95_s": 80.5,
        "complete_p50_s": 180.5,
        "complete_p95_s": 180.5,
        "tokens_mean": 80.0,
    }
    assert result["quality_identity"]["passed"] is True
    assert result["efficiency_passed"] is True


def test_cache_artifact_shape_is_json_serializable(tmp_path: Path):
    cached = ExactQueryBuilderCache(
        tmp_path,
        lambda question: (
            {"pubmed_query": question, "mesh_terms": [], "keywords_en": []},
            CodexUsage(input_tokens=3),
        ),
    )
    cached("q")
    cached("q")

    assert json.dumps([event.__dict__ for event in cached.events])
