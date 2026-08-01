"""Score E2E warm du cache exact à partir de traces live complètes.

Le calcul est un contrefactuel intra-trace : la sortie du query-builder étant
byte-identique sur hit, on conserve littéralement tous les candidats, jugements et
traductions capturés, puis on remplace seulement la durée et les tokens de cette
phase par le pire hit mesuré. Cela isole l'effet causal du cache de la variance LLM
des phases aval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from experiments.autoresearch_xmed.score import MIN_EFFICIENCY_GAIN, load_json

MAX_REGRESSION = 0.05


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _phase_duration(case: dict, start: str, end: str) -> float:
    elapsed = {row["phase"]: float(row["elapsed_s"]) for row in case.get("phases", [])}
    if start not in elapsed or end not in elapsed or elapsed[end] < elapsed[start]:
        raise ValueError(f"phase {start}→{end} absente/invalide pour {case.get('query_id')}")
    return elapsed[end] - elapsed[start]


def _summary(run: dict, hit_latency_s: float) -> dict:
    baseline_usable: list[float] = []
    candidate_usable: list[float] = []
    baseline_complete: list[float] = []
    candidate_complete: list[float] = []
    baseline_tokens: list[int] = []
    candidate_tokens: list[int] = []
    query_durations: list[float] = []

    for case in run["cases"]:
        if case.get("error"):
            raise ValueError(f"cas en erreur: {case['query_id']}")
        duration = _phase_duration(case, "codex", "codex_done")
        query_tokens = int(case["tokens"]["query"])
        total_tokens = int(case["tokens"]["total"])
        if query_tokens < 0 or query_tokens > total_tokens:
            raise ValueError(f"tokens query invalides pour {case['query_id']}")
        query_durations.append(duration)
        baseline_usable.append(float(case["usable_latency_s"]))
        candidate_usable.append(float(case["usable_latency_s"]) - duration + hit_latency_s)
        baseline_complete.append(float(case["complete_latency_s"]))
        candidate_complete.append(float(case["complete_latency_s"]) - duration + hit_latency_s)
        baseline_tokens.append(total_tokens)
        candidate_tokens.append(total_tokens - query_tokens)

    def metrics(usable: list[float], complete: list[float], tokens: list[int]) -> dict:
        return {
            "usable_p50_s": statistics.median(usable),
            "usable_p95_s": _quantile(usable, 0.95),
            "complete_p50_s": statistics.median(complete),
            "complete_p95_s": _quantile(complete, 0.95),
            "tokens_mean": statistics.fmean(tokens),
        }

    baseline = metrics(baseline_usable, baseline_complete, baseline_tokens)
    candidate = metrics(candidate_usable, candidate_complete, candidate_tokens)
    gains = {
        key.replace("_s", "") + "_gain": (baseline[key] - candidate[key]) / baseline[key]
        for key in baseline
    }
    improved = any(value >= MIN_EFFICIENCY_GAIN for value in gains.values())
    regressed = any(value < -MAX_REGRESSION for value in gains.values())
    return {
        "baseline": baseline,
        "warm_candidate": candidate,
        "performance": gains,
        "query_builder_phase": {
            "p50_s": statistics.median(query_durations),
            "p95_s": _quantile(query_durations, 0.95),
            "cache_hit_s": hit_latency_s,
        },
        "quality_identity": {
            "passed": True,
            "reason": "seule la phase query-builder est remplacée par sa sortie exacte en cache",
        },
        "efficiency_passed": improved and not regressed,
    }


def _load_cache_evidence(paths: list[Path]) -> tuple[list[dict], float]:
    evidence = []
    hit_latencies = []
    for path in paths:
        value = json.loads(path.read_text())
        if value.get("schema_version") != 1 or value.get("exact_output") is not True:
            raise ValueError(f"preuve cache invalide: {path}")
        hits = [row for row in value.get("observations", []) if row.get("cache_hit") is True]
        misses = [row for row in value.get("observations", []) if row.get("cache_hit") is False]
        if len(hits) != 1 or len(misses) != 1:
            raise ValueError(f"preuve cold/hit incomplète: {path}")
        hit = hits[0]
        if int(hit.get("billed_tokens", -1)) != 0 or float(hit.get("elapsed_s", -1)) < 0:
            raise ValueError(f"hit cache invalide: {path}")
        hit_latencies.append(float(hit["elapsed_s"]))
        evidence.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "question": value.get("question"),
                "hit_latency_s": float(hit["elapsed_s"]),
                "cold_tokens": int(misses[0]["billed_tokens"]),
            }
        )
    return evidence, max(hit_latencies)


def score(baseline_paths: list[Path], cache_paths: list[Path]) -> dict:
    cache_evidence, conservative_hit_latency = _load_cache_evidence(cache_paths)
    baselines = [(path, load_json(path)) for path in baseline_paths]
    identities = {
        (
            run.get("protocol_fingerprint"),
            run.get("corpus_fingerprint"),
            run.get("machine_fingerprint"),
        )
        for _, run in baselines
    }
    if len(identities) != 1:
        raise ValueError("baselines non comparables")
    if any(
        run.get("run_role") != "baseline"
        or run.get("benchmark_tier") != "benchmark_full"
        or len(run["cases"]) != 18
        for _, run in baselines
    ):
        raise ValueError("une baseline live full de 18 cas est requise")

    runs = []
    for path, run in baselines:
        result = _summary(run, conservative_hit_latency)
        result["baseline_path"] = str(path)
        result["baseline_sha256"] = _sha256(path)
        runs.append(result)
    passed = all(row["quality_identity"]["passed"] and row["efficiency_passed"] for row in runs)
    return {
        "schema_version": 1,
        "kind": "exact_query_builder_cache_warm_counterfactual",
        "scope": "requête utilisateur byte-identique déjà présente dans le cache",
        "verdict": "keep_warm" if passed else "reject",
        "method": (
            "contrefactuel intra-trace; sorties aval inchangées; pire latence de hit "
            "observée ajoutée à chaque cas"
        ),
        "cache_evidence": cache_evidence,
        "conservative_hit_latency_s": conservative_hit_latency,
        "runs": runs,
        "limitations": [
            "aucun gain sur un miss froid",
            "ne met en cache ni résultats PubMed, ni candidats, ni jugements, ni traductions",
            "ne démontre pas le taux de hit du trafic réel",
            "sidecar expérimental non branché à la production",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, action="append", required=True)
    parser.add_argument("--cache-artifact", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = score(args.baseline, args.cache_artifact)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
