"""Score comparatif des artefacts ``retrieval_screen`` sur des qrels proxy.

Cette porte sert uniquement au screening des expériences autoresearch. Elle ne
juge ni le modèle de pertinence ni la traduction et ne peut jamais promouvoir
une variante en production. Les PMID absents des qrels restent explicitement
inconnus : ils ne sont jamais transformés implicitement en grade zéro.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_retrieval_screen import (
    RetrievalConfig,
    validate_screen_case,
)

RELEVANT_GRADE = 2
MIN_MEDIAN_LATENCY_GAIN = 0.10
EPSILON = 1e-12
NORMALIZED_QUALITY_MARGIN = 0.02
RELEVANT_COUNT_RELATIVE_MARGIN = 0.02
RELEVANT_COUNT_MIN_MARGIN = 1
DIVERSITY_RELATIVE_MARGIN = 0.02
DIVERSITY_ENTROPY_MIN_MARGIN = 0.05
RETRIEVAL_COVERAGE_MIN_MARGIN = 0.25
NDCG_WORST_QUARTILE_FLOOR = -0.05
NDCG_BOOTSTRAP_LOWER_FLOOR = -0.02
DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR = -0.10
RETRIEVAL_COVERAGE_WORST_QUARTILE_FLOOR = -1.0
DIVERSITY_KEYS = (
    "journal_entropy",
    "journal_coverage",
    "source_entropy",
    "source_coverage",
    "year_entropy",
    "year_coverage",
)
QUALITY_KEYS = ("recall_at_50", "relevant_count", "ndcg_at_10")


class RetrievalScoreError(RuntimeError):
    """Artefact screen ou qrels incompatible avec la comparaison demandée."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RetrievalScoreError(f"JSON illisible: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetrievalScoreError(f"objet JSON attendu: {path}")
    return value


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _validate_local_search(case: dict, query_id: str) -> bool:
    local = case.get("local_search")
    if not isinstance(local, dict) or not isinstance(local.get("timed_out"), bool):
        raise RetrievalScoreError(f"statut de recherche locale invalide: {query_id}")

    timed_out = local["timed_out"]
    error = local.get("error")
    if not timed_out:
        if error is not None:
            raise RetrievalScoreError(f"recherche locale en erreur: {query_id}")
        return False

    if not isinstance(error, str) or "statement timeout" not in error.lower():
        raise RetrievalScoreError(f"timeout local non prouvé: {query_id}")
    if case.get("local_pmids_raw") != [] or case.get("local_pmids") != []:
        raise RetrievalScoreError(f"timeout local avec listes locales incohérentes: {query_id}")
    counts = case.get("counts")
    zero_count_keys = ("local", "local_dropped_window", "local_date_unverified")
    if not isinstance(counts, dict) or any(counts.get(key) != 0 for key in zero_count_keys):
        raise RetrievalScoreError(f"timeout local avec compte local incohérent: {query_id}")
    return True


def validate_screen(run: dict) -> list[dict]:
    """Valide un artefact de screening complet, comparable et non dégradé."""
    if run.get("schema_version") != 1:
        raise RetrievalScoreError("schema_version retrieval non pris en charge")
    if run.get("artifact_type") != "retrieval_screen":
        raise RetrievalScoreError("artifact_type doit valoir retrieval_screen")
    if run.get("complete") is not True:
        raise RetrievalScoreError("artefact retrieval incomplet")
    if run.get("read_only") is not True:
        raise RetrievalScoreError("artefact retrieval non read-only")
    calls = run.get("calls")
    if calls != {"query_builder": False, "judge": False, "translate": False}:
        raise RetrievalScoreError("le screening ne doit appeler ni builder, juge ni traduction")

    config = run.get("config")
    if not isinstance(config, dict):
        raise RetrievalScoreError("configuration retrieval absente")
    try:
        RetrievalConfig(**config)
    except (TypeError, ValueError) as exc:
        raise RetrievalScoreError(f"configuration retrieval invalide: {exc}") from exc
    if run.get("config_fingerprint") != fingerprint(config):
        raise RetrievalScoreError("fingerprint de configuration incohérent")

    for key in (
        "database",
        "corpus_scope",
        "corpus_fingerprint",
        "machine_fingerprint",
        "source_run_id",
        "source_artifact_sha256",
        "runner_sha256",
    ):
        if not _valid_identifier(run.get(key)):
            raise RetrievalScoreError(f"identité retrieval absente: {key}")

    cases = run.get("cases")
    expected = run.get("expected_query_ids")
    if not isinstance(cases, list) or not cases:
        raise RetrievalScoreError("aucun cas retrieval")
    actual = [case.get("query_id") for case in cases]
    if (
        not isinstance(expected, list)
        or expected != actual
        or len(actual) != len(set(actual))
        or not all(_valid_identifier(query_id) for query_id in actual)
    ):
        raise RetrievalScoreError("ordre ou identité des query_id invalide")

    for case in cases:
        query_id = str(case["query_id"])
        if case.get("error"):
            raise RetrievalScoreError(f"cas retrieval en erreur: {query_id}")
        if case.get("config") != config:
            raise RetrievalScoreError(f"configuration de cas incohérente: {query_id}")
        if case.get("hydration_errors"):
            raise RetrievalScoreError(f"hydratation dégradée: {query_id}")
        _validate_local_search(case, query_id)
        timings = case.get("timings")
        total_s = timings.get("total_s") if isinstance(timings, dict) else None
        if isinstance(total_s, bool) or not isinstance(total_s, (int, float)) or total_s <= 0:
            raise RetrievalScoreError(f"latence totale invalide: {query_id}")
        try:
            validate_screen_case(case)
        except ValueError as exc:
            raise RetrievalScoreError(f"ordre du lot invalide ({query_id}): {exc}") from exc
        builder = case.get("query_builder")
        if not isinstance(builder, dict) or case.get("query_builder_fingerprint") != fingerprint(
            builder
        ):
            raise RetrievalScoreError(f"query-builder incohérent: {query_id}")
    return cases


def validate_pair(baseline: dict, candidate: dict) -> tuple[list[dict], list[dict]]:
    baseline_cases = validate_screen(baseline)
    candidate_cases = validate_screen(candidate)
    shared_keys = (
        "expected_query_ids",
        "database",
        "corpus_scope",
        "corpus_fingerprint",
        "machine_fingerprint",
        "source_run_id",
        "source_artifact_sha256",
        "runner_sha256",
    )
    mismatches = [key for key in shared_keys if baseline.get(key) != candidate.get(key)]
    if mismatches:
        raise RetrievalScoreError(f"artefacts retrieval non comparables: {', '.join(mismatches)}")
    for base_case, cand_case in zip(baseline_cases, candidate_cases, strict=True):
        query_id = str(base_case["query_id"])
        for key in ("query_id", "query", "width", "date_from", "date_to"):
            if base_case.get(key) != cand_case.get(key):
                raise RetrievalScoreError(f"cas non comparable ({query_id}): {key}")
        if base_case.get("query_builder_fingerprint") != cand_case.get("query_builder_fingerprint"):
            raise RetrievalScoreError(f"query-builder différent: {query_id}")
    return baseline_cases, candidate_cases


def validate_qrels(proxy: dict, query_ids: list[str]) -> dict[str, dict[str, int]]:
    if proxy.get("schema_version") != 1:
        raise RetrievalScoreError("schema_version des qrels proxy non pris en charge")
    if proxy.get("proxy") is not True:
        raise RetrievalScoreError("les qrels doivent être explicitement marqués proxy")
    raw = proxy.get("qrels")
    if not isinstance(raw, dict):
        raise RetrievalScoreError("qrels proxy absents")
    extra = sorted(set(raw) - set(query_ids))
    if extra:
        raise RetrievalScoreError(f"qrels pour des query_id inattendus: {extra}")
    out: dict[str, dict[str, int]] = {}
    for query_id in query_ids:
        values = raw.get(query_id, {})
        if not isinstance(values, dict):
            raise RetrievalScoreError(f"qrels invalides pour {query_id}")
        normalized = {}
        for raw_pmid, raw_grade in values.items():
            if (
                isinstance(raw_grade, bool)
                or not isinstance(raw_grade, int)
                or not 0 <= raw_grade <= 3
            ):
                raise RetrievalScoreError(f"grade invalide pour {query_id}/{raw_pmid}")
            try:
                pmid = str(int(raw_pmid))
            except (TypeError, ValueError) as exc:
                raise RetrievalScoreError(f"PMID qrels invalide: {query_id}/{raw_pmid}") from exc
            normalized[pmid] = raw_grade
        out[query_id] = normalized
    return out


def _entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _diversity(rows: list[dict], labels: dict[str, int]) -> dict[str, float]:
    relevant = [row for row in rows if labels.get(str(row["pmid"]), 0) >= RELEVANT_GRADE]
    dimensions = {
        "journal": [str(row["journal"]) for row in relevant if row.get("journal")],
        "source": [str(row["source"]) for row in relevant if row.get("source")],
        "year": [str(row["pub_year"]) for row in relevant if row.get("pub_year") is not None],
    }
    return {
        key: value
        for dimension, values in dimensions.items()
        for key, value in (
            (f"{dimension}_entropy", _entropy(values)),
            (f"{dimension}_coverage", float(len(set(values)))),
        )
    }


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def _metrics(case: dict, labels: dict[str, int]) -> dict:
    selected = [int(pmid) for pmid in case["judge_pmids"]]
    rows = case["selected_metadata"]
    top10 = selected[:10]
    top50 = selected[:50]
    known = set(labels)
    unknown = [pmid for pmid in selected if str(pmid) not in known]
    unknown_top10 = [pmid for pmid in top10 if str(pmid) not in known]
    unknown_top50 = [pmid for pmid in top50 if str(pmid) not in known]
    grades10 = [labels.get(str(pmid), 0) for pmid in top10]
    grades50 = [labels.get(str(pmid), 0) for pmid in top50]
    ideal = sorted(labels.values(), reverse=True)[:10]
    ideal_dcg = _dcg(ideal)
    relevant_total = sum(grade >= RELEVANT_GRADE for grade in labels.values())
    relevant_count = sum(grade >= RELEVANT_GRADE for grade in grades50)
    return {
        "selected_count": len(selected),
        "annotated_top10": sum(str(pmid) in known for pmid in top10),
        "coverage_top10": (
            sum(str(pmid) in known for pmid in top10) / len(top10) if top10 else 1.0
        ),
        "annotated_top50": sum(str(pmid) in known for pmid in top50),
        "coverage_top50": (
            sum(str(pmid) in known for pmid in top50) / len(top50) if top50 else 1.0
        ),
        "unknown_pmids": unknown,
        "unknown_pmids_top10": unknown_top10,
        "unknown_pmids_top50": unknown_top50,
        "relevant_count": float(relevant_count),
        "graded_gain": float(sum(2**grade - 1 for grade in grades50)),
        "recall_at_50": relevant_count / relevant_total if relevant_total else 0.0,
        "ndcg_at_10": _dcg(grades10) / ideal_dcg if ideal_dcg else 0.0,
        "diversity": _diversity(rows[:50], labels),
    }


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _paired_bootstrap(deltas: list[float], samples: int = 10_000) -> dict[str, float | int]:
    rng = random.Random(0)
    size = len(deltas)
    means = [
        statistics.fmean(deltas[rng.randrange(size)] for _ in range(size)) for _ in range(samples)
    ]
    return {
        "samples": samples,
        "estimate": statistics.fmean(deltas),
        "lower_95": _quantile(means, 0.05),
    }


def _quality_margin(key: str, baseline: float) -> float:
    if key == "relevant_count":
        return float(
            max(
                RELEVANT_COUNT_MIN_MARGIN,
                math.floor(RELEVANT_COUNT_RELATIVE_MARGIN * baseline),
            )
        )
    return NORMALIZED_QUALITY_MARGIN


def _diversity_margin(key: str, baseline: float) -> float:
    if "entropy" in key:
        return max(DIVERSITY_ENTROPY_MIN_MARGIN, DIVERSITY_RELATIVE_MARGIN * baseline)
    return max(RETRIEVAL_COVERAGE_MIN_MARGIN, DIVERSITY_RELATIVE_MARGIN * baseline)


def _diversity_worst_quartile_floor(key: str) -> float:
    if "entropy" in key:
        return DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR
    return RETRIEVAL_COVERAGE_WORST_QUARTILE_FLOOR


def _aggregate(per_query: dict[str, dict], widths: dict[str, str]) -> dict:
    rows = list(per_query.values())

    def summarize(selected: list[dict]) -> dict:
        return {
            "queries": len(selected),
            "coverage_top10": _mean([row["coverage_top10"] for row in selected]),
            "coverage_top50": _mean([row["coverage_top50"] for row in selected]),
            "relevant_count_mean": _mean([row["relevant_count"] for row in selected]),
            "relevant_count_total": sum(row["relevant_count"] for row in selected),
            "graded_gain_mean": _mean([row["graded_gain"] for row in selected]),
            "graded_gain_total": sum(row["graded_gain"] for row in selected),
            "recall_at_50": _mean([row["recall_at_50"] for row in selected]),
            "ndcg_at_10": _mean([row["ndcg_at_10"] for row in selected]),
            "diversity": {
                key: _mean([row["diversity"][key] for row in selected]) for key in DIVERSITY_KEYS
            },
        }

    by_width = {}
    for width in sorted(set(widths.values())):
        by_width[width] = summarize(
            [per_query[query_id] for query_id, value in widths.items() if value == width]
        )
    return {"global": summarize(rows), "widths": by_width}


def _noninferiority(base: dict, cand: dict) -> tuple[bool, list[str], dict[str, float]]:
    failures = []
    margins = {}
    for key in QUALITY_KEYS:
        aggregate_key = "relevant_count_total" if key == "relevant_count" else key
        margin = _quality_margin(key, base[aggregate_key])
        margins[key] = margin
        if cand[aggregate_key] < base[aggregate_key] - margin - EPSILON:
            failures.append(key)
    for key in DIVERSITY_KEYS:
        margin = _diversity_margin(key, base["diversity"][key])
        margins[f"diversity.{key}"] = margin
        if cand["diversity"][key] < base["diversity"][key] - margin - EPSILON:
            failures.append(f"diversity.{key}")
    return not failures, failures, margins


def _tail_noninferiority(base_per_query: dict[str, dict], cand_per_query: dict[str, dict]) -> dict:
    query_ids = list(base_per_query)
    ndcg_deltas = [
        cand_per_query[query_id]["ndcg_at_10"] - base_per_query[query_id]["ndcg_at_10"]
        for query_id in query_ids
    ]
    quartile_size = max(1, math.ceil(len(query_ids) / 4))
    ndcg_worst_quartile = statistics.fmean(sorted(ndcg_deltas)[:quartile_size])
    bootstrap = _paired_bootstrap(ndcg_deltas)
    ndcg_worst_passed = ndcg_worst_quartile >= NDCG_WORST_QUARTILE_FLOOR - EPSILON
    bootstrap_passed = bootstrap["lower_95"] >= NDCG_BOOTSTRAP_LOWER_FLOOR - EPSILON

    diversity_worst_quartile = {
        key: statistics.fmean(
            sorted(
                cand_per_query[query_id]["diversity"][key]
                - base_per_query[query_id]["diversity"][key]
                for query_id in query_ids
            )[:quartile_size]
        )
        for key in DIVERSITY_KEYS
    }
    diversity_failures = [
        key
        for key, delta in diversity_worst_quartile.items()
        if delta < _diversity_worst_quartile_floor(key) - EPSILON
    ]
    return {
        "passed": ndcg_worst_passed and bootstrap_passed and not diversity_failures,
        "ndcg": {
            "worst_quartile_mean": ndcg_worst_quartile,
            "worst_quartile_floor": NDCG_WORST_QUARTILE_FLOOR,
            "worst_quartile_passed": ndcg_worst_passed,
            "paired_bootstrap": bootstrap,
            "bootstrap_lower_floor": NDCG_BOOTSTRAP_LOWER_FLOOR,
            "bootstrap_passed": bootstrap_passed,
        },
        "diversity": {
            "worst_quartile_deltas": diversity_worst_quartile,
            "worst_quartile_floors": {
                key: _diversity_worst_quartile_floor(key) for key in DIVERSITY_KEYS
            },
            "failures": diversity_failures,
        },
    }


def _gate_scenario(
    base: dict,
    cand: dict,
    base_per_query: dict[str, dict],
    cand_per_query: dict[str, dict],
) -> dict:
    global_pass, global_failures, global_margins = _noninferiority(base["global"], cand["global"])
    width_failures = {}
    width_margins = {}
    for width in base["widths"]:
        passed, failures, margins = _noninferiority(base["widths"][width], cand["widths"][width])
        width_margins[width] = margins
        if not passed:
            width_failures[width] = failures
    tail = _tail_noninferiority(base_per_query, cand_per_query)
    return {
        "passed": global_pass and not width_failures and tail["passed"],
        "global_failures": global_failures,
        "global_margins": global_margins,
        "width_failures": width_failures,
        "width_margins": width_margins,
        "tail": tail,
    }


def _scenario_labels(
    qrels: dict[str, dict[str, int]],
    unknown_union: dict[str, set[int]],
    unknown_grade: int,
) -> dict[str, dict[str, int]]:
    return {
        query_id: {
            **labels,
            **{str(pmid): unknown_grade for pmid in unknown_union[query_id]},
        }
        for query_id, labels in qrels.items()
    }


def _robustness(
    baseline: dict[str, dict],
    candidate: dict[str, dict],
    query_ids: list[str],
    widths: dict[str, str],
) -> dict:
    per_query = {
        query_id: {
            "width": widths[query_id],
            "baseline": {"timeout_count": int(baseline[query_id]["local_search"]["timed_out"])},
            "candidate": {"timeout_count": int(candidate[query_id]["local_search"]["timed_out"])},
        }
        for query_id in query_ids
    }

    def compare_group(selected: list[str]) -> dict:
        base_count = sum(per_query[query_id]["baseline"]["timeout_count"] for query_id in selected)
        cand_count = sum(per_query[query_id]["candidate"]["timeout_count"] for query_id in selected)
        size = len(selected)
        base_rate = base_count / size
        cand_rate = cand_count / size
        return {
            "queries": size,
            "baseline": {"timeout_count": base_count, "timeout_rate": base_rate},
            "candidate": {"timeout_count": cand_count, "timeout_rate": cand_rate},
            "passed": cand_rate <= base_rate + EPSILON,
        }

    global_result = compare_group(query_ids)
    width_results = {
        width: compare_group([query_id for query_id in query_ids if widths[query_id] == width])
        for width in sorted(set(widths.values()))
    }
    width_failures = [width for width, result in width_results.items() if not result["passed"]]
    return {
        "per_query": per_query,
        "global": global_result,
        "widths": width_results,
        "gate": {
            "passed": global_result["passed"] and not width_failures,
            "global_passed": global_result["passed"],
            "width_failures": width_failures,
        },
    }


def compare(baseline: dict, candidate: dict, proxy_qrels: dict) -> dict:
    baseline_cases, candidate_cases = validate_pair(baseline, candidate)
    query_ids = [str(case["query_id"]) for case in baseline_cases]
    qrels = validate_qrels(proxy_qrels, query_ids)
    base_by_id = {str(case["query_id"]): case for case in baseline_cases}
    cand_by_id = {str(case["query_id"]): case for case in candidate_cases}
    widths = {
        query_id: str(base_by_id[query_id].get("width") or "unspecified") for query_id in query_ids
    }
    robustness = _robustness(base_by_id, cand_by_id, query_ids, widths)

    original = {
        "baseline": {
            query_id: _metrics(base_by_id[query_id], qrels[query_id]) for query_id in query_ids
        },
        "candidate": {
            query_id: _metrics(cand_by_id[query_id], qrels[query_id]) for query_id in query_ids
        },
    }
    unknown_union = {
        query_id: set(original["baseline"][query_id]["unknown_pmids"])
        | set(original["candidate"][query_id]["unknown_pmids"])
        for query_id in query_ids
    }
    scenarios = {}
    for grade in (0, 3):
        labels = _scenario_labels(qrels, unknown_union, grade)
        base_per_query = {
            query_id: _metrics(base_by_id[query_id], labels[query_id]) for query_id in query_ids
        }
        cand_per_query = {
            query_id: _metrics(cand_by_id[query_id], labels[query_id]) for query_id in query_ids
        }
        base_aggregate = _aggregate(base_per_query, widths)
        cand_aggregate = _aggregate(cand_per_query, widths)
        scenarios[str(grade)] = {
            "per_query": {"baseline": base_per_query, "candidate": cand_per_query},
            "baseline": base_aggregate,
            "candidate": cand_aggregate,
            "gate": _gate_scenario(
                base_aggregate,
                cand_aggregate,
                base_per_query,
                cand_per_query,
            ),
        }

    all_annotated = not any(unknown_union.values())
    extreme_scenarios_change = scenarios["0"]["gate"]["passed"] != scenarios["3"]["gate"]["passed"]
    latency_gains = []
    for query_id in query_ids:
        base_s = float(base_by_id[query_id]["timings"]["total_s"])
        cand_s = float(cand_by_id[query_id]["timings"]["total_s"])
        latency_gains.append((base_s - cand_s) / base_s)
    median_latency_gain = statistics.median(latency_gains)
    quality_pass = scenarios["0"]["gate"]["passed"]

    if not all_annotated and extreme_scenarios_change:
        verdict = "ineligible"
        reason = "les inconnus changent la non-infériorité entre les bornes 0/3"
    elif not all_annotated:
        verdict = "reject"
        reason = "annotations proxy incomplètes; keep_screen exige un top-50 entièrement annoté"
    elif not robustness["gate"]["passed"]:
        verdict = "reject"
        reason = "le taux de timeout local régresse globalement ou dans une strate de largeur"
    elif not quality_pass or median_latency_gain + EPSILON < MIN_MEDIAN_LATENCY_GAIN:
        verdict = "reject"
        reason = "non-infériorité ou gain médian de latence insuffisant"
    else:
        verdict = "keep_screen"
        reason = "screening proxy passé; aucune promotion production autorisée"

    per_query = {}
    for query_id in query_ids:
        base_metrics = original["baseline"][query_id]
        cand_metrics = original["candidate"][query_id]
        per_query[query_id] = {
            "width": widths[query_id],
            "baseline": base_metrics,
            "candidate": cand_metrics,
            "deltas_diagnostic": {
                "relevant_count": cand_metrics["relevant_count"] - base_metrics["relevant_count"],
                "graded_gain": cand_metrics["graded_gain"] - base_metrics["graded_gain"],
                "recall_at_50": cand_metrics["recall_at_50"] - base_metrics["recall_at_50"],
                "ndcg_at_10": cand_metrics["ndcg_at_10"] - base_metrics["ndcg_at_10"],
                "retrieval_total_latency_gain": latency_gains[query_ids.index(query_id)],
            },
        }

    return {
        "schema_version": 1,
        "gate": "retrieval_screen_proxy",
        "proxy": True,
        "production_promotion": False,
        "verdict": verdict,
        "reason": reason,
        "disclaimer": (
            "Screening sur qrels LLM proxy: ce verdict ne démontre pas une qualité clinique "
            "et ne permet jamais une promotion en production."
        ),
        "all_annotated": all_annotated,
        "unknowns_can_change_noninferiority": extreme_scenarios_change,
        "unknown_pmids": {
            query_id: {
                "baseline": original["baseline"][query_id]["unknown_pmids"],
                "candidate": original["candidate"][query_id]["unknown_pmids"],
                "union": sorted(unknown_union[query_id]),
            }
            for query_id in query_ids
        },
        "bounds": {"unknown_grade_0": scenarios["0"], "unknown_grade_3": scenarios["3"]},
        "per_query": per_query,
        "robustness": robustness,
        "performance": {
            "per_query_total_latency_gain": dict(zip(query_ids, latency_gains, strict=True)),
            "median_total_latency_gain": median_latency_gain,
            "required_median_gain": MIN_MEDIAN_LATENCY_GAIN,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("qrels", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = compare(load_json(args.baseline), load_json(args.candidate), load_json(args.qrels))
    except RetrievalScoreError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
