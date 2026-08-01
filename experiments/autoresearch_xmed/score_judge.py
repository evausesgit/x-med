"""Score comparatif de deux artefacts ``judge_screen`` sur des qrels proxy.

Le verdict ne vaut que pour le screening autoresearch. Les métriques sont
agrégées en deux temps (répétitions par requête, puis requêtes globalement et par
largeur) afin qu'une requête répétée davantage ne pèse jamais plus lourd.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_judge_screen import JudgeConfig

EPSILON = 1e-12
RELEVANT_GRADE = 2
MIN_EFFICIENCY_GAIN = 0.10
MAX_OTHER_AXIS_REGRESSION = 0.05
QUALITY_MARGIN = 0.02
NDCG_WORST_QUARTILE_FLOOR = -0.05
QUALITY_KEYS = ("ndcg_at_10", "p_at_10", "recall_pool", "f1_at_2")
METRIC_KEYS = (
    "ndcg_at_10",
    "p_at_10",
    "recall_pool",
    "precision_at_2",
    "recall_at_2",
    "f1_at_2",
    "mae_grade",
)


class JudgeScoreError(RuntimeError):
    """Artefact, qrels ou strates impropres à une comparaison."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JudgeScoreError(f"JSON illisible: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise JudgeScoreError(f"objet JSON attendu: {path}")
    return value


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _positive_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _valid_usage(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    for key in keys:
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return False
    total = value.get("total_tokens")
    return (
        isinstance(total, int)
        and not isinstance(total, bool)
        and total == value["input_tokens"] + value["output_tokens"]
        and total > 0
    )


def _sum_usage(values: list[dict]) -> dict[str, int]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    out = {key: sum(value[key] for value in values) for key in keys}
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


def _validate_judgement(row: object, query_id: str) -> int:
    if not isinstance(row, dict):
        raise JudgeScoreError(f"jugement non objet: {query_id}")
    pmid = row.get("pmid")
    score = row.get("score")
    pct = row.get("relevance_pct")
    reason = row.get("reason")
    if isinstance(pmid, bool) or not isinstance(pmid, int):
        raise JudgeScoreError(f"PMID de jugement invalide: {query_id}")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
        raise JudgeScoreError(f"score invalide: {query_id}/{pmid}")
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 <= pct <= 100:
        raise JudgeScoreError(f"relevance_pct invalide: {query_id}/{pmid}")
    if not isinstance(reason, str) or not reason.strip():
        raise JudgeScoreError(f"reason invalide: {query_id}/{pmid}")
    return pmid


def validate_screen(run: dict) -> list[dict]:
    if run.get("schema_version") != 1 or run.get("artifact_type") != "judge_screen":
        raise JudgeScoreError("artefact de type judge_screen v1 requis")
    if run.get("complete") is not True:
        raise JudgeScoreError("artefact judge_screen incomplet")
    if run.get("calls") != {"database": False, "retrieval": False, "translate": False}:
        raise JudgeScoreError("le judge_screen ne doit appeler ni DB, retrieval ni traduction")
    for key in ("source_pool_sha256", "runner_sha256", "machine_fingerprint"):
        if not _valid_id(run.get(key)):
            raise JudgeScoreError(f"identité judge_screen absente: {key}")

    config = run.get("config")
    if not isinstance(config, dict):
        raise JudgeScoreError("configuration judge_screen absente")
    try:
        parsed_config = JudgeConfig(**config)
    except (TypeError, ValueError) as exc:
        raise JudgeScoreError(f"configuration judge_screen invalide: {exc}") from exc
    if run.get("config_fingerprint") != fingerprint(config):
        raise JudgeScoreError("config_fingerprint incohérent")
    if run.get("exact_production_prompt") is not parsed_config.exact_production_prompt:
        raise JudgeScoreError("identité du prompt baseline incohérente")

    cases = run.get("cases")
    expected_ids = run.get("expected_query_ids")
    if not isinstance(cases, list) or not cases:
        raise JudgeScoreError("aucun cas judge_screen")
    actual_ids = [case.get("query_id") for case in cases]
    if (
        not isinstance(expected_ids, list)
        or expected_ids != actual_ids
        or len(actual_ids) != len(set(actual_ids))
        or not all(_valid_id(query_id) for query_id in actual_ids)
    ):
        raise JudgeScoreError("ordre ou identité des query_id invalide")

    for case in cases:
        query_id = str(case["query_id"])
        if case.get("error"):
            raise JudgeScoreError(f"cas judge_screen en erreur: {query_id}")
        if case.get("config") != config:
            raise JudgeScoreError(f"configuration de cas incohérente: {query_id}")
        if not isinstance(case.get("query"), str) or not case["query"]:
            raise JudgeScoreError(f"question absente: {query_id}")
        item_ids = case.get("item_ids")
        pmids = case.get("pmids")
        if (
            not isinstance(item_ids, list)
            or not all(_valid_id(item_id) for item_id in item_ids)
            or len(item_ids) != len(set(item_ids))
            or not isinstance(pmids, list)
            or any(isinstance(pmid, bool) or not isinstance(pmid, int) for pmid in pmids)
            or len(pmids) != len(set(pmids))
            or len(item_ids) != len(pmids)
            or not pmids
        ):
            raise JudgeScoreError(f"identités pool invalides: {query_id}")

        repetitions = case.get("repetitions")
        if not isinstance(repetitions, list) or len(repetitions) != parsed_config.repetitions:
            raise JudgeScoreError(f"répétitions incomplètes: {query_id}")
        expected_repetitions = list(range(1, parsed_config.repetitions + 1))
        if [rep.get("repetition") for rep in repetitions] != expected_repetitions:
            raise JudgeScoreError(f"ordre des répétitions invalide: {query_id}")

        for repetition in repetitions:
            if not _positive_number(repetition.get("latency_s")):
                raise JudgeScoreError(f"latence répétition invalide: {query_id}")
            if not _valid_usage(repetition.get("tokens")):
                raise JudgeScoreError(f"tokens répétition invalides: {query_id}")
            calls = repetition.get("calls")
            prompt_hashes = repetition.get("prompt_hashes")
            if not isinstance(calls, list) or not calls:
                raise JudgeScoreError(f"appels juge absents: {query_id}")
            if (
                not isinstance(prompt_hashes, list)
                or prompt_hashes != [call.get("prompt_sha256") for call in calls]
                or not all(_valid_id(value) for value in prompt_hashes)
            ):
                raise JudgeScoreError(f"hashes de prompt invalides: {query_id}")
            call_pmids = []
            for call in calls:
                values = call.get("pmids") if isinstance(call, dict) else None
                if (
                    not isinstance(values, list)
                    or any(isinstance(pmid, bool) or not isinstance(pmid, int) for pmid in values)
                    or not values
                    or not _positive_number(call.get("latency_s"))
                    or not _valid_usage(call.get("usage"))
                ):
                    raise JudgeScoreError(f"appel juge invalide: {query_id}")
                call_pmids.extend(values)
            if call_pmids != pmids or len(call_pmids) != len(set(call_pmids)):
                raise JudgeScoreError(f"bijection appels/PMID invalide: {query_id}")
            if repetition["tokens"] != _sum_usage([call["usage"] for call in calls]):
                raise JudgeScoreError(f"agrégat tokens répétition incohérent: {query_id}")

            judgements = repetition.get("judgements")
            if not isinstance(judgements, list):
                raise JudgeScoreError(f"jugements absents: {query_id}")
            judgement_pmids = [_validate_judgement(row, query_id) for row in judgements]
            if judgement_pmids != pmids or len(judgement_pmids) != len(set(judgement_pmids)):
                raise JudgeScoreError(f"bijection jugements/PMID invalide: {query_id}")
        if not _valid_usage(case.get("tokens")) or case["tokens"] != _sum_usage(
            [repetition["tokens"] for repetition in repetitions]
        ):
            raise JudgeScoreError(f"agrégat tokens query incohérent: {query_id}")
    return cases


def pair_mismatches(baseline: dict, candidate: dict) -> list[str]:
    keys = (
        "artifact_type",
        "source_pool_sha256",
        "runner_sha256",
        "machine_fingerprint",
        "expected_query_ids",
    )
    mismatches = [key for key in keys if baseline.get(key) != candidate.get(key)]
    if baseline["config"]["repetitions"] != candidate["config"]["repetitions"]:
        mismatches.append("config.repetitions")
    base_cases = baseline["cases"]
    cand_cases = candidate["cases"]
    if len(base_cases) != len(cand_cases):
        return [*mismatches, "cases"]
    for base_case, cand_case in zip(base_cases, cand_cases, strict=True):
        query_id = str(base_case["query_id"])
        for key in ("query_id", "query", "item_ids", "pmids"):
            if base_case.get(key) != cand_case.get(key):
                mismatches.append(f"{query_id}.{key}")
    return mismatches


def load_widths(path: Path, expected_ids: list[str], cases: list[dict]) -> dict[str, str]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as exc:
        raise JudgeScoreError(f"queries.jsonl illisible: {path}") from exc
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not _valid_id(row.get("id")):
            raise JudgeScoreError("ligne queries.jsonl invalide")
        if row["id"] in by_id:
            raise JudgeScoreError(f"query id dupliqué dans queries.jsonl: {row['id']}")
        if not _valid_id(row.get("width")) or not isinstance(row.get("query"), str):
            raise JudgeScoreError(f"width/query absent dans queries.jsonl: {row['id']}")
        by_id[row["id"]] = row
    missing = [query_id for query_id in expected_ids if query_id not in by_id]
    if missing:
        raise JudgeScoreError(f"widths manquantes: {missing}")
    for case in cases:
        query_id = str(case["query_id"])
        if case["query"] != by_id[query_id]["query"]:
            raise JudgeScoreError(f"question différente dans queries.jsonl: {query_id}")
    return {query_id: str(by_id[query_id]["width"]) for query_id in expected_ids}


def validate_qrels(proxy: dict, query_ids: list[str]) -> dict[str, dict[int, int]]:
    if proxy.get("schema_version") != 1 or proxy.get("proxy") is not True:
        raise JudgeScoreError("qrels v1 explicitement proxy requis")
    raw = proxy.get("qrels")
    if not isinstance(raw, dict):
        raise JudgeScoreError("qrels absents")
    extras = sorted(set(raw) - set(query_ids))
    if extras:
        raise JudgeScoreError(f"query_id qrels inattendus: {extras}")
    normalized = {}
    for query_id in query_ids:
        labels = raw.get(query_id)
        if not isinstance(labels, dict):
            raise JudgeScoreError(f"qrels invalides: {query_id}")
        values = {}
        for raw_pmid, grade in labels.items():
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
                raise JudgeScoreError(f"grade qrels invalide: {query_id}/{raw_pmid}")
            try:
                pmid = int(raw_pmid)
            except (TypeError, ValueError) as exc:
                raise JudgeScoreError(f"PMID qrels invalide: {query_id}/{raw_pmid}") from exc
            values[pmid] = grade
        normalized[query_id] = values
    return normalized


def qrel_gaps(cases: list[dict], qrels: dict[str, dict[int, int]]) -> dict[str, list[int]]:
    gaps = {}
    for case in cases:
        query_id = str(case["query_id"])
        missing = sorted(set(case["pmids"]) - set(qrels[query_id]))
        if missing:
            gaps[query_id] = missing
    return gaps


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def repetition_metrics(repetition: dict, pool_order: list[int], labels: dict[int, int]) -> dict:
    pool_rank = {pmid: rank for rank, pmid in enumerate(pool_order)}
    ranked = sorted(
        repetition["judgements"],
        key=lambda row: (-row["score"], -row["relevance_pct"], pool_rank[row["pmid"]]),
    )
    ranked_pmids = [row["pmid"] for row in ranked]
    top10 = ranked[:10]
    top_grades = [labels[row["pmid"]] for row in top10]
    ideal = sorted(labels.values(), reverse=True)[:10]
    ideal_dcg = _dcg(ideal)
    relevant_total = sum(grade >= RELEVANT_GRADE for grade in labels.values())
    relevant_top = sum(grade >= RELEVANT_GRADE for grade in top_grades)

    predicted = {row["pmid"] for row in ranked if row["score"] >= RELEVANT_GRADE}
    relevant = {pmid for pmid, grade in labels.items() if grade >= RELEVANT_GRADE}
    true_positive = len(predicted & relevant)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(relevant) if relevant else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    mae = statistics.fmean(abs(row["score"] - labels[row["pmid"]]) for row in ranked)
    return {
        "ranking_pmids": ranked_pmids,
        "ndcg_at_10": _dcg(top_grades) / ideal_dcg if ideal_dcg else 0.0,
        "p_at_10": relevant_top / 10.0,
        "recall_pool": relevant_top / relevant_total if relevant_total else 0.0,
        "precision_at_2": precision,
        "recall_at_2": recall,
        "f1_at_2": f1,
        "mae_grade": mae,
        "latency_s": float(repetition["latency_s"]),
        "tokens": int(repetition["tokens"]["total_tokens"]),
    }


def _mean_metrics(rows: list[dict]) -> dict[str, float]:
    return {key: statistics.fmean(row[key] for row in rows) for key in METRIC_KEYS}


def evaluate_artifact(
    cases: list[dict], qrels: dict[str, dict[int, int]], widths: dict[str, str]
) -> dict:
    per_query = {}
    latency_samples = []
    token_samples = []
    for case in cases:
        query_id = str(case["query_id"])
        repetitions = [
            repetition_metrics(repetition, case["pmids"], qrels[query_id])
            for repetition in case["repetitions"]
        ]
        latency_samples.extend(row["latency_s"] for row in repetitions)
        token_samples.extend(row["tokens"] for row in repetitions)
        per_query[query_id] = {
            "width": widths[query_id],
            "repetitions": repetitions,
            "mean": _mean_metrics(repetitions),
        }

    def aggregate(query_ids: list[str]) -> dict:
        return {
            "queries": len(query_ids),
            **{
                key: statistics.fmean(per_query[query_id]["mean"][key] for query_id in query_ids)
                for key in METRIC_KEYS
            },
        }

    query_ids = list(per_query)
    by_width = {
        width: aggregate([query_id for query_id in query_ids if widths[query_id] == width])
        for width in sorted(set(widths.values()))
    }
    return {
        "per_query": per_query,
        "aggregate": {"global": aggregate(query_ids), "widths": by_width},
        "performance": {
            "wall_latency_p50_s": statistics.median(latency_samples),
            "tokens_mean": statistics.fmean(token_samples),
            "samples": len(latency_samples),
        },
    }


def _relative_gain(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        raise JudgeScoreError("mesure de performance baseline non positive")
    return (baseline - candidate) / baseline


def _ineligible(reason: str, **details) -> dict:
    return {
        "schema_version": 1,
        "gate": "judge_screen_proxy",
        "proxy": True,
        "production_promotion": False,
        "verdict": "ineligible",
        "reason": reason,
        "disclaimer": (
            "Screening sur qrels LLM proxy uniquement : ce verdict ne démontre pas une "
            "qualité clinique et n'autorise aucune promotion en production."
        ),
        **details,
    }


def _quality_noninferiority(
    baseline: dict[str, float], candidate: dict[str, float]
) -> tuple[list[str], dict[str, float], dict[str, float]]:
    margins = {key: QUALITY_MARGIN for key in QUALITY_KEYS}
    deltas = {key: candidate[key] - baseline[key] for key in QUALITY_KEYS}
    failures = [key for key in QUALITY_KEYS if deltas[key] < -margins[key] - EPSILON]
    return failures, margins, deltas


def _worst_quartile_ndcg(ndcg_deltas: dict[str, float]) -> dict:
    query_ids = list(ndcg_deltas)
    quartile_size = max(1, math.ceil(len(query_ids) / 4))
    worst_query_ids = sorted(query_ids, key=lambda query_id: (ndcg_deltas[query_id], query_id))[
        :quartile_size
    ]
    mean_delta = statistics.fmean(ndcg_deltas[query_id] for query_id in worst_query_ids)
    return {
        "query_ids": worst_query_ids,
        "mean_ndcg_delta": mean_delta,
        "floor": NDCG_WORST_QUARTILE_FLOOR,
        "passed": mean_delta >= NDCG_WORST_QUARTILE_FLOOR - EPSILON,
    }


def compare(baseline: dict, candidate: dict, proxy: dict, queries_path: Path) -> dict:
    base_cases = validate_screen(baseline)
    cand_cases = validate_screen(candidate)
    if mismatches := pair_mismatches(baseline, candidate):
        return _ineligible("artefacts judge_screen non comparables", identity_mismatches=mismatches)

    query_ids = list(baseline["expected_query_ids"])
    widths = load_widths(queries_path, query_ids, base_cases)
    qrels = validate_qrels(proxy, query_ids)
    gaps = qrel_gaps(base_cases, qrels)
    if gaps:
        return _ineligible("qrels proxy incomplets", qrel_gaps=gaps)

    base_eval = evaluate_artifact(base_cases, qrels, widths)
    cand_eval = evaluate_artifact(cand_cases, qrels, widths)
    base_global = base_eval["aggregate"]["global"]
    cand_global = cand_eval["aggregate"]["global"]
    global_failures, global_margins, global_deltas = _quality_noninferiority(
        base_global, cand_global
    )
    width_failures = {}
    width_margins = {}
    width_deltas = {}
    for width, base_width in base_eval["aggregate"]["widths"].items():
        failures, margins, deltas = _quality_noninferiority(
            base_width, cand_eval["aggregate"]["widths"][width]
        )
        width_margins[width] = margins
        width_deltas[width] = deltas
        if failures:
            width_failures[width] = failures
    ndcg_deltas = {
        query_id: cand_eval["per_query"][query_id]["mean"]["ndcg_at_10"]
        - base_eval["per_query"][query_id]["mean"]["ndcg_at_10"]
        for query_id in query_ids
    }
    worst_quartile = _worst_quartile_ndcg(ndcg_deltas)
    quality_passed = not global_failures and not width_failures and worst_quartile["passed"]

    base_perf = base_eval["performance"]
    cand_perf = cand_eval["performance"]
    latency_gain = _relative_gain(base_perf["wall_latency_p50_s"], cand_perf["wall_latency_p50_s"])
    token_gain = _relative_gain(base_perf["tokens_mean"], cand_perf["tokens_mean"])
    latency_path = (
        latency_gain + EPSILON >= MIN_EFFICIENCY_GAIN
        and token_gain + EPSILON >= -MAX_OTHER_AXIS_REGRESSION
    )
    token_path = (
        token_gain + EPSILON >= MIN_EFFICIENCY_GAIN
        and latency_gain + EPSILON >= -MAX_OTHER_AXIS_REGRESSION
    )
    efficiency_passed = latency_path or token_path

    if not quality_passed:
        verdict = "reject"
        reason = "non-infériorité proxy du juge échouée"
    elif not efficiency_passed:
        verdict = "reject"
        reason = "gain efficacité insuffisant ou régression >5 % sur l'autre axe"
    else:
        verdict = "keep_screen"
        reason = "non-infériorité proxy et efficacité du screening passées"

    return {
        "schema_version": 1,
        "gate": "judge_screen_proxy",
        "proxy": True,
        "production_promotion": False,
        "verdict": verdict,
        "reason": reason,
        "disclaimer": (
            "Screening sur qrels LLM proxy uniquement : ce verdict ne démontre pas une "
            "qualité clinique et n'autorise aucune promotion en production."
        ),
        "quality_gate": {
            "passed": quality_passed,
            "global_failures": global_failures,
            "global_margins": global_margins,
            "global_deltas": global_deltas,
            "width_failures": width_failures,
            "width_margins": width_margins,
            "width_deltas": width_deltas,
            "worst_quartile": worst_quartile,
        },
        "efficiency_gate": {
            "passed": efficiency_passed,
            "latency_gain": latency_gain,
            "token_gain": token_gain,
            "required_gain": MIN_EFFICIENCY_GAIN,
            "max_other_axis_regression": MAX_OTHER_AXIS_REGRESSION,
            "passed_via": "latency" if latency_path else ("tokens" if token_path else None),
        },
        "widths": widths,
        "ndcg_deltas_per_query": ndcg_deltas,
        "baseline": base_eval,
        "candidate": cand_eval,
    }


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("qrels", type=Path)
    parser.add_argument("queries", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(
            load_json(args.baseline),
            load_json(args.candidate),
            load_json(args.qrels),
            args.queries,
        )
    except JudgeScoreError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    _write_atomic(args.out, result)
    print(json.dumps({"verdict": result["verdict"], "reason": result["reason"]}))


if __name__ == "__main__":
    main()
