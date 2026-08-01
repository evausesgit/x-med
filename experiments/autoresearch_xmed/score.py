"""Portes non compensatoires du benchmark autoresearch X-Med."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from experiments.autoresearch_xmed.manifest import validate_variant_identity

QUALITY_KEYS = ("ndcg@10", "precision@10", "recall@50")
DIVERSITY_KEYS = (
    "journal_entropy@10",
    "source_entropy@10",
    "year_entropy@10",
    "journal_coverage@10",
    "source_coverage@10",
    "year_coverage@10",
)
TRANSLATION_SCORE_KEYS = ("fidelity", "terminology", "readability")
TRANSLATION_BEHAVIOR_KEYS = ("reuse_hydrated_translation_input",)
COMPARISON_EPSILON = 1e-12
MIN_EFFICIENCY_GAIN = 0.10
NORMALIZED_QUALITY_MARGIN = 0.02
DIVERSITY_RELATIVE_MARGIN = 0.02
DIVERSITY_ENTROPY_MIN_MARGIN = 0.05
LIVE_COVERAGE_MARGIN = 0.02
NDCG_WORST_QUARTILE_FLOOR = -0.05
NDCG_BOOTSTRAP_LOWER_FLOOR = -0.02
DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR = -0.10
LIVE_COVERAGE_WORST_QUARTILE_FLOOR = -0.10


class InvalidArtifact(ValueError):
    pass


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise InvalidArtifact(f"artefact invalide: {path}")
    ids = [case.get("query_id") for case in data["cases"]]
    if None in ids or len(ids) != len(set(ids)):
        raise InvalidArtifact(f"query_id absent ou dupliqué: {path}")
    if data.get("run_kind"):
        if data.get("complete") is not True:
            raise InvalidArtifact(f"run incomplet: {path}")
        expected = [str(value) for value in data.get("expected_query_ids", [])]
        if not expected or expected != [str(value) for value in ids]:
            raise InvalidArtifact(f"couverture de requêtes incomplète: {path}")
        for key in ("database", "corpus_scope", "corpus_fingerprint", "machine_fingerprint"):
            if not data.get(key):
                raise InvalidArtifact(f"{key} absent: {path}")
        protocol_fingerprint = data.get("protocol_fingerprint")
        if protocol_fingerprint:
            if data.get("benchmark_tier") not in {"smoke_recent", "benchmark_full"}:
                raise InvalidArtifact(f"benchmark_tier v2 invalide: {path}")
            if not validate_variant_identity(data):
                raise InvalidArtifact(f"identité de variante invalide: {path}")
            if data["benchmark_tier"] == "benchmark_full":
                canonical_ids = [f"q{index:02d}" for index in range(1, 19)]
                if data.get("corpus_scope") != "full" or expected != canonical_ids:
                    raise InvalidArtifact(f"baseline full non canonique: {path}")
            elif data.get("corpus_scope") != "recent":
                raise InvalidArtifact(f"smoke v2 hors clone récent: {path}")
        else:
            if data.get("corpus_scope") != "recent" or not data.get("manifest_fingerprint"):
                raise InvalidArtifact(f"legacy autorisé uniquement pour smoke récent: {path}")
            if data.get("benchmark_tier") not in (None, "legacy_smoke_recent"):
                raise InvalidArtifact(f"tier legacy invalide: {path}")
        for case in data["cases"]:
            latency_keys = ("latency_s", "usable_latency_s", "complete_latency_s")
            for key in latency_keys:
                value = case.get(key)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise InvalidArtifact(f"{key} invalide pour {case.get('query_id')}: {path}")
            total_tokens = case.get("tokens", {}).get("total")
            if (
                not isinstance(total_tokens, int)
                or isinstance(total_tokens, bool)
                or total_tokens < 0
            ):
                raise InvalidArtifact(f"tokens invalides pour {case.get('query_id')}: {path}")
            results = case.get("results")
            if not isinstance(results, list):
                raise InvalidArtifact(f"results absent pour {case.get('query_id')}: {path}")
            pmids = [row.get("pmid") for row in results]
            if None in pmids or len(pmids) != len(set(pmids)):
                raise InvalidArtifact(
                    f"PMID absent ou dupliqué pour {case.get('query_id')}: {path}"
                )
            if not case.get("error"):
                for key in (
                    "judge_input_sha256",
                    "judge_prompt_sha256",
                    "translate_prompt_sha256",
                ):
                    if not case.get(key):
                        raise InvalidArtifact(f"{key} absent pour {case.get('query_id')}: {path}")
    return data


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qrels_payload(value: object) -> tuple[dict[str, dict[str, int]], bool | None]:
    if not isinstance(value, dict):
        raise InvalidArtifact("qrels non objet")
    if "qrels" not in value:
        return value, None
    if value.get("schema_version") != 1 or not isinstance(value.get("qrels"), dict):
        raise InvalidArtifact("artefact qrels v1 invalide")
    proxy = value.get("proxy")
    if not isinstance(proxy, bool):
        raise InvalidArtifact("statut proxy des qrels absent")
    return value["qrels"], proxy


def _write_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (pos - low))


def entropy(values: list[Any]) -> float:
    present = [value for value in values if value not in (None, "")]
    if len(present) < 2:
        return 0.0
    counts = Counter(present)
    total = len(present)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def result_signature(result: dict) -> tuple:
    """Champs visibles et sémantiques dont l'identité garantit la fidélité."""
    return (
        result.get("pmid"),
        result.get("score"),
        result.get("relevance_pct"),
        result.get("reason"),
        result.get("source"),
        result.get("title"),
        result.get("abstract"),
        result.get("title_fr"),
        result.get("abstract_fr"),
        result.get("journal"),
        result.get("pub_year"),
        result.get("evidence_level"),
        result.get("doi"),
        result.get("in_db"),
    )


def exact_fidelity(base_case: dict, cand_case: dict) -> bool:
    base_results = [result_signature(row) for row in base_case.get("results", [])]
    cand_results = [result_signature(row) for row in cand_case.get("results", [])]
    required_hashes = (
        "judge_input_sha256",
        "judge_prompt_sha256",
        "translate_prompt_sha256",
    )
    return (
        all(base_case.get(key) and cand_case.get(key) for key in required_hashes)
        and base_case.get("judge_input_sha256") == cand_case.get("judge_input_sha256")
        and base_case.get("judge_prompt_sha256") == cand_case.get("judge_prompt_sha256")
        and base_case.get("translate_prompt_sha256") == cand_case.get("translate_prompt_sha256")
        and base_results == cand_results
    )


def _translation_map(case: dict) -> dict[str, tuple]:
    return {
        str(row.get("pmid")): (row.get("title_fr"), row.get("abstract_fr"))
        for row in case.get("results", [])
        if row.get("title_fr") or row.get("abstract_fr")
    }


def _same_translation_contract(baseline: dict, candidate: dict) -> bool:
    """Reconnaît la variance d'un traducteur inchangé dans deux runs v2.

    Le protocole fingerprinté couvre le prompt, le modèle configuré, le renderer et
    le runner. Les knobs qui changent effectivement l'entrée du traducteur restent
    exclus : leurs sorties différentes exigent toujours une évaluation bilingue.
    """

    protocol = baseline.get("protocol_fingerprint")
    if (
        not isinstance(protocol, str)
        or not protocol
        or candidate.get("protocol_fingerprint") != protocol
    ):
        return False
    base_config = baseline.get("variant_config")
    cand_config = candidate.get("variant_config")
    if not isinstance(base_config, dict) or not isinstance(cand_config, dict):
        return False
    return all(
        isinstance(base_config.get(key), bool)
        and isinstance(cand_config.get(key), bool)
        and base_config[key] == cand_config[key]
        for key in TRANSLATION_BEHAVIOR_KEYS
    )


def _translation_missing(case: dict) -> int:
    """Compte les traductions absentes dans la fenêtre de production (cap=20)."""

    eligible = [row for row in case.get("results", []) if (row.get("abstract") or "").strip()][:20]
    translated = sum(bool((row.get("abstract_fr") or "").strip()) for row in eligible)
    return len(eligible) - translated


def _valid_translation_score(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    for key in TRANSLATION_SCORE_KEYS:
        score = value.get(key)
        if not isinstance(score, (int, float)) or not math.isfinite(score):
            return False
        if not 0 <= float(score) <= 4:
            return False
    critical = value.get("critical_errors")
    return isinstance(critical, int) and not isinstance(critical, bool) and critical >= 0


def dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades[:k]))


def quality(case: dict, qrels: dict[str, int]) -> dict[str, float]:
    results = case.get("results", [])
    grades = [int(qrels.get(str(row.get("pmid")), 0)) for row in results]
    ideal = sorted((int(value) for value in qrels.values()), reverse=True)
    ideal_dcg = dcg(ideal, 10)
    relevant_total = sum(1 for value in qrels.values() if int(value) >= 2)
    relevant_50 = sum(1 for grade in grades[:50] if grade >= 2)
    return {
        "ndcg@10": dcg(grades, 10) / ideal_dcg if ideal_dcg else 0.0,
        "precision@10": sum(1 for grade in grades[:10] if grade >= 2) / 10.0,
        "recall@50": relevant_50 / relevant_total if relevant_total else 0.0,
    }


def diversity(case: dict, qrels: dict[str, int] | None = None) -> dict[str, float]:
    top = case.get("results", [])[:10]
    if qrels is not None:
        # En porte clinique, un hors-sujet ne doit jamais pouvoir « améliorer » la
        # diversité. On ne mesure donc que les résultats réellement pertinents.
        top = [row for row in top if int(qrels.get(str(row.get("pmid")), 0)) >= 2]
    values = {
        "journal": [row.get("journal") for row in top],
        "source": [row.get("source") for row in top],
        "year": [row.get("pub_year") for row in top],
    }
    return {
        **{f"{key}_entropy@10": entropy(rows) for key, rows in values.items()},
        **{
            f"{key}_coverage@10": sum(value not in (None, "") for value in rows) / 10.0
            for key, rows in values.items()
        },
    }


def aggregate(run: dict, qrels: dict[str, dict[str, int]] | None = None) -> dict:
    cases = run["cases"]
    latency = [float(case.get("latency_s", 0.0)) for case in cases]
    usable = [float(case.get("usable_latency_s", case.get("latency_s", 0.0))) for case in cases]
    complete = [float(case.get("complete_latency_s", case.get("latency_s", 0.0))) for case in cases]
    tokens = [int(case.get("tokens", {}).get("total", 0)) for case in cases]
    errors = sum(bool(case.get("error")) for case in cases)
    out = {
        "cases": len(cases),
        "errors": errors,
        "error_rate": errors / len(cases) if cases else 0.0,
        "latency_p50_s": quantile(latency, 0.5),
        "latency_p95_s": quantile(latency, 0.95),
        "usable_p50_s": quantile(usable, 0.5),
        "usable_p95_s": quantile(usable, 0.95),
        "complete_p50_s": quantile(complete, 0.5),
        "complete_p95_s": quantile(complete, 0.95),
        "tokens_mean": statistics.fmean(tokens) if tokens else 0.0,
    }
    div_rows = [
        diversity(case, qrels.get(str(case["query_id"]), {}) if qrels is not None else None)
        for case in cases
    ]
    out.update(
        {
            key: statistics.fmean(row[key] for row in div_rows) if div_rows else 0.0
            for key in DIVERSITY_KEYS
        }
    )
    if qrels is not None:
        rows = [quality(case, qrels.get(str(case["query_id"]), {})) for case in cases]
        out.update(
            {
                key: statistics.fmean(row[key] for row in rows) if rows else 0.0
                for key in QUALITY_KEYS
            }
        )
    return out


def _case_map(run: dict) -> dict[str, dict]:
    return {str(case["query_id"]): case for case in run["cases"]}


def _run_kind(run: dict) -> str:
    if value := run.get("run_kind"):
        return str(value)
    run_id = str(run.get("run_id", ""))
    if run_id.startswith("baseline-"):
        return "live"
    if run_id.startswith("replay-"):
        return "replay"
    return "unspecified"


def _qrels_gaps(
    base_cases: dict[str, dict],
    cand_cases: dict[str, dict],
    qrels: dict[str, dict[str, int]],
) -> dict[str, dict]:
    """Refuse les pools partiels : un PMID non annoté ne vaut jamais implicitement 0."""
    gaps = {}
    for qid in base_cases:
        labels = qrels.get(qid, {})
        pooled = {
            str(row.get("pmid"))
            for case in (base_cases[qid], cand_cases[qid])
            for row in case.get("results", [])[:50]
        }
        missing = sorted(pooled - set(labels))
        if missing or not any(int(value) >= 2 for value in labels.values()):
            gaps[qid] = {
                "missing_pmids": missing,
                "has_relevant": any(int(value) >= 2 for value in labels.values()),
            }
    return gaps


def _stratum(case: dict) -> str:
    """Strate de difficulté fixée dans `queries.jsonl` avant les expériences."""
    return str(case.get("width") or "unstratified")


def _quality_margin(_key: str, _baseline: float) -> float:
    return NORMALIZED_QUALITY_MARGIN


def _diversity_margin(key: str, baseline: float) -> float:
    if "entropy" in key:
        return max(DIVERSITY_ENTROPY_MIN_MARGIN, DIVERSITY_RELATIVE_MARGIN * baseline)
    return LIVE_COVERAGE_MARGIN


def _diversity_worst_quartile_floor(key: str) -> float:
    if "entropy" in key:
        return DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR
    return LIVE_COVERAGE_WORST_QUARTILE_FLOOR


def _metric_failures_by_stratum(
    base_cases: dict[str, dict],
    cand_cases: dict[str, dict],
    metric_keys: tuple[str, ...],
    metric_fn,
    margin_fn,
) -> tuple[
    dict[str, list[str]],
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
]:
    qids_by_stratum: dict[str, list[str]] = {}
    for qid, case in base_cases.items():
        qids_by_stratum.setdefault(_stratum(case), []).append(qid)

    failures: dict[str, list[str]] = {}
    deltas: dict[str, dict[str, float]] = {}
    margins: dict[str, dict[str, float]] = {}
    for stratum, qids in sorted(qids_by_stratum.items()):
        base_rows = [metric_fn(base_cases[qid], qid) for qid in qids]
        cand_rows = [metric_fn(cand_cases[qid], qid) for qid in qids]
        base_means = {key: statistics.fmean(row[key] for row in base_rows) for key in metric_keys}
        deltas[stratum] = {
            key: statistics.fmean(row[key] for row in cand_rows) - base_means[key]
            for key in metric_keys
        }
        margins[stratum] = {key: margin_fn(key, base_means[key]) for key in metric_keys}
        lost = [
            key
            for key, delta in deltas[stratum].items()
            if delta < -margins[stratum][key] - COMPARISON_EPSILON
        ]
        if lost:
            failures[stratum] = lost
    return failures, deltas, margins


def _paired_bootstrap(deltas: list[float], samples: int = 10_000) -> dict[str, float | int]:
    """IC unilatéral reproductible sur la requête, unité statistique primaire."""
    if not deltas:
        return {"samples": samples, "estimate": 0.0, "lower_95": 0.0}
    rng = random.Random(0)
    n = len(deltas)
    means = [statistics.fmean(deltas[rng.randrange(n)] for _ in range(n)) for _ in range(samples)]
    return {
        "samples": samples,
        "estimate": statistics.fmean(deltas),
        "lower_95": quantile(means, 0.05),
    }


def _quality_tail(ndcg_deltas: list[float]) -> dict:
    worst_quartile_n = max(1, math.ceil(len(ndcg_deltas) / 4))
    worst_quartile_mean = statistics.fmean(sorted(ndcg_deltas)[:worst_quartile_n])
    bootstrap = _paired_bootstrap(ndcg_deltas)
    worst_quartile_passed = worst_quartile_mean >= NDCG_WORST_QUARTILE_FLOOR - COMPARISON_EPSILON
    bootstrap_passed = bootstrap["lower_95"] >= NDCG_BOOTSTRAP_LOWER_FLOOR - COMPARISON_EPSILON
    return {
        "passed": worst_quartile_passed and bootstrap_passed,
        "worst_quartile_mean": worst_quartile_mean,
        "worst_quartile_floor": NDCG_WORST_QUARTILE_FLOOR,
        "worst_quartile_passed": worst_quartile_passed,
        "paired_bootstrap": bootstrap,
        "bootstrap_lower_floor": NDCG_BOOTSTRAP_LOWER_FLOOR,
        "bootstrap_passed": bootstrap_passed,
    }


def _diversity_tail(per_query_deltas: dict[str, dict[str, float]]) -> dict:
    quartile_size = max(1, math.ceil(len(per_query_deltas) / 4))
    worst_quartile = {
        key: statistics.fmean(sorted(row[key] for row in per_query_deltas.values())[:quartile_size])
        for key in DIVERSITY_KEYS
    }
    floors = {key: _diversity_worst_quartile_floor(key) for key in DIVERSITY_KEYS}
    failures = [
        key for key, delta in worst_quartile.items() if delta < floors[key] - COMPARISON_EPSILON
    ]
    return {
        "passed": not failures,
        "worst_quartile_deltas": worst_quartile,
        "worst_quartile_floors": floors,
        "failures": failures,
    }


def compare(
    baseline: dict,
    candidate: dict,
    gate: str,
    qrels: dict[str, dict[str, int]] | None = None,
    translation_scores: dict[str, dict[str, float]] | None = None,
) -> dict:
    if gate not in {"fidelity", "clinical", "auto"}:
        raise ValueError("gate doit valoir fidelity, clinical ou auto")
    base_cases, cand_cases = _case_map(baseline), _case_map(candidate)
    if base_cases.keys() != cand_cases.keys():
        raise InvalidArtifact("baseline et candidat ne couvrent pas les mêmes query_id")

    base_agg = aggregate(baseline, qrels)
    cand_agg = aggregate(candidate, qrels)
    gates: list[dict] = []

    fidelity_failures = [
        qid for qid in base_cases if not exact_fidelity(base_cases[qid], cand_cases[qid])
    ]
    if gate == "fidelity" or (gate == "auto" and not fidelity_failures):
        gates.append(
            {
                "name": "exact_fidelity",
                "passed": not fidelity_failures,
                "failures": fidelity_failures,
            }
        )
    elif qrels is None:
        gates.append(
            {
                "name": "relative_quality_evidence",
                "passed": False,
                "ineligible": True,
                "reason": (
                    "sorties différentes et qrels médicaux absents"
                    if gate == "auto"
                    else "qrels médicaux absents"
                ),
                "fidelity_failures": fidelity_failures if gate == "auto" else [],
            }
        )
    elif gaps := _qrels_gaps(base_cases, cand_cases, qrels):
        gates.append(
            {
                "name": "relative_quality_evidence",
                "passed": False,
                "ineligible": True,
                "reason": "pool de qrels incomplet",
                "gaps": gaps,
            }
        )
    else:

        def quality_for(case: dict, qid: str) -> dict[str, float]:
            return quality(case, qrels.get(qid, {}))

        stratum_failures, stratum_deltas, stratum_margins = _metric_failures_by_stratum(
            base_cases, cand_cases, QUALITY_KEYS, quality_for, _quality_margin
        )
        aggregate_margins = {key: _quality_margin(key, base_agg[key]) for key in QUALITY_KEYS}
        aggregate_lost = [
            key
            for key in QUALITY_KEYS
            if cand_agg[key] < base_agg[key] - aggregate_margins[key] - COMPARISON_EPSILON
        ]
        per_query_deltas = {
            qid: {
                key: quality(cand_cases[qid], qrels.get(qid, {}))[key]
                - quality(base_cases[qid], qrels.get(qid, {}))[key]
                for key in QUALITY_KEYS
            }
            for qid in base_cases
        }
        ndcg_deltas = [row["ndcg@10"] for row in per_query_deltas.values()]
        quality_tail = _quality_tail(ndcg_deltas)
        gates.append(
            {
                "name": "relative_quality_noninferiority",
                "passed": (not stratum_failures and not aggregate_lost and quality_tail["passed"]),
                "aggregate_failures": aggregate_lost,
                "aggregate_margins": aggregate_margins,
                "stratum_failures": stratum_failures,
                "stratum_deltas": stratum_deltas,
                "stratum_margins": stratum_margins,
                "worst_quartile_ndcg_mean": quality_tail["worst_quartile_mean"],
                "worst_quartile_floor": quality_tail["worst_quartile_floor"],
                "paired_bootstrap_ndcg": quality_tail["paired_bootstrap"],
                "bootstrap_lower_floor": quality_tail["bootstrap_lower_floor"],
                "statistically_supported": quality_tail["bootstrap_passed"],
                "query_outcomes": {
                    "won": sum(delta > COMPARISON_EPSILON for delta in ndcg_deltas),
                    "tied": sum(abs(delta) <= COMPARISON_EPSILON for delta in ndcg_deltas),
                    "lost": sum(delta < -COMPARISON_EPSILON for delta in ndcg_deltas),
                },
                "per_query_deltas_diagnostic": per_query_deltas,
            }
        )

    diversity_aggregate_margins = {
        key: _diversity_margin(key, base_agg[key]) for key in DIVERSITY_KEYS
    }
    diversity_lost = [
        key
        for key in DIVERSITY_KEYS
        if cand_agg[key] < base_agg[key] - diversity_aggregate_margins[key] - COMPARISON_EPSILON
    ]
    (
        diversity_stratum_failures,
        diversity_stratum_deltas,
        diversity_stratum_margins,
    ) = _metric_failures_by_stratum(
        base_cases,
        cand_cases,
        DIVERSITY_KEYS,
        lambda case, qid: diversity(case, qrels.get(qid, {}) if qrels is not None else None),
        _diversity_margin,
    )
    diversity_per_query_deltas = {
        qid: {
            key: diversity(cand_cases[qid], qrels.get(qid, {}) if qrels is not None else None)[key]
            - diversity(base_cases[qid], qrels.get(qid, {}) if qrels is not None else None)[key]
            for key in DIVERSITY_KEYS
        }
        for qid in base_cases
    }
    diversity_tail = _diversity_tail(diversity_per_query_deltas)
    gates.append(
        {
            "name": "diversity_noninferiority",
            "passed": (
                not diversity_lost and not diversity_stratum_failures and diversity_tail["passed"]
            ),
            "aggregate_failures": diversity_lost,
            "aggregate_margins": diversity_aggregate_margins,
            "stratum_failures": diversity_stratum_failures,
            "stratum_deltas": diversity_stratum_deltas,
            "stratum_margins": diversity_stratum_margins,
            "worst_quartile_deltas": diversity_tail["worst_quartile_deltas"],
            "worst_quartile_floors": diversity_tail["worst_quartile_floors"],
            "worst_quartile_failures": diversity_tail["failures"],
            "per_query_deltas_diagnostic": diversity_per_query_deltas,
        }
    )
    changed_translations = {
        qid: {
            "baseline": _translation_map(base_cases[qid]),
            "candidate": _translation_map(cand_cases[qid]),
        }
        for qid in base_cases
        if _translation_map(base_cases[qid]) != _translation_map(cand_cases[qid])
    }
    if not changed_translations:
        gates.append({"name": "translation_fidelity", "passed": True, "mode": "exact"})
    elif _same_translation_contract(baseline, candidate):
        missing_deltas = {
            qid: _translation_missing(cand_cases[qid]) - _translation_missing(base_cases[qid])
            for qid in changed_translations
        }
        coverage_failures = {qid: delta for qid, delta in missing_deltas.items() if delta > 0}
        gates.append(
            {
                "name": "translation_same_contract",
                "passed": not coverage_failures,
                "mode": "same_v2_contract_stochastic_outputs",
                "changed_queries": sorted(changed_translations),
                "missing_translation_deltas": missing_deltas,
                "coverage_failures": coverage_failures,
                "reason": (
                    "même traducteur fingerprinté; les formulations stochastiques "
                    "ne sont pas attribuées au refactor"
                ),
            }
        )
    elif translation_scores is None:
        gates.append(
            {
                "name": "translation_quality_evidence",
                "passed": False,
                "ineligible": True,
                "reason": "traductions différentes et notes bilingues absentes",
                "changed_queries": sorted(changed_translations),
            }
        )
    else:
        baseline_scores = translation_scores.get("baseline", {})
        candidate_scores = translation_scores.get("candidate", {})
        gaps: dict[str, dict[str, list[str]]] = {}
        query_losses: dict[str, list[str]] = {}
        shared_pmid_losses: dict[str, dict[str, list[str]]] = {}
        threshold_failures: dict[str, dict[str, list[str]]] = {}
        critical_failures: dict[str, list[str]] = {}
        for qid, outputs in changed_translations.items():
            side_scores = {
                "baseline": baseline_scores.get(qid, {}),
                "candidate": candidate_scores.get(qid, {}),
            }
            for side in ("baseline", "candidate"):
                required = set(outputs[side])
                values = side_scores[side]
                missing = (
                    sorted(required - set(values)) if isinstance(values, dict) else sorted(required)
                )
                invalid = sorted(
                    pmid
                    for pmid in required & set(values if isinstance(values, dict) else {})
                    if not _valid_translation_score(values[pmid])
                )
                if missing or invalid:
                    gaps.setdefault(qid, {})[side] = [
                        *(f"missing:{pmid}" for pmid in missing),
                        *(f"invalid:{pmid}" for pmid in invalid),
                    ]
            if qid in gaps:
                continue
            base_values = [side_scores["baseline"][pmid] for pmid in outputs["baseline"]]
            cand_values = [side_scores["candidate"][pmid] for pmid in outputs["candidate"]]
            losses = []
            if outputs["baseline"] and not outputs["candidate"]:
                losses = ["coverage"]
            elif base_values and cand_values:
                losses = [
                    key
                    for key in TRANSLATION_SCORE_KEYS
                    if statistics.fmean(float(value[key]) for value in cand_values)
                    < statistics.fmean(float(value[key]) for value in base_values)
                    - COMPARISON_EPSILON
                ]
            if losses:
                query_losses[qid] = losses
            for pmid in set(outputs["baseline"]) & set(outputs["candidate"]):
                lost = [
                    key
                    for key in TRANSLATION_SCORE_KEYS
                    if float(side_scores["candidate"][pmid][key])
                    < float(side_scores["baseline"][pmid][key]) - COMPARISON_EPSILON
                ]
                if lost:
                    shared_pmid_losses.setdefault(qid, {})[pmid] = lost
            for pmid, value in zip(outputs["candidate"], cand_values, strict=True):
                below = [key for key in TRANSLATION_SCORE_KEYS if float(value[key]) < 3]
                if below:
                    threshold_failures.setdefault(qid, {})[pmid] = below
                if int(value["critical_errors"]) > 0:
                    critical_failures.setdefault(qid, []).append(pmid)
        gates.append(
            {
                "name": "translation_quality_noninferiority",
                "passed": not any(
                    (gaps, query_losses, shared_pmid_losses, threshold_failures, critical_failures)
                ),
                "ineligible": bool(gaps),
                "coverage_gaps": gaps,
                "query_mean_failures": query_losses,
                "shared_pmid_failures": shared_pmid_losses,
                "absolute_threshold_failures": threshold_failures,
                "critical_error_failures": critical_failures,
            }
        )
    gates.append(
        {
            "name": "robustness_noninferiority",
            "passed": cand_agg["error_rate"] <= base_agg["error_rate"],
        }
    )
    base_kind, cand_kind = _run_kind(baseline), _run_kind(candidate)
    actual_artifacts = base_kind != "unspecified" or cand_kind != "unspecified"
    same_corpus = baseline.get("corpus_fingerprint") == candidate.get("corpus_fingerprint")
    corpus_identified = bool(baseline.get("corpus_fingerprint"))
    same_replay_source = base_kind != "replay" or baseline.get(
        "source_artifact_sha256"
    ) == candidate.get("source_artifact_sha256")
    replay_source_identified = base_kind != "replay" or bool(baseline.get("source_artifact_sha256"))
    same_machine = baseline.get("machine_fingerprint") == candidate.get("machine_fingerprint")
    machine_identified = bool(baseline.get("machine_fingerprint"))
    base_protocol = baseline.get("protocol_fingerprint")
    cand_protocol = candidate.get("protocol_fingerprint")
    if base_protocol or cand_protocol:
        same_manifest = bool(base_protocol) and base_protocol == cand_protocol
        manifest_identified = bool(base_protocol and cand_protocol)
    else:
        same_manifest = baseline.get("manifest_fingerprint") == candidate.get(
            "manifest_fingerprint"
        )
        manifest_identified = bool(baseline.get("manifest_fingerprint"))
    full_benchmark = (
        baseline.get("benchmark_tier") == "benchmark_full"
        and candidate.get("benchmark_tier") == "benchmark_full"
    )
    performance_comparable = base_kind == cand_kind and (
        not actual_artifacts
        or (
            same_corpus
            and corpus_identified
            and same_replay_source
            and replay_source_identified
            and same_machine
            and machine_identified
            and same_manifest
            and manifest_identified
            and full_benchmark
        )
    )
    gates.append(
        {
            "name": "performance_measurement_comparability",
            "passed": performance_comparable,
            "ineligible": not performance_comparable,
            "baseline_kind": base_kind,
            "candidate_kind": cand_kind,
            "same_corpus": same_corpus,
            "same_replay_source": same_replay_source,
            "same_machine": same_machine,
            "same_manifest": same_manifest,
            "full_benchmark": full_benchmark,
            "reason": (
                None
                if performance_comparable
                else "modes, protocole, corpus, capture source ou tier full non comparables"
            ),
        }
    )

    ineligible = any(item.get("ineligible") for item in gates)
    hard_pass = all(item["passed"] for item in gates)
    if performance_comparable:
        performance = {
            **{
                f"{prefix}_{quantile_name}_gain": (
                    (
                        base_agg[f"{prefix}_{quantile_name}_s"]
                        - cand_agg[f"{prefix}_{quantile_name}_s"]
                    )
                    / base_agg[f"{prefix}_{quantile_name}_s"]
                    if base_agg[f"{prefix}_{quantile_name}_s"]
                    else 0.0
                )
                for prefix in ("usable", "complete")
                for quantile_name in ("p50", "p95")
            },
            "token_gain": (
                (base_agg["tokens_mean"] - cand_agg["tokens_mean"]) / base_agg["tokens_mean"]
                if base_agg["tokens_mean"]
                else 0.0
            ),
        }
        efficiency_improved = any(
            value >= MIN_EFFICIENCY_GAIN - COMPARISON_EPSILON for value in performance.values()
        )
        efficiency_regressed = any(value < -0.05 for value in performance.values())
    else:
        performance = {
            "usable_p50_gain": None,
            "usable_p95_gain": None,
            "complete_p50_gain": None,
            "complete_p95_gain": None,
            "token_gain": None,
        }
        efficiency_improved = False
        efficiency_regressed = False
    verdict = (
        "ineligible"
        if ineligible
        else "reject"
        if not hard_pass or not efficiency_improved or efficiency_regressed
        else "keep"
    )
    return {
        "schema_version": 1,
        "gate": gate,
        "verdict": verdict,
        "gates": gates,
        "baseline": base_agg,
        "candidate": cand_agg,
        "performance": performance,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--gate", choices=("fidelity", "clinical", "auto"), required=True)
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--translation-scores", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    qrels_document = json.loads(args.qrels.read_text()) if args.qrels else None
    qrels, qrels_proxy = (
        _qrels_payload(qrels_document) if qrels_document is not None else (None, None)
    )
    translation_scores = (
        json.loads(args.translation_scores.read_text()) if args.translation_scores else None
    )
    result = compare(
        load_json(args.baseline),
        load_json(args.candidate),
        args.gate,
        qrels,
        translation_scores,
    )
    result["evidence"] = {
        "baseline_sha256": _file_sha256(args.baseline),
        "candidate_sha256": _file_sha256(args.candidate),
        "qrels_sha256": _file_sha256(args.qrels) if args.qrels else None,
        "qrels_proxy": qrels_proxy,
        "translation_scores_sha256": (
            _file_sha256(args.translation_scores) if args.translation_scores else None
        ),
    }
    if qrels_proxy is True:
        result.update(
            {
                "proxy_only": True,
                "clinical_truth": False,
                "production_promotion": False,
                "disclaimer": (
                    "Qrels LLM proxy : le verdict vaut pour ce benchmark et "
                    "n'autorise aucune promotion clinique en production."
                ),
            }
        )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(args.out, rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
