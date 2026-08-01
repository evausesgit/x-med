from copy import deepcopy
import json
import re
import threading

import pytest

from app.services import translate
from app.services.codex_cli import CodexUsage
from experiments.autoresearch_xmed.run_translation_screen import (
    TRANSLATE_TIMEOUT_S,
    TranslationConfig,
    TranslationScreenError,
    build_parser,
    build_prompt,
    load_pool,
    run_repetition,
    run_screen,
    translation_checks,
)


def _item(pmid):
    return {
        "item_id": f"item-{pmid}",
        "query_id": "q01",
        "pmid": pmid,
        "title": f"COPD study {pmid}",
        "abstract": f"No benefit at 12.5 mg for 30% of SGLT2 patients in study {pmid}.",
    }


def _write_pool(path, items):
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def _pmids(prompt):
    return [int(value) for value in re.findall(r"^- PMID (\d+)$", prompt, re.MULTILINE)]


def _response(pmids, *, reverse=False):
    values = reversed(pmids) if reverse else pmids
    return {
        "translations": [
            {
                "pmid": pmid,
                "title_fr": f"Étude COPD {pmid}",
                "abstract_fr": (
                    f"Aucun bénéfice à 12,5 mg pour 30 % des patients SGLT2 dans l'étude {pmid}."
                ),
            }
            for pmid in values
        ]
    }


def test_baseline_prompt_schema_and_renderer_are_byte_exact():
    item = _item(1)
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        calls.append((prompt, schema, timeout, kwargs))
        return _response([1]), CodexUsage(input_tokens=10, output_tokens=5)

    result = run_repetition([item], TranslationConfig(), runner)
    expected_items = [{"pmid": item["pmid"], "title": item["title"], "abstract": item["abstract"]}]
    expected_prompt = translate._PROMPT_HEAD + translate._render(expected_items)

    assert build_prompt([item], TranslationConfig()) == expected_prompt
    assert calls == [
        (
            expected_prompt,
            translate._SCHEMA,
            TRANSLATE_TIMEOUT_S,
            {
                "model": TranslationConfig().model,
                "reasoning": TranslationConfig().reasoning,
            },
        )
    ]
    assert result["translations"][0]["pmid"] == 1


def test_exact_production_contract_includes_model_reasoning_and_orchestration():
    assert TranslationConfig().exact_production_contract is True
    assert TranslationConfig(batch_size=10).exact_production_contract is True
    assert TranslationConfig(shards=2).exact_production_contract is False
    assert TranslationConfig(prompt_style="compact").exact_production_contract is False
    assert TranslationConfig(model="other").exact_production_contract is False
    assert TranslationConfig(reasoning="other").exact_production_contract is False


def test_two_shards_are_concurrent_and_reassemble_input_order():
    barrier = threading.Barrier(2)
    threads = []

    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        threads.append(threading.get_ident())
        barrier.wait(timeout=2)
        pmids = _pmids(prompt)
        return _response(pmids, reverse=True), CodexUsage(input_tokens=4, output_tokens=2)

    items = [_item(pmid) for pmid in range(1, 5)]
    result = run_repetition(items, TranslationConfig(batch_size=4, shards=2), runner)

    assert len(set(threads)) == 2
    assert [call["pmids"] for call in result["calls"]] == [[1, 2], [3, 4]]
    assert [row["pmid"] for row in result["translations"]] == [1, 2, 3, 4]
    assert result["tokens"]["total_tokens"] == 12


@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate"])
def test_translation_response_requires_strict_pmid_bijection(defect):
    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        pmids = _pmids(prompt)
        response = _response(pmids)
        if defect == "missing":
            response["translations"].pop()
        elif defect == "extra":
            response["translations"].extend(_response([999])["translations"])
        else:
            response["translations"].append(deepcopy(response["translations"][0]))
        return response, CodexUsage()

    with pytest.raises(TranslationScreenError, match="PMID incohérents"):
        run_repetition([_item(1), _item(2)], TranslationConfig(), runner)


def test_automatic_checks_are_diagnostic_and_detect_losses():
    item = _item(1)
    faithful = _response([1])["translations"][0]
    checks = translation_checks(item, faithful)
    assert checks["numbers"]["passed"] is True
    assert checks["percentages"]["passed"] is True
    assert checks["units"]["passed"] is True
    assert checks["acronyms"]["passed"] is True
    assert checks["non_empty"] == {"title_fr": True, "abstract_fr": True}
    assert checks["diagnostic_only"] is True

    lossy = {"pmid": 1, "title_fr": "", "abstract_fr": "Texte sans données."}
    failed = translation_checks(item, lossy)
    assert failed["numbers"]["passed"] is False
    assert failed["percentages"]["passed"] is False
    assert failed["units"]["passed"] is False
    assert failed["acronyms"]["passed"] is False
    assert failed["non_empty"]["title_fr"] is False


def test_pool_validation_rejects_private_leaks_and_duplicate_pmids(tmp_path):
    pool = tmp_path / "pool.jsonl"
    items = [_item(1), _item(2)]
    _write_pool(pool, items)
    assert load_pool(pool) == items

    leaked = deepcopy(items)
    leaked[0]["abstract_fr"] = "secret"
    _write_pool(pool, leaked)
    with pytest.raises(TranslationScreenError, match="aveugle invalide"):
        load_pool(pool)

    duplicated = [items[0], {**items[1], "pmid": 1}]
    _write_pool(pool, duplicated)
    with pytest.raises(TranslationScreenError, match="PMID dupliqué"):
        load_pool(pool)


def test_screen_is_injected_complete_fingerprinted_and_atomic(tmp_path):
    pool = tmp_path / "pool.jsonl"
    out = tmp_path / "screen.json"
    _write_pool(pool, [_item(1), _item(2)])
    calls = []

    def runner(prompt, schema, timeout, **kwargs):
        del schema, timeout, kwargs
        calls.append(prompt)
        pmids = _pmids(prompt)
        return _response(pmids), CodexUsage(input_tokens=3, output_tokens=1)

    result = run_screen(pool, out, TranslationConfig(repetitions=2), runner)
    persisted = json.loads(out.read_text(encoding="utf-8"))

    assert persisted == result
    assert result["complete"] is True
    assert result["expected_pmids"] == [1, 2]
    assert len(result["repetitions"]) == 2
    assert len(calls) == 2
    assert len(result["source_pool_sha256"]) == 64
    assert len(result["config_fingerprint"]) == 64
    assert len(result["prompt_contract_fingerprint"]) == 64
    assert result["external_calls"] == {
        "database": False,
        "cache": False,
        "retrieval": False,
        "llm_sidecar": True,
    }
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "values",
    [
        {"model": ""},
        {"reasoning": ""},
        {"batch_size": 0},
        {"shards": 3},
        {"shards": True},
        {"prompt_style": "other"},
        {"repetitions": 0},
    ],
)
def test_config_rejects_invalid_values(values):
    with pytest.raises(TranslationScreenError):
        TranslationConfig(**values)


def test_parser_exposes_translation_screen_knobs():
    args = build_parser().parse_args(
        [
            "pool.jsonl",
            "--out",
            "screen.json",
            "--model",
            "translator",
            "--reasoning",
            "low",
            "--batch-size",
            "12",
            "--shards",
            "2",
            "--prompt-style",
            "compact",
            "--repetitions",
            "3",
        ]
    )
    assert (
        args.model,
        args.reasoning,
        args.batch_size,
        args.shards,
        args.prompt_style,
        args.repetitions,
    ) == ("translator", "low", 12, 2, "compact", 3)
