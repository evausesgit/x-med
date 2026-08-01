import json
import os

import pytest

from experiments.autoresearch_xmed.build_judge_pool import (
    JudgePoolError,
    _validate_clone,
    build,
    write_outputs,
)


def _artifact(tmp_path, name, cases):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"run_id": name, "cases": cases}), encoding="utf-8")
    return path


def test_pool_unites_retained_and_hard_negatives_without_leaking_provenance(tmp_path):
    run1 = _artifact(
        tmp_path,
        "run1",
        [
            {
                "query_id": "q1",
                "query": "question",
                "judge_pmids": [1, 3],
                "results": [
                    {
                        "pmid": 1,
                        "title": "retained",
                        "abstract": "abstract 1",
                        "score": 3,
                        "reason": "secret",
                        "source": "pubmed",
                    },
                    {"pmid": 2, "title": "hors top", "abstract": "abstract 2"},
                ],
                "external": {
                    "esummary": {"values": {"3": {"title": "negative"}}},
                    "efetch": {"values": {"3": "abstract 3"}},
                },
            }
        ],
    )
    run2 = _artifact(
        tmp_path,
        "run2",
        [
            {
                "query_id": "q1",
                "query": "question",
                "judge_pmids": [3, 4],
                "results": [
                    {"pmid": 1, "title": "duplicate", "abstract": "duplicate"},
                    {"pmid": 4, "title": "retained 4", "abstract": "abstract 4"},
                ],
            }
        ],
    )

    items, key, counts = build([run1, run2], top_k=1, seed=7)

    assert {(item["query_id"], item["pmid"]) for item in items} == {
        ("q1", 1),
        ("q1", 3),
        ("q1", 4),
    }
    assert counts == {"q1": {"total": 3, "retained": 2, "hard_negative": 1, "missing_abstract": 0}}
    forbidden = {"score", "reason", "source", "run_id", "retained_by", "judge_input_by"}
    assert all(forbidden.isdisjoint(item) for item in items)

    by_pmid = {value["pmid"]: value for value in key["items"].values()}
    assert by_pmid[3]["retained_by"] == []
    assert by_pmid[3]["judge_input_by"] == ["run1", "run2"]
    assert by_pmid[4]["retained_by"] == ["run2"]


def test_metadata_precedence_is_results_then_external_then_clone(tmp_path):
    path = _artifact(
        tmp_path,
        "live",
        [
            {
                "query_id": "q1",
                "query": "question",
                "judge_pmids": [10, 20],
                "results": [{"pmid": 10, "title": "result title", "abstract": None}],
                "external": {
                    "esummary": {
                        "values": {"10": {"title": "external title", "journal": "external journal"}}
                    },
                    "efetch": {"values": {"10": "external abstract"}},
                    "local_pmids": [20],
                },
            }
        ],
    )
    requested = []

    def fetch(pmids):
        requested.append(set(pmids))
        return {
            10: {"title": "clone title", "abstract": "clone abstract"},
            20: {
                "title": "local title",
                "abstract": "local abstract",
                "journal": "local journal",
                "pub_year": 2026,
                "evidence_level": 1,
            },
        }

    items, _, counts = build([path], top_k=10, seed=1, fetch_from_clone=fetch)

    assert requested == [{20}]
    by_pmid = {item["pmid"]: item for item in items}
    assert by_pmid[10]["title"] == "result title"
    assert by_pmid[10]["abstract"] == "external abstract"
    assert by_pmid[10]["journal"] == "external journal"
    assert by_pmid[20]["title"] == "local title"
    assert by_pmid[20]["abstract"] == "local abstract"
    assert counts["q1"]["missing_abstract"] == 0


def test_retrieval_screen_metadata_hydrates_without_marking_retained(tmp_path):
    path = _artifact(
        tmp_path,
        "retrieval",
        [
            {
                "query_id": "q1",
                "query": "question",
                "judge_pmids": [42],
                "selected_metadata": [
                    {
                        "pmid": 42,
                        "title": "screened",
                        "abstract": "screen abstract",
                        "journal": "J",
                    }
                ],
                "results": [],
            }
        ],
    )

    items, key, counts = build([path], top_k=5, seed=1)

    assert items[0]["title"] == "screened"
    assert items[0]["abstract"] == "screen abstract"
    private = key["items"][items[0]["item_id"]]
    assert private["retained_by"] == []
    assert private["judge_input_by"] == ["retrieval"]
    assert counts["q1"]["hard_negative"] == 1


def test_missing_clone_row_is_counted_and_query_conflicts_fail(tmp_path):
    first = _artifact(
        tmp_path,
        "first",
        [{"query_id": "q1", "query": "one", "judge_pmids": [9], "results": []}],
    )
    items, _, counts = build([first], top_k=5, seed=1, fetch_from_clone=lambda _pmids: {})
    assert items[0]["abstract"] is None
    assert counts["q1"]["missing_abstract"] == 1

    second = _artifact(
        tmp_path,
        "second",
        [{"query_id": "q1", "query": "different", "judge_pmids": [], "results": []}],
    )
    with pytest.raises(JudgePoolError, match="questions incompatibles"):
        build([first, second], top_k=5, seed=1)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def tuples(self):
        return self

    def all(self):
        return self.rows


class _CloneConnection:
    def __init__(self, *, read_only="on", prepared="true"):
        self.read_only = read_only
        self.prepared = prepared

    def scalar(self, statement):
        sql = str(statement)
        if sql == "SHOW default_transaction_read_only":
            return self.read_only
        if sql == "SELECT current_database()":
            return "xmed_autoresearch_full"
        if "to_regclass('public.articles')" in sql:
            return "articles"
        if "to_regclass('public.autoresearch_meta')" in sql:
            return "autoresearch_meta"
        raise AssertionError(sql)

    def execute(self, statement):
        assert str(statement) == "SELECT key, value FROM autoresearch_meta"
        return _Rows([("prepared", self.prepared), ("scope", "full")])


def test_clone_guard_requires_autoresearch_read_only_and_prepared():
    metadata = _validate_clone(_CloneConnection(), "xmed_autoresearch_full")
    assert metadata["prepared"] == "true"

    with pytest.raises(JudgePoolError, match="doit contenir"):
        _validate_clone(_CloneConnection(), "xmed_prod")
    with pytest.raises(JudgePoolError, match="non read-only"):
        _validate_clone(_CloneConnection(read_only="off"), "xmed_autoresearch_full")
    with pytest.raises(JudgePoolError, match="non préparé"):
        _validate_clone(_CloneConnection(prepared="false"), "xmed_autoresearch_full")


def test_outputs_are_atomic_and_do_not_leave_temporary_files(tmp_path, monkeypatch):
    pool = tmp_path / "pool.jsonl"
    key = tmp_path / "pool.key.json"
    pool.write_text("old pool", encoding="utf-8")
    key.write_text("old key", encoding="utf-8")
    items = [{"item_id": "id", "query_id": "q1", "pmid": 1}]
    private = {"schema_version": 1, "items": {}}

    write_outputs(pool, key, items, private)
    assert json.loads(pool.read_text(encoding="utf-8")) == items[0]
    assert json.loads(key.read_text(encoding="utf-8")) == private
    assert list(tmp_path.glob("*.tmp")) == []

    original_replace = os.replace

    def fail_replace(source, destination):
        if destination == pool:
            raise OSError("replace failed")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_outputs(pool, key, [{"pmid": 2}], private)
    assert json.loads(pool.read_text(encoding="utf-8")) == items[0]
    assert list(tmp_path.glob("*.tmp")) == []
