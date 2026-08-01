import hashlib
import json

import pytest

from experiments.autoresearch_xmed.build_translation_comparison import (
    TranslationComparisonError,
    build,
    write_outputs,
)


def _item(pmid):
    return {
        "item_id": f"item-{pmid}",
        "query_id": f"q{pmid:02d}",
        "pmid": pmid,
        "title": f"Title {pmid}",
        "abstract": f"No benefit at {pmid} mg in COPD.",
    }


def _write_pool(path, items):
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def _screen(path, pool, items, prefix):
    pool_sha = hashlib.sha256(pool.read_bytes()).hexdigest()
    translations = [
        {
            "item_id": item["item_id"],
            "query_id": item["query_id"],
            "pmid": item["pmid"],
            "title_fr": f"{prefix} titre {item['pmid']}",
            "abstract_fr": f"{prefix} résumé {item['pmid']}",
        }
        for item in items
    ]
    value = {
        "artifact_type": "translation_screen",
        "complete": True,
        "source_pool_sha256": pool_sha,
        "runner_sha256": f"runner-{prefix}",
        "config_fingerprint": f"config-{prefix}",
        "expected_item_ids": [item["item_id"] for item in items],
        "repetitions": [{"translations": translations}],
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def test_comparison_randomizes_system_labels_and_keeps_mapping_private(tmp_path):
    items = [_item(pmid) for pmid in range(1, 11)]
    pool = tmp_path / "pool.jsonl"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_pool(pool, items)
    _screen(baseline, pool, items, "BASELINE_SECRET")
    _screen(candidate, pool, items, "CANDIDATE_SECRET")

    blind, key = build(pool, baseline, candidate, seed=17)
    blind_again, key_again = build(pool, baseline, candidate, seed=17)

    assert blind == blind_again
    assert key["items"] == key_again["items"]
    assert {value["labels"]["baseline"] for value in key["items"].values()} == {"A", "B"}
    assert all(set(item["options"]) == {"A", "B"} for item in blind)
    public = json.dumps(blind)
    assert '"baseline":' not in public.lower()
    assert '"candidate":' not in public.lower()
    assert '"labels"' not in public.lower()
    assert all(
        set(value["stratum"]) == {"length", "risk", "combined"} for value in key["items"].values()
    )
    assert len(key["blind_pool_sha256"]) == 64


def test_comparison_validates_pool_fingerprint_and_item_bijection(tmp_path):
    items = [_item(1), _item(2)]
    pool = tmp_path / "pool.jsonl"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_pool(pool, items)
    _screen(baseline, pool, items, "base")
    _screen(candidate, pool, items, "cand")

    value = json.loads(candidate.read_text())
    value["source_pool_sha256"] = "wrong"
    candidate.write_text(json.dumps(value))
    with pytest.raises(TranslationComparisonError, match="pool source différent"):
        build(pool, baseline, candidate)

    _screen(candidate, pool, items, "cand")
    value = json.loads(candidate.read_text())
    value["repetitions"][0]["translations"].pop()
    candidate.write_text(json.dumps(value))
    with pytest.raises(TranslationComparisonError, match="bijection item_id"):
        build(pool, baseline, candidate)


def test_comparison_outputs_are_atomic_and_fingerprinted(tmp_path):
    items = [_item(1)]
    pool = tmp_path / "pool.jsonl"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    blind_path = tmp_path / "blind.jsonl"
    key_path = tmp_path / "key.json"
    _write_pool(pool, items)
    _screen(baseline, pool, items, "base")
    _screen(candidate, pool, items, "cand")
    blind, key = build(pool, baseline, candidate)

    write_outputs(blind_path, key_path, blind, key)

    assert hashlib.sha256(blind_path.read_bytes()).hexdigest() == key["blind_pool_sha256"]
    assert json.loads(key_path.read_text()) == key
    assert list(tmp_path.glob("*.tmp")) == []
