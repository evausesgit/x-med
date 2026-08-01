from pathlib import Path

from app.services.codex_cli import CodexUsage
from experiments.autoresearch_xmed.query_cache import build_cached, cache_key


def test_query_cache_calls_builder_once_and_preserves_origin_usage(tmp_path: Path):
    calls = []

    def builder(question):
        calls.append(question)
        return {"pubmed_query": "A", "mesh_terms": [], "keywords_en": ["A"]}, CodexUsage(
            input_tokens=10, output_tokens=2
        )

    first, first_usage, first_hit = build_cached("question", tmp_path, builder)
    second, second_usage, second_hit = build_cached("question", tmp_path, builder)

    assert calls == ["question"]
    assert first == second
    assert first_usage == second_usage
    assert first_hit is False
    assert second_hit is True


def test_query_cache_does_not_merge_distinct_wording():
    assert cache_key("abc") != cache_key("abc ")
