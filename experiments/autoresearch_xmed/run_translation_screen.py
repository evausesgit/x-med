"""Screen sidecar de traduction, sans DB, cache ni retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings
from app.services import translate
from app.services.codex_cli import CodexUsage, run_codex
from experiments.autoresearch_xmed.manifest import fingerprint

TRANSLATE_TIMEOUT_S = 600
PUBLIC_FIELDS = {"item_id", "query_id", "pmid", "title", "abstract"}
PRIVATE_FORBIDDEN_FIELDS = {
    "title_fr",
    "abstract_fr",
    "baseline_translations",
    "retained_by",
    "source_artifacts",
    "selection_features",
    "provenance",
}

_COMPACT_PROMPT_HEAD = (
    "Traduis en français, sans ajout ni omission, chaque titre et résumé médical. "
    "Conserve exactement nombres, pourcentages, unités, acronymes et sens des "
    "négations. Réponds uniquement via le schéma JSON, une traduction par PMID.\n\n"
    "Articles :\n"
)

TranslationRunner = Callable[..., tuple[dict, CodexUsage]]


class TranslationScreenError(ValueError):
    """Pool, configuration ou réponse de traduction non démontrable."""


@dataclass(frozen=True)
class TranslationConfig:
    model: str = settings.codex_model_translate
    reasoning: str = settings.codex_reasoning_translate
    batch_size: int = 20
    shards: int = 1
    prompt_style: str = "baseline"
    repetitions: int = 1

    def __post_init__(self) -> None:
        for name in ("model", "reasoning"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TranslationScreenError(f"{name} doit être une chaîne non vide")
        for name in ("batch_size", "repetitions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise TranslationScreenError(f"{name} doit être strictement positif")
        if isinstance(self.shards, bool) or self.shards not in {1, 2}:
            raise TranslationScreenError("shards doit valoir 1 ou 2")
        if self.prompt_style not in {"baseline", "compact"}:
            raise TranslationScreenError("prompt_style doit valoir baseline ou compact")

    @property
    def exact_production_contract(self) -> bool:
        return (
            self.prompt_style == "baseline"
            and self.shards == 1
            and self.model == settings.codex_model_translate
            and self.reasoning == settings.codex_reasoning_translate
        )


def _machine_fingerprint() -> str:
    return fingerprint(
        {
            "node": platform.node(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        }
    )


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_pool(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TranslationScreenError(f"pool illisible: {path}") from exc
    items = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranslationScreenError(f"JSON invalide ligne {line_number}") from exc
        if not isinstance(item, dict):
            raise TranslationScreenError(f"objet attendu ligne {line_number}")
        missing = sorted(PUBLIC_FIELDS - set(item))
        extra = sorted(set(item) - PUBLIC_FIELDS)
        leaked = sorted(set(item) & PRIVATE_FORBIDDEN_FIELDS)
        if missing or extra or leaked:
            raise TranslationScreenError(
                f"pool aveugle invalide ligne {line_number}: "
                f"missing={missing}, extra={extra}, leaked={leaked}"
            )
        if not isinstance(item["item_id"], str) or not item["item_id"].strip():
            raise TranslationScreenError(f"item_id invalide ligne {line_number}")
        if not isinstance(item["query_id"], str) or not item["query_id"].strip():
            raise TranslationScreenError(f"query_id invalide ligne {line_number}")
        if isinstance(item["pmid"], bool) or not isinstance(item["pmid"], int) or item["pmid"] <= 0:
            raise TranslationScreenError(f"PMID invalide ligne {line_number}")
        for field in ("title", "abstract"):
            if not isinstance(item[field], str):
                raise TranslationScreenError(f"{field} invalide ligne {line_number}")
        if not item["abstract"].strip():
            raise TranslationScreenError(f"abstract absent ligne {line_number}")
        items.append(item)
    if not items:
        raise TranslationScreenError("pool vide")
    item_ids = [item["item_id"] for item in items]
    pmids = [item["pmid"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise TranslationScreenError("item_id dupliqué")
    if len(pmids) != len(set(pmids)):
        raise TranslationScreenError("PMID dupliqué")
    return items


def build_prompt(items: list[dict], config: TranslationConfig) -> str:
    rendered_items = [
        {"pmid": item["pmid"], "title": item["title"], "abstract": item["abstract"]}
        for item in items
    ]
    head = translate._PROMPT_HEAD if config.prompt_style == "baseline" else _COMPACT_PROMPT_HEAD
    return head + translate._render(rendered_items)


def _usage_dict(usage: object) -> dict[str, int]:
    if not hasattr(usage, "as_dict"):
        raise TranslationScreenError("usage tokens absent")
    raw = usage.as_dict()
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {}
    for key in keys:
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TranslationScreenError(f"usage {key} invalide")
        out[key] = value
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def _validate_translations(data: dict, expected_pmids: list[int]) -> dict[int, dict]:
    rows = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise TranslationScreenError("réponse sans liste translations")
    parsed = {}
    duplicates = []
    for row in rows:
        if not isinstance(row, dict):
            raise TranslationScreenError("traduction non objet")
        pmid = row.get("pmid")
        if isinstance(pmid, bool) or not isinstance(pmid, int):
            raise TranslationScreenError("PMID de traduction invalide")
        if pmid in parsed:
            duplicates.append(pmid)
            continue
        title_fr = row.get("title_fr")
        abstract_fr = row.get("abstract_fr")
        if not isinstance(title_fr, str) or not isinstance(abstract_fr, str):
            raise TranslationScreenError(f"textes traduits invalides pour PMID {pmid}")
        parsed[pmid] = {
            "pmid": pmid,
            "title_fr": title_fr.strip(),
            "abstract_fr": abstract_fr.strip(),
        }
    expected = set(expected_pmids)
    observed = set(parsed)
    missing = sorted(expected - observed)
    extras = sorted(observed - expected)
    if duplicates or missing or extras or len(rows) != len(expected_pmids):
        raise TranslationScreenError(
            f"PMID incohérents: missing={missing}, extras={extras}, "
            f"duplicates={sorted(set(duplicates))}"
        )
    return parsed


_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_UNIT_RE = re.compile(
    r"\b(?:mg|kg|g|µg|mcg|mL|L|mmHg|cm|mm|µm|nm|mmol/L|mg/dL|mL/min)\b",
    re.IGNORECASE,
)
_ACRONYM_RE = re.compile(r"\b(?=[A-Z0-9-]{2,}\b)(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]+\b")


def _normalized(values: list[str], *, lower: bool = False) -> list[str]:
    out = [re.sub(r"\s+", "", value.replace(",", ".")) for value in values]
    return [value.lower() for value in out] if lower else out


def _preservation(source: str, target: str, pattern: re.Pattern, *, lower: bool = False) -> dict:
    expected = _normalized(pattern.findall(source), lower=lower)
    observed = _normalized(pattern.findall(target), lower=lower)
    remaining = list(observed)
    missing = []
    for value in expected:
        if value in remaining:
            remaining.remove(value)
        else:
            missing.append(value)
    return {
        "expected": expected,
        "observed": observed,
        "missing": missing,
        "passed": not missing,
    }


def translation_checks(item: dict, translated: dict) -> dict:
    source = f"{item['title']}\n{item['abstract']}"
    target = f"{translated['title_fr']}\n{translated['abstract_fr']}"
    title_ratio = len(translated["title_fr"]) / len(item["title"]) if item["title"] else None
    abstract_ratio = len(translated["abstract_fr"]) / len(item["abstract"])
    return {
        "non_empty": {
            "title_fr": bool(translated["title_fr"]),
            "abstract_fr": bool(translated["abstract_fr"]),
        },
        "numbers": _preservation(source, target, _NUMBER_RE),
        "percentages": _preservation(source, target, _PERCENT_RE),
        "units": _preservation(source, target, _UNIT_RE, lower=True),
        "acronyms": _preservation(source, target, _ACRONYM_RE),
        "length_ratios": {
            "title": title_ratio,
            "abstract": abstract_ratio,
            "title_in_diagnostic_range": title_ratio is None or 0.35 <= title_ratio <= 2.5,
            "abstract_in_diagnostic_range": 0.5 <= abstract_ratio <= 2.0,
        },
        "diagnostic_only": True,
    }


def _split_shards(items: list[dict], shards: int) -> list[list[dict]]:
    if shards == 1 or len(items) < 2:
        return [items]
    split = (len(items) + 1) // 2
    return [items[:split], items[split:]]


def _run_shard(
    items: list[dict],
    config: TranslationConfig,
    runner: TranslationRunner,
    batch_index: int,
    shard_index: int,
) -> dict:
    prompt = build_prompt(items, config)
    expected_pmids = [item["pmid"] for item in items]
    started = time.monotonic()
    data, usage = runner(
        prompt,
        translate._SCHEMA,
        TRANSLATE_TIMEOUT_S,
        model=config.model,
        reasoning=config.reasoning,
    )
    return {
        "batch_index": batch_index,
        "shard_index": shard_index,
        "pmids": expected_pmids,
        "latency_s": time.monotonic() - started,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "usage": _usage_dict(usage),
        "translations": _validate_translations(data, expected_pmids),
    }


def _sum_usage(calls: list[dict]) -> dict[str, int]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {key: sum(call["usage"][key] for call in calls) for key in keys}
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def run_repetition(
    items: list[dict],
    config: TranslationConfig,
    runner: TranslationRunner = run_codex,
    repetition: int = 1,
) -> dict:
    started = time.monotonic()
    expected_pmids = [item["pmid"] for item in items]
    by_pmid = {item["pmid"]: item for item in items}
    translations = {}
    calls = []
    batches = [
        items[offset : offset + config.batch_size]
        for offset in range(0, len(items), config.batch_size)
    ]
    for batch_index, batch in enumerate(batches, 1):
        shards = _split_shards(batch, config.shards)
        if len(shards) == 2:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _run_shard,
                        shard,
                        config,
                        runner,
                        batch_index,
                        shard_index,
                    )
                    for shard_index, shard in enumerate(shards, 1)
                ]
                shard_results = [future.result() for future in futures]
        else:
            shard_results = [_run_shard(shards[0], config, runner, batch_index, 1)]
        for call in shard_results:
            overlap = set(translations) & set(call["translations"])
            if overlap:
                raise TranslationScreenError(f"PMID dupliqués entre shards: {sorted(overlap)}")
            translations.update(call["translations"])
            calls.append(call)
    if set(translations) != set(expected_pmids) or len(translations) != len(expected_pmids):
        raise TranslationScreenError("réassemblage des traductions incomplet")
    rows = []
    for pmid in expected_pmids:
        translated = translations[pmid]
        item = by_pmid[pmid]
        rows.append(
            {
                "item_id": item["item_id"],
                "query_id": item["query_id"],
                **translated,
                "checks": translation_checks(item, translated),
            }
        )
    return {
        "repetition": repetition,
        "latency_s": time.monotonic() - started,
        "tokens": _sum_usage(calls),
        "calls": [
            {key: value for key, value in call.items() if key != "translations"} for call in calls
        ],
        "translations": rows,
    }


def run_screen(
    pool_path: Path,
    out_path: Path,
    config: TranslationConfig,
    runner: TranslationRunner = run_codex,
) -> dict:
    items = load_pool(pool_path)
    config_dict = asdict(config)
    output = {
        "schema_version": 1,
        "artifact_type": "translation_screen",
        "run_id": f"translation-screen-{time.time_ns()}",
        "complete": False,
        "expected_item_ids": [item["item_id"] for item in items],
        "expected_pmids": [item["pmid"] for item in items],
        "source_pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "machine_fingerprint": _machine_fingerprint(),
        "config": config_dict,
        "config_fingerprint": fingerprint(config_dict),
        "prompt_contract_fingerprint": fingerprint(
            {
                "prompt_head": (
                    translate._PROMPT_HEAD
                    if config.prompt_style == "baseline"
                    else _COMPACT_PROMPT_HEAD
                ),
                "schema": translate._SCHEMA,
                "renderer": "app.services.translate._render",
            }
        ),
        "exact_production_contract": config.exact_production_contract,
        "external_calls": {
            "database": False,
            "cache": False,
            "retrieval": False,
            "llm_sidecar": True,
        },
        "repetitions": [],
    }
    _write_atomic(out_path, output)
    for repetition in range(1, config.repetitions + 1):
        output["repetitions"].append(run_repetition(items, config, runner, repetition))
        _write_atomic(out_path, output)
    output["latency_s"] = sum(value["latency_s"] for value in output["repetitions"])
    output["tokens"] = {
        key: sum(value["tokens"][key] for value in output["repetitions"])
        for key in output["repetitions"][0]["tokens"]
    }
    output["complete"] = True
    _write_atomic(out_path, output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=settings.codex_model_translate)
    parser.add_argument("--reasoning", default=settings.codex_reasoning_translate)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--shards", type=int, choices=(1, 2), default=1)
    parser.add_argument("--prompt-style", choices=("baseline", "compact"), default="baseline")
    parser.add_argument("--repetitions", type=int, default=1)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = TranslationConfig(
            model=args.model,
            reasoning=args.reasoning,
            batch_size=args.batch_size,
            shards=args.shards,
            prompt_style=args.prompt_style,
            repetitions=args.repetitions,
        )
        output = run_screen(args.pool, args.out, config)
    except TranslationScreenError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    print(
        json.dumps(
            {
                "items": len(output["expected_item_ids"]),
                "repetitions": len(output["repetitions"]),
                "total_tokens": output["tokens"]["total_tokens"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
