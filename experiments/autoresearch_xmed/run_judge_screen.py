"""Harnais fixe pour évaluer le juge sur un pool JSONL aveugle.

Ce sidecar ne touche ni au retrieval, ni à PostgreSQL, ni à la traduction. Le
chemin ``baseline/head/1200/shards=1`` réutilise directement le prompt, le schéma
et le renderer du juge de production. Toutes les autres combinaisons sont des
variantes explicitement fingerprintées.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings
from app.services import codex_judge
from app.services.codex_cli import CodexUsage, run_codex
from experiments.autoresearch_xmed.manifest import fingerprint

JUDGE_TIMEOUT_S = 420
REQUIRED_FIELDS = (
    "item_id",
    "query_id",
    "query",
    "pmid",
    "title",
    "abstract",
    "journal",
    "pub_year",
    "evidence_level",
)
BLIND_FORBIDDEN_FIELDS = (
    "score",
    "relevance_pct",
    "reason",
    "source",
    "run_id",
    "retained_by",
    "judge_input_by",
    "top_k_by",
)

_COMPACT_PROMPT_HEAD = (
    "Évalue la pertinence clinique de chaque article pour la question ci-dessous, "
    "à partir du titre et du résumé. Respecte précisément population, intervention, "
    "comparateur et critère. Pour chaque PMID, rends score (0 hors sujet, 1 marginal, "
    "2 pertinent, 3 très pertinent), relevance_pct (0-100, cohérent avec le score) "
    "et reason (une phrase concrète de 25 mots maximum sur l'apport au médecin). "
    "Réponds uniquement avec le schéma JSON imposé, une entrée par PMID.\n\n"
    "Question clinique du médecin : {prm}\n\nArticles :\n"
)

JudgeRunner = Callable[..., tuple[dict, CodexUsage]]


class JudgeScreenError(ValueError):
    """Pool, configuration ou réponse du juge non démontrable."""


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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class JudgeConfig:
    model: str = settings.codex_model
    reasoning: str = settings.codex_reasoning
    batch_size: int = 50
    max_abstract_chars: int = codex_judge.MAX_ABSTRACT_CHARS
    abstract_mode: str = "head"
    prompt_style: str = "baseline"
    shards: int = 1
    repetitions: int = 1

    def __post_init__(self) -> None:
        for name in ("model", "reasoning"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise JudgeScreenError(f"{name} doit être une chaîne non vide")
        for name in ("batch_size", "max_abstract_chars", "repetitions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise JudgeScreenError(f"{name} doit être un entier strictement positif")
        if self.abstract_mode not in {"head", "head_tail"}:
            raise JudgeScreenError("abstract_mode doit valoir head ou head_tail")
        if self.prompt_style not in {"baseline", "compact"}:
            raise JudgeScreenError("prompt_style doit valoir baseline ou compact")
        if self.shards not in {1, 2} or isinstance(self.shards, bool):
            raise JudgeScreenError("shards doit valoir 1 ou 2")

    @property
    def exact_production_prompt(self) -> bool:
        return (
            self.abstract_mode == "head"
            and self.max_abstract_chars == codex_judge.MAX_ABSTRACT_CHARS
            and self.prompt_style == "baseline"
            and self.shards == 1
        )


def load_pool(path: Path) -> list[dict]:
    """Charge et valide tout le JSONL avant le premier appel au juge."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise JudgeScreenError(f"pool illisible: {path}") from exc
    items: list[dict] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise JudgeScreenError(f"JSON invalide ligne {line_number}") from exc
        if not isinstance(item, dict):
            raise JudgeScreenError(f"objet attendu ligne {line_number}")
        missing = [field for field in REQUIRED_FIELDS if field not in item]
        leaked = [field for field in BLIND_FORBIDDEN_FIELDS if field in item]
        if missing or leaked:
            raise JudgeScreenError(
                f"pool invalide ligne {line_number}: missing={missing}, leaked={leaked}"
            )
        if not isinstance(item["item_id"], str) or not item["item_id"].strip():
            raise JudgeScreenError(f"item_id invalide ligne {line_number}")
        if not isinstance(item["query_id"], str) or not item["query_id"].strip():
            raise JudgeScreenError(f"query_id invalide ligne {line_number}")
        if not isinstance(item["query"], str) or not item["query"].strip():
            raise JudgeScreenError(f"query invalide ligne {line_number}")
        if isinstance(item["pmid"], bool) or not isinstance(item["pmid"], int):
            raise JudgeScreenError(f"pmid invalide ligne {line_number}")
        for field in ("title", "abstract"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise JudgeScreenError(f"{field} absent ligne {line_number}")
        if item["journal"] is not None and not isinstance(item["journal"], str):
            raise JudgeScreenError(f"journal invalide ligne {line_number}")
        for field in ("pub_year", "evidence_level"):
            value = item[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise JudgeScreenError(f"{field} invalide ligne {line_number}")
        items.append(item)
    if not items:
        raise JudgeScreenError("pool vide")

    item_ids = [item["item_id"] for item in items]
    pairs = [(item["query_id"], item["pmid"]) for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise JudgeScreenError("item_id dupliqué")
    if len(pairs) != len(set(pairs)):
        raise JudgeScreenError("couple query_id/pmid dupliqué")
    queries: dict[str, str] = {}
    for item in items:
        previous = queries.setdefault(item["query_id"], item["query"])
        if previous != item["query"]:
            raise JudgeScreenError(f"questions incompatibles pour {item['query_id']}")
    return items


def group_by_query(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """Groupe sans trier : ordre des requêtes et des articles stable."""

    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["query_id"], []).append(item)
    return list(groups.items())


def _truncate_abstract(value: str, config: JudgeConfig) -> str:
    abstract = value.strip()
    limit = config.max_abstract_chars
    if len(abstract) <= limit:
        return abstract
    if config.abstract_mode == "head":
        return abstract[:limit] + "…"
    head_chars = (limit + 1) // 2
    tail_chars = limit // 2
    tail = abstract[-tail_chars:] if tail_chars else ""
    return abstract[:head_chars] + " … " + tail


def _render_variant(items: list[dict], config: JudgeConfig) -> str:
    blocks = []
    for item in items:
        facts = " · ".join(
            str(value)
            for value in (
                item.get("journal"),
                item.get("pub_year"),
                f"niveau de preuve {item['evidence_level']}"
                if item.get("evidence_level")
                else None,
            )
            if value
        )
        blocks.append(
            f"- PMID {item['pmid']}\n"
            + f"  Titre : {item['title']}\n"
            + (f"  Source : {facts}\n" if facts else "")
            + f"  Résumé : {_truncate_abstract(item['abstract'], config)}"
        )
    return "\n".join(blocks)


def build_prompt(query: str, items: list[dict], config: JudgeConfig) -> str:
    articles = [
        {
            key: item.get(key)
            for key in (
                "pmid",
                "title",
                "abstract",
                "journal",
                "pub_year",
                "evidence_level",
            )
        }
        for item in items
    ]
    if config.exact_production_prompt:
        return codex_judge._PROMPT_HEAD.format(prm=query) + codex_judge._render_articles(articles)
    head = codex_judge._PROMPT_HEAD if config.prompt_style == "baseline" else _COMPACT_PROMPT_HEAD
    return head.format(prm=query) + _render_variant(articles, config)


def _usage_dict(usage: object) -> dict[str, int]:
    if not hasattr(usage, "as_dict"):
        raise JudgeScreenError("usage tokens absent")
    value = usage.as_dict()
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {}
    for key in keys:
        token_count = value.get(key, 0)
        if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0:
            raise JudgeScreenError(f"usage {key} invalide")
        out[key] = token_count
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def _validate_judgements(data: dict, expected_pmids: list[int]) -> dict[int, dict]:
    rows = data.get("judgements") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise JudgeScreenError("réponse sans liste judgements")
    parsed: dict[int, dict] = {}
    duplicates = []
    for row in rows:
        if not isinstance(row, dict):
            raise JudgeScreenError("jugement non objet")
        pmid = row.get("pmid")
        if isinstance(pmid, bool) or not isinstance(pmid, int):
            raise JudgeScreenError("PMID de jugement invalide")
        if pmid in parsed:
            duplicates.append(pmid)
            continue
        score = row.get("score")
        relevance_pct = row.get("relevance_pct")
        reason = row.get("reason")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
            raise JudgeScreenError(f"score invalide pour PMID {pmid}")
        if (
            isinstance(relevance_pct, bool)
            or not isinstance(relevance_pct, int)
            or not 0 <= relevance_pct <= 100
        ):
            raise JudgeScreenError(f"relevance_pct invalide pour PMID {pmid}")
        if not isinstance(reason, str) or not reason.strip():
            raise JudgeScreenError(f"reason invalide pour PMID {pmid}")
        parsed[pmid] = {
            "pmid": pmid,
            "score": score,
            "relevance_pct": relevance_pct,
            "reason": reason.strip(),
        }
    expected = set(expected_pmids)
    observed = set(parsed)
    missing = sorted(expected - observed)
    extras = sorted(observed - expected)
    if duplicates or missing or extras or len(rows) != len(expected_pmids):
        raise JudgeScreenError(
            f"PMID incohérents: missing={missing}, extras={extras}, "
            f"duplicates={sorted(set(duplicates))}"
        )
    return parsed


def _run_shard(
    query: str,
    items: list[dict],
    config: JudgeConfig,
    runner: JudgeRunner,
    batch_index: int,
    shard_index: int,
) -> dict:
    prompt = build_prompt(query, items, config)
    expected_pmids = [item["pmid"] for item in items]
    started = time.monotonic()
    data, usage = runner(
        prompt,
        codex_judge._SCHEMA,
        JUDGE_TIMEOUT_S,
        model=config.model,
        reasoning=config.reasoning,
    )
    latency = time.monotonic() - started
    return {
        "batch_index": batch_index,
        "shard_index": shard_index,
        "pmids": expected_pmids,
        "latency_s": latency,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "usage": _usage_dict(usage),
        "judgements": _validate_judgements(data, expected_pmids),
    }


def _split_shards(items: list[dict], shards: int) -> list[list[dict]]:
    if shards == 1 or len(items) < 2:
        return [items]
    split = (len(items) + 1) // 2
    return [items[:split], items[split:]]


def _sum_usage(calls: list[dict]) -> dict[str, int]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {key: sum(call["usage"][key] for call in calls) for key in keys}
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def run_query(
    query_id: str,
    items: list[dict],
    config: JudgeConfig,
    runner: JudgeRunner = run_codex,
) -> dict:
    query = items[0]["query"]
    expected_pmids = [item["pmid"] for item in items]
    repetitions = []
    for repetition in range(1, config.repetitions + 1):
        repetition_started = time.monotonic()
        calls = []
        judgements: dict[int, dict] = {}
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
                            query,
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
                shard_results = [_run_shard(query, shards[0], config, runner, batch_index, 1)]
            for result in shard_results:
                overlap = set(judgements) & set(result["judgements"])
                if overlap:
                    raise JudgeScreenError(f"PMID dupliqués entre shards: {sorted(overlap)}")
                judgements.update(result["judgements"])
                calls.append(result)

        missing = sorted(set(expected_pmids) - set(judgements))
        extras = sorted(set(judgements) - set(expected_pmids))
        if missing or extras or len(judgements) != len(expected_pmids):
            raise JudgeScreenError(f"réassemblage incomplet: missing={missing}, extras={extras}")
        repetitions.append(
            {
                "repetition": repetition,
                "latency_s": time.monotonic() - repetition_started,
                "tokens": _sum_usage(calls),
                "prompt_hashes": [call["prompt_sha256"] for call in calls],
                "calls": [
                    {key: value for key, value in call.items() if key != "judgements"}
                    for call in calls
                ],
                "judgements": [judgements[pmid] for pmid in expected_pmids],
            }
        )
    return {
        "query_id": query_id,
        "query": query,
        "item_ids": [item["item_id"] for item in items],
        "pmids": expected_pmids,
        "config": asdict(config),
        "repetitions": repetitions,
        "tokens": {
            key: sum(rep["tokens"][key] for rep in repetitions) for key in repetitions[0]["tokens"]
        },
        "error": None,
    }


def run_screen(
    pool_path: Path,
    out_path: Path,
    config: JudgeConfig,
    runner: JudgeRunner = run_codex,
) -> dict:
    items = load_pool(pool_path)
    groups = group_by_query(items)
    config_dict = asdict(config)
    output = {
        "schema_version": 1,
        "artifact_type": "judge_screen",
        "run_id": f"judge-screen-{time.time_ns()}",
        "complete": False,
        "expected_query_ids": [query_id for query_id, _ in groups],
        "source_pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "machine_fingerprint": _machine_fingerprint(),
        "config": config_dict,
        "config_fingerprint": fingerprint(config_dict),
        "exact_production_prompt": config.exact_production_prompt,
        "calls": {"database": False, "retrieval": False, "translate": False},
        "cases": [],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(out_path, output)
    for query_id, query_items in groups:
        output["cases"].append(run_query(query_id, query_items, config, runner))
        _write_atomic(out_path, output)
    output["complete"] = True
    _write_atomic(out_path, output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=settings.codex_model)
    parser.add_argument("--reasoning", default=settings.codex_reasoning)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-abstract-chars", type=int, default=codex_judge.MAX_ABSTRACT_CHARS)
    parser.add_argument("--abstract-mode", choices=("head", "head_tail"), default="head")
    parser.add_argument("--prompt-style", choices=("baseline", "compact"), default="baseline")
    parser.add_argument("--shards", type=int, choices=(1, 2), default=1)
    parser.add_argument("--repetitions", type=int, default=1)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = JudgeConfig(
            model=args.model,
            reasoning=args.reasoning,
            batch_size=args.batch_size,
            max_abstract_chars=args.max_abstract_chars,
            abstract_mode=args.abstract_mode,
            prompt_style=args.prompt_style,
            shards=args.shards,
            repetitions=args.repetitions,
        )
        output = run_screen(args.pool, args.out, config)
    except JudgeScreenError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    total_tokens = sum(case["tokens"]["total_tokens"] for case in output["cases"])
    print(
        json.dumps(
            {"queries": len(output["cases"]), "total_tokens": total_tokens},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
