import json
import re
import threading
from copy import deepcopy

import pytest

from app.services import codex_judge
from app.services.codex_cli import CodexUsage
from experiments.autoresearch_xmed.run_judge_screen import (
    JUDGE_TIMEOUT_S,
    JudgeConfig,
    JudgeScreenError,
    build_parser,
    build_prompt,
    group_by_query,
    load_pool,
    run_query,
    run_screen,
)


def _item(pmid: int, query_id: str = "q1", query: str = "question clinique") -> dict:
    return {
        "item_id": f"item-{query_id}-{pmid}",
        "query_id": query_id,
        "query": query,
        "pmid": pmid,
        "title": f"title {pmid}",
        "abstract": f"abstract {pmid}",
        "journal": f"journal {pmid}",
        "pub_year": 2025,
        "evidence_level": 2,
    }


def _write_pool(path, items):
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )


def _pmids(prompt: str) -> list[int]:
    return [int(value) for value in re.findall(r"^- PMID (\d+)$", prompt, flags=re.MULTILINE)]


def _response(pmids: list[int], reverse: bool = False) -> dict:
    values = reversed(pmids) if reverse else pmids
    return {
        "judgements": [
            {
                "pmid": pmid,
                "score": 2,
                "relevance_pct": 70,
                "reason": f"apport {pmid}",
            }
            for pmid in values
        ]
    }


def test_baseline_prompt_schema_and_render_are_byte_exact():
    item = _item(1)
    item["abstract"] = "A" * 1300
    config = JudgeConfig()
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        calls.append((prompt, schema, timeout, kwargs))
        return _response([1]), CodexUsage(input_tokens=10, output_tokens=2)

    result = run_query("q1", [item], config, runner)
    article = {
        key: item.get(key)
        for key in ("pmid", "title", "abstract", "journal", "pub_year", "evidence_level")
    }
    expected = codex_judge._PROMPT_HEAD.format(prm=item["query"]) + codex_judge._render_articles(
        [article]
    )
    assert config.exact_production_prompt is True
    assert calls == [
        (
            expected,
            codex_judge._SCHEMA,
            JUDGE_TIMEOUT_S,
            {"model": config.model, "reasoning": config.reasoning},
        )
    ]
    assert result["repetitions"][0]["judgements"][0]["pmid"] == 1


def test_head_tail_preserves_both_ends_and_drops_middle():
    item = _item(1)
    item["abstract"] = "ABCDE-middle-UVWXY"
    config = JudgeConfig(max_abstract_chars=10, abstract_mode="head_tail")
    prompt = build_prompt(item["query"], [item], config)
    assert "ABCDE … UVWXY" in prompt
    assert "middle" not in prompt


def test_compact_prompt_is_a_distinct_sidecar_variant():
    item = _item(1)
    compact = build_prompt(item["query"], [item], JudgeConfig(prompt_style="compact"))
    baseline = build_prompt(item["query"], [item], JudgeConfig())
    assert compact != baseline
    assert item["query"] in compact
    assert "- PMID 1" in compact


def test_two_shards_run_concurrently_and_reassemble_stable_order():
    barrier = threading.Barrier(2)
    thread_ids = []

    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        thread_ids.append(threading.get_ident())
        barrier.wait(timeout=2)
        pmids = _pmids(prompt)
        return _response(pmids, reverse=True), CodexUsage(input_tokens=5, output_tokens=1)

    config = JudgeConfig(batch_size=4, shards=2)
    result = run_query("q1", [_item(pmid) for pmid in range(1, 5)], config, runner)
    repetition = result["repetitions"][0]
    assert len(set(thread_ids)) == 2
    assert [call["pmids"] for call in repetition["calls"]] == [[1, 2], [3, 4]]
    assert [row["pmid"] for row in repetition["judgements"]] == [1, 2, 3, 4]
    assert repetition["tokens"]["total_tokens"] == 12


@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate"])
def test_missing_extra_or_duplicate_judgements_are_refused(defect):
    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        pmids = _pmids(prompt)
        response = _response(pmids)
        if defect == "missing":
            response["judgements"].pop()
        elif defect == "extra":
            response["judgements"].extend(_response([999])["judgements"])
        else:
            response["judgements"].append(deepcopy(response["judgements"][0]))
        return response, CodexUsage()

    with pytest.raises(JudgeScreenError, match="PMID incohérents"):
        run_query("q1", [_item(1), _item(2)], JudgeConfig(), runner)


def test_pool_validation_requires_blind_metadata_and_unique_ids(tmp_path):
    pool = tmp_path / "pool.jsonl"
    items = [_item(1), _item(2)]
    _write_pool(pool, items)
    assert load_pool(pool) == items

    leaked = deepcopy(items)
    leaked[0]["score"] = 3
    _write_pool(pool, leaked)
    with pytest.raises(JudgeScreenError, match="leaked"):
        load_pool(pool)

    duplicated = [items[0], {**items[1], "item_id": items[0]["item_id"]}]
    _write_pool(pool, duplicated)
    with pytest.raises(JudgeScreenError, match="item_id dupliqué"):
        load_pool(pool)

    incomplete = deepcopy(items)
    incomplete[0]["abstract"] = None
    _write_pool(pool, incomplete)
    with pytest.raises(JudgeScreenError, match="abstract absent"):
        load_pool(pool)


def test_grouping_preserves_first_query_and_item_order():
    items = [
        _item(2, "q2", "question 2"),
        _item(1, "q1", "question 1"),
        _item(3, "q2", "question 2"),
    ]
    groups = group_by_query(items)
    assert [query_id for query_id, _ in groups] == ["q2", "q1"]
    assert [[item["pmid"] for item in values] for _, values in groups] == [[2, 3], [1]]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"reasoning": ""},
        {"batch_size": 0},
        {"max_abstract_chars": 0},
        {"repetitions": 0},
        {"abstract_mode": "middle"},
        {"prompt_style": "other"},
        {"shards": 3},
        {"shards": True},
    ],
)
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(JudgeScreenError):
        JudgeConfig(**kwargs)


def test_parser_exposes_all_judge_screen_knobs():
    args = build_parser().parse_args(
        [
            "pool.jsonl",
            "--out",
            "screen.json",
            "--model",
            "judge-model",
            "--reasoning",
            "low",
            "--batch-size",
            "24",
            "--max-abstract-chars",
            "900",
            "--abstract-mode",
            "head_tail",
            "--prompt-style",
            "compact",
            "--shards",
            "2",
            "--repetitions",
            "3",
        ]
    )
    assert (
        args.model,
        args.reasoning,
        args.batch_size,
        args.max_abstract_chars,
        args.abstract_mode,
        args.prompt_style,
        args.shards,
        args.repetitions,
    ) == ("judge-model", "low", 24, 900, "head_tail", "compact", 2, 3)


def test_run_screen_is_injected_complete_and_fingerprinted(tmp_path):
    pool = tmp_path / "pool.jsonl"
    out = tmp_path / "screen.json"
    _write_pool(pool, [_item(2, "q2", "question 2"), _item(1, "q1", "question 1")])
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        calls.append(prompt)
        pmids = _pmids(prompt)
        return _response(pmids), CodexUsage(input_tokens=3, output_tokens=1)

    result = run_screen(pool, out, JudgeConfig(repetitions=2), runner)
    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert result == persisted
    assert persisted["complete"] is True
    assert persisted["expected_query_ids"] == ["q2", "q1"]
    assert persisted["calls"] == {"database": False, "retrieval": False, "translate": False}
    assert len(calls) == 4
    assert len(persisted["source_pool_sha256"]) == 64
    assert len(persisted["config_fingerprint"]) == 64
    assert list(tmp_path.glob("*.tmp")) == []
