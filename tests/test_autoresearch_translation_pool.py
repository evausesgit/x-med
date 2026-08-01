import json

import pytest

from experiments.autoresearch_xmed.build_translation_pool import (
    TranslationPoolError,
    build,
    text_features,
    write_outputs,
)


def _result(pmid, abstract, **values):
    return {
        "pmid": pmid,
        "title": f"Title {pmid}",
        "abstract": abstract,
        "title_fr": f"Titre {pmid}",
        "abstract_fr": f"Résumé {pmid}",
        "evidence_level": values.pop("evidence_level", 2),
        **values,
    }


def _artifact(tmp_path, name, cases, *, complete=True):
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": name,
                "run_kind": "live",
                "complete": complete,
                "expected_query_ids": [case["query_id"] for case in cases],
                "protocol_fingerprint": "protocol",
                "variant_fingerprint": name,
                "corpus_fingerprint": "corpus",
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_pool_unites_retained_pmids_and_keeps_references_private(tmp_path):
    shared = _result(1, "No benefit at 12.5 mg; 95% CI 1-2 in COPD.")
    first = _artifact(
        tmp_path,
        "baseline-a",
        [
            {"query_id": "q02", "results": [shared]},
            {"query_id": "q01", "results": [_result(2, "Short abstract.")]},
        ],
    )
    second_shared = {**shared, "title_fr": "Autre titre", "abstract_fr": "Autre résumé"}
    second = _artifact(
        tmp_path,
        "baseline-b",
        [{"query_id": "q03", "results": [second_shared]}],
    )

    items, key = build([second, first])

    assert {item["pmid"] for item in items} == {1, 2}
    assert all(set(item) == {"item_id", "query_id", "pmid", "title", "abstract"} for item in items)
    shared_public = next(item for item in items if item["pmid"] == 1)
    assert shared_public["query_id"] == "q02"
    private = key["items"][shared_public["item_id"]]
    assert private["query_ids"] == ["q02", "q03"]
    assert [value["run_id"] for value in private["baseline_translations"]] == [
        "baseline-a",
        "baseline-b",
    ]
    rendered_pool = json.dumps(items, ensure_ascii=False)
    assert "Résumé" not in rendered_pool
    assert "retained_by" not in rendered_pool
    assert len(key["source_artifacts"]) == 2


def test_selection_is_bounded_deterministic_and_feature_stratified(tmp_path):
    abstracts = [
        "Plain text.",
        "Dose 12 mg reduced risk by 30% (95% CI 1-2).",
        "No benefit was observed in COPD.",
        "A" * 800,
        "B" * 1600,
        "SGLT2 was given at 10 mg without adverse effects.",
    ]
    first = _artifact(
        tmp_path,
        "a",
        [
            {
                "query_id": "q01",
                "results": [_result(i + 1, value) for i, value in enumerate(abstracts)],
            }
        ],
    )
    second = _artifact(tmp_path, "b", [{"query_id": "q02", "results": []}])

    selected_a, key_a = build([first, second], limit=4)
    selected_b, key_b = build([second, first], limit=4)

    assert selected_a == selected_b
    assert key_a["selection"] == key_b["selection"]
    assert len(selected_a) == 4
    signatures = {
        tuple(key_a["items"][item["item_id"]]["selection_features"].values()) for item in selected_a
    }
    assert len(signatures) == 4


def test_feature_detection_covers_requested_translation_risks():
    features = text_features(
        "No SGLT2 benefit at 12.5 mg (30%; 95% CI 1.0-2.0).",
        1,
    )
    assert features == {
        "length": "short",
        "numbers": True,
        "percent": True,
        "confidence_interval": True,
        "units": True,
        "acronyms": True,
        "negation": True,
        "evidence_level": 1,
    }


def test_pool_refuses_incomplete_live_or_conflicting_source_text(tmp_path):
    incomplete = _artifact(
        tmp_path,
        "incomplete",
        [{"query_id": "q01", "results": [_result(1, "Abstract")]}],
        complete=False,
    )
    with pytest.raises(TranslationPoolError, match="live complet"):
        build([incomplete])

    first = _artifact(
        tmp_path,
        "first",
        [{"query_id": "q01", "results": [_result(1, "First")]}],
    )
    second = _artifact(
        tmp_path,
        "second",
        [{"query_id": "q02", "results": [_result(1, "Different")]}],
    )
    with pytest.raises(TranslationPoolError, match="incompatibles"):
        build([first, second])


def test_pool_and_private_key_are_written_atomically(tmp_path):
    pool_path = tmp_path / "pool.jsonl"
    key_path = tmp_path / "key.json"
    items = [{"item_id": "one", "query_id": "q1", "pmid": 1, "title": "T", "abstract": "A"}]
    key = {"schema_version": 1, "items": {}}

    write_outputs(pool_path, key_path, items, key)

    assert json.loads(pool_path.read_text()) == items[0]
    assert json.loads(key_path.read_text()) == key
    assert list(tmp_path.glob("*.tmp")) == []
