"""Juge bilingue aveugle A/B pour les variantes de traduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings
from app.services.codex_cli import CodexUsage, run_codex
from experiments.autoresearch_xmed.manifest import fingerprint

JUDGE_TIMEOUT_S = 600
LABELS = ("A", "B")
SCORE_KEYS = ("clinical_fidelity", "terminology", "readability")

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "item_id": {"type": "string"},
                    "pmid": {"type": "integer"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "label": {"type": "string", "enum": ["A", "B"]},
                                "clinical_fidelity": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 5,
                                },
                                "terminology": {"type": "integer", "minimum": 1, "maximum": 5},
                                "readability": {"type": "integer", "minimum": 1, "maximum": 5},
                                "critical_errors": {"type": "array", "items": {"type": "string"}},
                                "omissions": {"type": "array", "items": {"type": "string"}},
                                "hallucinations": {"type": "array", "items": {"type": "string"}},
                                "rationale": {"type": "string"},
                            },
                            "required": [
                                "label",
                                "clinical_fidelity",
                                "terminology",
                                "readability",
                                "critical_errors",
                                "omissions",
                                "hallucinations",
                                "rationale",
                            ],
                        },
                    },
                },
                "required": ["item_id", "pmid", "options"],
            },
        }
    },
    "required": ["evaluations"],
}

_PROMPT_HEAD = """Tu es un évaluateur bilingue anglais-français spécialisé en médecine.
Compare chaque traduction française uniquement au texte source anglais. Les options A/B
sont anonymisées : ne tente jamais d'identifier leur système.

Note chaque option séparément sur trois échelles entières de 1 à 5 :
- clinical_fidelity : 1=contre-sens/risque clinique majeur, 2=erreur ou omission majeure,
  3=sens global préservé avec défauts mineurs, 4=fidèle, 5=entièrement fidèle et nuancé.
- terminology : 1=terminologie dangereuse, 2=plusieurs termes faux, 3=acceptable avec
  imprécisions, 4=correcte, 5=précise et idiomatique pour un médecin francophone.
- readability : 1=incompréhensible, 2=difficile, 3=lisible mais maladroit, 4=clair,
  5=fluide et clinique sans altérer le sens.

Liste explicitement : critical_errors (contre-sens susceptible de changer une décision,
nombre/dose/unité/population/négation erroné), omissions significatives et hallucinations.
Une liste vide signifie qu'aucun défaut de cette catégorie n'est détecté. Donne une courte
rationale factuelle par option. Réponds uniquement via le schéma JSON imposé.

Comparaisons :
"""

JudgeRunner = Callable[..., tuple[dict, CodexUsage]]


class BilingualJudgeError(ValueError):
    """Pool, configuration ou sortie du juge bilingue invalide."""


@dataclass(frozen=True)
class BilingualJudgeConfig:
    model: str = settings.codex_model
    reasoning: str = settings.codex_reasoning
    batch_size: int = 8
    repetitions: int = 3

    def __post_init__(self) -> None:
        for name in ("model", "reasoning"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise BilingualJudgeError(f"{name} doit être une chaîne non vide")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size <= 0
        ):
            raise BilingualJudgeError("batch_size doit être strictement positif")
        if isinstance(self.repetitions, bool) or self.repetitions not in {2, 3}:
            raise BilingualJudgeError("repetitions doit valoir 2 ou 3")


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
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
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


def load_blind_pool(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BilingualJudgeError(f"pool aveugle illisible: {path}") from exc
    items = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BilingualJudgeError(f"JSON invalide ligne {line_number}") from exc
        if not isinstance(item, dict) or set(item) != {
            "item_id",
            "query_id",
            "pmid",
            "source",
            "options",
        }:
            raise BilingualJudgeError(f"champs aveugles invalides ligne {line_number}")
        if not isinstance(item["item_id"], str) or not item["item_id"]:
            raise BilingualJudgeError(f"item_id invalide ligne {line_number}")
        if not isinstance(item["query_id"], str) or not item["query_id"]:
            raise BilingualJudgeError(f"query_id invalide ligne {line_number}")
        if isinstance(item["pmid"], bool) or not isinstance(item["pmid"], int):
            raise BilingualJudgeError(f"PMID invalide ligne {line_number}")
        source = item["source"]
        options = item["options"]
        if not isinstance(source, dict) or set(source) != {"title", "abstract"}:
            raise BilingualJudgeError(f"source invalide ligne {line_number}")
        if any(not isinstance(source[key], str) or not source[key].strip() for key in source):
            raise BilingualJudgeError(f"texte source absent ligne {line_number}")
        if not isinstance(options, dict) or set(options) != set(LABELS):
            raise BilingualJudgeError(f"options A/B invalides ligne {line_number}")
        for label in LABELS:
            option = options[label]
            if not isinstance(option, dict) or set(option) != {"title_fr", "abstract_fr"}:
                raise BilingualJudgeError(f"option {label} invalide ligne {line_number}")
            if any(not isinstance(option[key], str) for key in option):
                raise BilingualJudgeError(f"texte option {label} invalide ligne {line_number}")
        items.append(item)
    if not items:
        raise BilingualJudgeError("pool aveugle vide")
    ids = [item["item_id"] for item in items]
    pmids = [item["pmid"] for item in items]
    if len(ids) != len(set(ids)) or len(pmids) != len(set(pmids)):
        raise BilingualJudgeError("item_id ou PMID dupliqué")
    return items


def _label_order(item_id: str, repetition: int) -> tuple[str, str]:
    digest = hashlib.sha256(f"presentation:{repetition}:{item_id}".encode()).digest()
    return LABELS if digest[0] % 2 == 0 else tuple(reversed(LABELS))


def build_prompt(items: list[dict], repetition: int) -> str:
    blocks = []
    for item in items:
        option_blocks = []
        for label in _label_order(item["item_id"], repetition):
            option = item["options"][label]
            option_blocks.append(
                f"  Option {label}\n"
                f"    Titre FR : {option['title_fr']}\n"
                f"    Résumé FR : {option['abstract_fr']}"
            )
        blocks.append(
            f"- item_id {item['item_id']} · PMID {item['pmid']}\n"
            f"  Titre EN : {item['source']['title']}\n"
            f"  Résumé EN : {item['source']['abstract']}\n" + "\n".join(option_blocks)
        )
    return _PROMPT_HEAD + "\n".join(blocks)


def _usage_dict(usage: object) -> dict[str, int]:
    if not hasattr(usage, "as_dict"):
        raise BilingualJudgeError("usage tokens absent")
    raw = usage.as_dict()
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {}
    for key in keys:
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BilingualJudgeError(f"usage {key} invalide")
        out[key] = value
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def _string_list(value: object, field: str, item_id: str, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise BilingualJudgeError(f"{field} invalide pour {item_id}/{label}")
    return [item.strip() for item in value]


def _validate_response(data: dict, expected: list[dict]) -> dict[str, dict]:
    rows = data.get("evaluations") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise BilingualJudgeError("réponse sans evaluations")
    expected_map = {item["item_id"]: item["pmid"] for item in expected}
    parsed = {}
    duplicates = []
    for row in rows:
        if not isinstance(row, dict):
            raise BilingualJudgeError("évaluation non objet")
        item_id = row.get("item_id")
        if not isinstance(item_id, str):
            raise BilingualJudgeError("item_id d'évaluation invalide")
        if item_id in parsed:
            duplicates.append(item_id)
            continue
        if row.get("pmid") != expected_map.get(item_id):
            raise BilingualJudgeError(f"PMID incohérent pour {item_id}")
        options = row.get("options")
        if not isinstance(options, list):
            raise BilingualJudgeError(f"options absentes pour {item_id}")
        by_label = {}
        duplicate_labels = []
        for option in options:
            if not isinstance(option, dict) or option.get("label") not in LABELS:
                raise BilingualJudgeError(f"label invalide pour {item_id}")
            label = option["label"]
            if label in by_label:
                duplicate_labels.append(label)
                continue
            scores = {}
            for key in SCORE_KEYS:
                value = option.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                    raise BilingualJudgeError(f"{key} invalide pour {item_id}/{label}")
                scores[key] = value
            rationale = option.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise BilingualJudgeError(f"rationale invalide pour {item_id}/{label}")
            by_label[label] = {
                "label": label,
                **scores,
                "critical_errors": _string_list(
                    option.get("critical_errors"), "critical_errors", item_id, label
                ),
                "omissions": _string_list(option.get("omissions"), "omissions", item_id, label),
                "hallucinations": _string_list(
                    option.get("hallucinations"), "hallucinations", item_id, label
                ),
                "rationale": rationale.strip(),
            }
        if set(by_label) != set(LABELS) or duplicate_labels or len(options) != 2:
            raise BilingualJudgeError(f"bijection A/B invalide pour {item_id}")
        parsed[item_id] = {
            "item_id": item_id,
            "pmid": row["pmid"],
            "options": [by_label[label] for label in LABELS],
        }
    missing = sorted(set(expected_map) - set(parsed))
    extras = sorted(set(parsed) - set(expected_map))
    if missing or extras or duplicates or len(rows) != len(expected):
        raise BilingualJudgeError(
            f"bijection items invalide: missing={missing}, extras={extras}, duplicates={duplicates}"
        )
    return parsed


def _run_batch(
    items: list[dict],
    config: BilingualJudgeConfig,
    runner: JudgeRunner,
    repetition: int,
    batch_index: int,
) -> dict:
    prompt = build_prompt(items, repetition)
    started = time.monotonic()
    data, usage = runner(
        prompt,
        _SCHEMA,
        JUDGE_TIMEOUT_S,
        model=config.model,
        reasoning=config.reasoning,
    )
    return {
        "batch_index": batch_index,
        "item_ids": [item["item_id"] for item in items],
        "latency_s": time.monotonic() - started,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "usage": _usage_dict(usage),
        "evaluations": _validate_response(data, items),
    }


def _sum_usage(calls: list[dict]) -> dict[str, int]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {key: sum(call["usage"][key] for call in calls) for key in keys}
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def run_repetition(
    items: list[dict],
    config: BilingualJudgeConfig,
    runner: JudgeRunner,
    repetition: int,
) -> dict:
    started = time.monotonic()
    calls = []
    evaluations = {}
    batches = [
        items[offset : offset + config.batch_size]
        for offset in range(0, len(items), config.batch_size)
    ]
    for batch_index, batch in enumerate(batches, 1):
        call = _run_batch(batch, config, runner, repetition, batch_index)
        overlap = set(evaluations) & set(call["evaluations"])
        if overlap:
            raise BilingualJudgeError(f"items dupliqués entre lots: {sorted(overlap)}")
        evaluations.update(call["evaluations"])
        calls.append(call)
    expected_ids = [item["item_id"] for item in items]
    if set(evaluations) != set(expected_ids):
        raise BilingualJudgeError("réassemblage incomplet")
    return {
        "repetition": repetition,
        "latency_s": time.monotonic() - started,
        "tokens": _sum_usage(calls),
        "calls": [
            {key: value for key, value in call.items() if key != "evaluations"} for call in calls
        ],
        "evaluations": [evaluations[item_id] for item_id in expected_ids],
    }


def run_judge(
    blind_path: Path,
    out_path: Path,
    config: BilingualJudgeConfig,
    runner: JudgeRunner = run_codex,
) -> dict:
    items = load_blind_pool(blind_path)
    config_dict = asdict(config)
    output = {
        "schema_version": 1,
        "artifact_type": "translation_bilingual_judgement",
        "run_id": f"translation-bilingual-{time.time_ns()}",
        "complete": False,
        "expected_item_ids": [item["item_id"] for item in items],
        "source_blind_pool_sha256": hashlib.sha256(blind_path.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "machine_fingerprint": _machine_fingerprint(),
        "config": config_dict,
        "config_fingerprint": fingerprint(config_dict),
        "judge_contract_fingerprint": fingerprint({"prompt": _PROMPT_HEAD, "schema": _SCHEMA}),
        "proxy_only": True,
        "repetitions": [],
    }
    _write_atomic(out_path, output)
    for repetition in range(1, config.repetitions + 1):
        output["repetitions"].append(run_repetition(items, config, runner, repetition))
        _write_atomic(out_path, output)
    output["complete"] = True
    output["latency_s"] = sum(rep["latency_s"] for rep in output["repetitions"])
    output["tokens"] = {
        key: sum(rep["tokens"][key] for rep in output["repetitions"])
        for key in output["repetitions"][0]["tokens"]
    }
    _write_atomic(out_path, output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("blind_pool", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=settings.codex_model)
    parser.add_argument("--reasoning", default=settings.codex_reasoning)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--repetitions", type=int, choices=(2, 3), default=3)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = BilingualJudgeConfig(
            model=args.model,
            reasoning=args.reasoning,
            batch_size=args.batch_size,
            repetitions=args.repetitions,
        )
        output = run_judge(args.blind_pool, args.out, config)
    except BilingualJudgeError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    print(json.dumps({"items": len(output["expected_item_ids"]), "proxy_only": True}))


if __name__ == "__main__":
    main()
