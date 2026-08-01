"""Score non compensatoire d'un jugement bilingue aveugle (proxy uniquement)."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

from experiments.autoresearch_xmed.run_translation_bilingual_judge import LABELS, SCORE_KEYS

EPSILON = 1e-12
GLOBAL_NONINFERIORITY_MARGIN = 0.15
STRATUM_NONINFERIORITY_MARGIN = 0.25
WORST_QUARTILE_NONINFERIORITY_MARGIN = 0.50
CANDIDATE_ABSOLUTE_FLOOR = 3.0


class TranslationProxyScoreError(ValueError):
    """Clé privée ou jugement incomplet/incohérent."""


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationProxyScoreError(f"JSON illisible: {path}") from exc
    if not isinstance(value, dict):
        raise TranslationProxyScoreError(f"objet JSON attendu: {path}")
    return value


def _option_map(evaluation: dict, item_id: str) -> dict[str, dict]:
    options = evaluation.get("options")
    if not isinstance(options, list) or len(options) != 2:
        raise TranslationProxyScoreError(f"options invalides pour {item_id}")
    parsed = {}
    for option in options:
        if not isinstance(option, dict) or option.get("label") not in LABELS:
            raise TranslationProxyScoreError(f"label invalide pour {item_id}")
        label = option["label"]
        if label in parsed:
            raise TranslationProxyScoreError(f"label dupliqué pour {item_id}")
        for key in SCORE_KEYS:
            score = option.get(key)
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise TranslationProxyScoreError(f"{key} invalide pour {item_id}/{label}")
        for key in ("critical_errors", "omissions", "hallucinations"):
            values = option.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise TranslationProxyScoreError(f"{key} invalide pour {item_id}/{label}")
        parsed[label] = option
    if set(parsed) != set(LABELS):
        raise TranslationProxyScoreError(f"bijection A/B invalide pour {item_id}")
    return parsed


def _stratum_names(value: dict) -> list[str]:
    if not isinstance(value, dict):
        raise TranslationProxyScoreError("strate privée absente")
    required = ("length", "risk", "combined")
    if any(not isinstance(value.get(key), str) or not value[key] for key in required):
        raise TranslationProxyScoreError("strate privée invalide")
    return [f"length={value['length']}", f"risk={value['risk']}", f"combined={value['combined']}"]


def _below_margin(delta: float, margin: float) -> bool:
    return delta < -margin - EPSILON


def score(key: dict, judgement: dict) -> dict:
    if key.get("artifact_type") != "translation_comparison_private_key":
        raise TranslationProxyScoreError("clé de comparaison invalide")
    if judgement.get("artifact_type") != "translation_bilingual_judgement":
        raise TranslationProxyScoreError("jugement bilingue invalide")
    if judgement.get("complete") is not True or judgement.get("proxy_only") is not True:
        raise TranslationProxyScoreError("jugement incomplet ou non déclaré proxy")
    if any(
        not judgement.get(key)
        for key in (
            "config_fingerprint",
            "judge_contract_fingerprint",
            "runner_sha256",
            "machine_fingerprint",
        )
    ):
        raise TranslationProxyScoreError("fingerprints du juge absents")
    if judgement.get("source_blind_pool_sha256") != key.get("blind_pool_sha256"):
        raise TranslationProxyScoreError("pool aveugle différent de la clé privée")

    private_items = key.get("items")
    if not isinstance(private_items, dict) or not private_items:
        raise TranslationProxyScoreError("items privés absents")
    expected_ids = list(private_items)
    if judgement.get("expected_item_ids") != expected_ids:
        raise TranslationProxyScoreError("couverture item_id incompatible")
    sources = key.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"pool", "baseline", "candidate"}:
        raise TranslationProxyScoreError("provenance privée absente")
    if sources["pool"].get("sha256") != key.get("source_pool_sha256"):
        raise TranslationProxyScoreError("fingerprint du pool source incohérent")
    for system in ("baseline", "candidate"):
        source = sources[system]
        if not isinstance(source, dict) or any(
            not source.get(field)
            for field in ("sha256", "config_fingerprint", "runner_sha256", "repetition")
        ):
            raise TranslationProxyScoreError(f"provenance {system} incomplète")
    repetitions = judgement.get("repetitions")
    if not isinstance(repetitions, list) or len(repetitions) not in {2, 3}:
        raise TranslationProxyScoreError("deux ou trois répétitions sont requises")

    values = {
        item_id: {
            system: {
                **{key: [] for key in SCORE_KEYS},
                "critical_errors": [],
                "omissions": [],
                "hallucinations": [],
            }
            for system in ("baseline", "candidate")
        }
        for item_id in expected_ids
    }
    for repetition_index, repetition in enumerate(repetitions, 1):
        if repetition.get("repetition") != repetition_index:
            raise TranslationProxyScoreError("numérotation des répétitions incohérente")
        evaluations = repetition.get("evaluations") if isinstance(repetition, dict) else None
        if not isinstance(evaluations, list):
            raise TranslationProxyScoreError(f"evaluations absentes répétition {repetition_index}")
        parsed = {}
        for evaluation in evaluations:
            if not isinstance(evaluation, dict) or not isinstance(evaluation.get("item_id"), str):
                raise TranslationProxyScoreError("évaluation invalide")
            item_id = evaluation["item_id"]
            if item_id in parsed:
                raise TranslationProxyScoreError(f"item dupliqué: {item_id}")
            if item_id not in private_items or evaluation.get("pmid") != private_items[item_id].get(
                "pmid"
            ):
                raise TranslationProxyScoreError(f"provenance PMID invalide pour {item_id}")
            parsed[item_id] = _option_map(evaluation, item_id)
        if set(parsed) != set(expected_ids) or len(evaluations) != len(expected_ids):
            raise TranslationProxyScoreError(f"bijection invalide répétition {repetition_index}")
        for item_id in expected_ids:
            labels = private_items[item_id].get("labels")
            if not isinstance(labels, dict) or set(labels) != {"baseline", "candidate"}:
                raise TranslationProxyScoreError(f"clé labels invalide pour {item_id}")
            if set(labels.values()) != set(LABELS):
                raise TranslationProxyScoreError(f"démasquage non bijectif pour {item_id}")
            for system in ("baseline", "candidate"):
                option = parsed[item_id][labels[system]]
                for metric in SCORE_KEYS:
                    values[item_id][system][metric].append(option[metric])
                for category in ("critical_errors", "omissions", "hallucinations"):
                    values[item_id][system][category].append(option[category])

    per_item = {}
    critical_failures = {}
    absolute_floor_failures = {}
    diagnostic_counts = {
        system: {category: 0 for category in ("omissions", "hallucinations")}
        for system in ("baseline", "candidate")
    }
    for item_id in expected_ids:
        systems = {}
        for system in ("baseline", "candidate"):
            state = values[item_id][system]
            systems[system] = {
                **{metric: statistics.fmean(state[metric]) for metric in SCORE_KEYS},
                "critical_error_count": sum(len(entries) for entries in state["critical_errors"]),
                "omission_count": sum(len(entries) for entries in state["omissions"]),
                "hallucination_count": sum(len(entries) for entries in state["hallucinations"]),
            }
            for category in ("omissions", "hallucinations"):
                diagnostic_counts[system][category] += systems[system][f"{category[:-1]}_count"]
        deltas = {
            metric: systems["candidate"][metric] - systems["baseline"][metric]
            for metric in SCORE_KEYS
        }
        if (
            systems["candidate"]["critical_error_count"]
            > systems["baseline"]["critical_error_count"]
        ):
            critical_failures[item_id] = {
                "baseline": systems["baseline"]["critical_error_count"],
                "candidate": systems["candidate"]["critical_error_count"],
            }
        below_floor = [
            metric
            for metric in SCORE_KEYS
            if systems["candidate"][metric] < CANDIDATE_ABSOLUTE_FLOOR - EPSILON
        ]
        if below_floor:
            absolute_floor_failures[item_id] = below_floor
        per_item[item_id] = {
            "pmid": private_items[item_id]["pmid"],
            "stratum": private_items[item_id]["stratum"],
            "systems": systems,
            "deltas": deltas,
        }

    global_deltas = {
        metric: statistics.fmean(item["deltas"][metric] for item in per_item.values())
        for metric in SCORE_KEYS
    }
    global_failures = [
        metric
        for metric, delta in global_deltas.items()
        if _below_margin(delta, GLOBAL_NONINFERIORITY_MARGIN)
    ]
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for item_id, item in per_item.items():
        for stratum in _stratum_names(item["stratum"]):
            by_stratum[stratum].append(per_item[item_id])
    stratum_deltas = {
        stratum: {
            metric: statistics.fmean(item["deltas"][metric] for item in items)
            for metric in SCORE_KEYS
        }
        for stratum, items in sorted(by_stratum.items())
    }
    stratum_failures = {
        stratum: [
            metric
            for metric, delta in deltas.items()
            if _below_margin(delta, STRATUM_NONINFERIORITY_MARGIN)
        ]
        for stratum, deltas in stratum_deltas.items()
    }
    stratum_failures = {key: value for key, value in stratum_failures.items() if value}

    quartile_n = max(1, math.ceil(len(per_item) / 4))
    worst_quartile_deltas = {
        metric: statistics.fmean(
            sorted(item["deltas"][metric] for item in per_item.values())[:quartile_n]
        )
        for metric in SCORE_KEYS
    }
    worst_quartile_failures = [
        metric
        for metric, delta in worst_quartile_deltas.items()
        if _below_margin(delta, WORST_QUARTILE_NONINFERIORITY_MARGIN)
    ]
    baseline_critical = sum(
        item["systems"]["baseline"]["critical_error_count"] for item in per_item.values()
    )
    candidate_critical = sum(
        item["systems"]["candidate"]["critical_error_count"] for item in per_item.values()
    )
    critical_global_failure = candidate_critical > baseline_critical
    passed = not any(
        (
            critical_failures,
            critical_global_failure,
            absolute_floor_failures,
            global_failures,
            stratum_failures,
            worst_quartile_failures,
        )
    )
    return {
        "schema_version": 1,
        "artifact_type": "translation_proxy_score",
        "verdict": "keep_proxy" if passed else "reject_proxy",
        "proxy_only": True,
        "clinical_truth": False,
        "predeclared_policy": {
            "score_scale": [1, 5],
            "global_noninferiority_margin_points": GLOBAL_NONINFERIORITY_MARGIN,
            "stratum_noninferiority_margin_points": STRATUM_NONINFERIORITY_MARGIN,
            "worst_quartile_noninferiority_margin_points": (WORST_QUARTILE_NONINFERIORITY_MARGIN),
            "candidate_absolute_floor": CANDIDATE_ABSOLUTE_FLOOR,
            "critical_error_margin": 0,
        },
        "source_blind_pool_sha256": key["blind_pool_sha256"],
        "source_pool_sha256": key.get("source_pool_sha256"),
        "judge_config_fingerprint": judgement["config_fingerprint"],
        "judge_contract_fingerprint": judgement["judge_contract_fingerprint"],
        "gates": {
            "critical_errors": {
                "passed": not critical_failures and not critical_global_failure,
                "baseline_total": baseline_critical,
                "candidate_total": candidate_critical,
                "per_item_failures": critical_failures,
            },
            "global_noninferiority": {
                "passed": not global_failures,
                "margin_points": GLOBAL_NONINFERIORITY_MARGIN,
                "deltas": global_deltas,
                "failures": global_failures,
            },
            "stratum_noninferiority": {
                "passed": not stratum_failures,
                "margin_points": STRATUM_NONINFERIORITY_MARGIN,
                "deltas": stratum_deltas,
                "failures": stratum_failures,
            },
            "worst_quartile_noninferiority": {
                "passed": not worst_quartile_failures,
                "margin_points": WORST_QUARTILE_NONINFERIORITY_MARGIN,
                "size": quartile_n,
                "deltas": worst_quartile_deltas,
                "failures": worst_quartile_failures,
            },
            "candidate_absolute_floor": {
                "passed": not absolute_floor_failures,
                "floor": CANDIDATE_ABSOLUTE_FLOOR,
                "per_item_failures": absolute_floor_failures,
            },
        },
        "diagnostics": {
            "omissions_hallucinations": diagnostic_counts,
            "per_item": per_item,
            "disclaimer": "Proxy automatisé bilingue; validation humaine médicale requise.",
        },
    }


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("key", type=Path)
    parser.add_argument("judgement", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = score(_load(args.key), _load(args.judgement))
    except TranslationProxyScoreError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        _write_atomic(args.out, result)
    print(rendered, end="")


if __name__ == "__main__":
    main()
