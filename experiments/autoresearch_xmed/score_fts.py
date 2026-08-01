"""Scoring proxy strict d'un artefact FTS apparié des rounds 24--26."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_fts_screen import (
    BASELINE_MODE,
    FtsConfig,
    paired_schedule,
)
from experiments.autoresearch_xmed.score_retrieval import (
    DIVERSITY_ENTROPY_MIN_MARGIN,
    DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR,
    DIVERSITY_RELATIVE_MARGIN,
    NDCG_BOOTSTRAP_LOWER_FLOOR,
    NDCG_WORST_QUARTILE_FLOOR,
    NORMALIZED_QUALITY_MARGIN,
    RELEVANT_COUNT_MIN_MARGIN,
    RELEVANT_COUNT_RELATIVE_MARGIN,
    RETRIEVAL_COVERAGE_MIN_MARGIN,
    RETRIEVAL_COVERAGE_WORST_QUARTILE_FLOOR,
    _paired_bootstrap,
)

EPSILON = 1e-12
MIN_PAIRED_LATENCY_GAIN = 0.10
RELEVANT_GRADE = 2
NORMALIZED_KEYS = ("ndcg_at_10", "p_at_10", "recall_at_50")
DIVERSITY_KEYS = (
    "journal_entropy",
    "journal_coverage",
    "year_entropy",
    "year_coverage",
    "evidence_entropy",
    "evidence_coverage",
)
DYNAMIC_SPEC_KEYS = {
    "query_spec_fingerprint",
    "tsquery",
    "tsquery_fingerprint",
    "explain",
}
FORBIDDEN_SQL = (
    " insert ",
    " update ",
    " delete ",
    " alter ",
    " drop ",
    " create ",
    " truncate ",
    " copy ",
    " call ",
)


class FtsScoreError(RuntimeError):
    """Artefact FTS ou qrels impropres à un verdict."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FtsScoreError(f"JSON illisible: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FtsScoreError(f"objet JSON attendu: {path}")
    return value


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _positive_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _validate_explain(value: object, query_id: str) -> None:
    if not isinstance(value, dict) or value.get("analyze") is not False:
        raise FtsScoreError(f"EXPLAIN sans ANALYZE requis: {query_id}")
    plan = value.get("plan")
    shape = value.get("plan_shape")
    if (
        not isinstance(plan, list)
        or not plan
        or not isinstance(shape, dict)
        or value.get("plan_fingerprint") != fingerprint(plan)
        or value.get("plan_shape_fingerprint") != fingerprint(shape)
    ):
        raise FtsScoreError(f"fingerprint EXPLAIN incohérent: {query_id}")


def _validate_spec(spec: object, query_id: str, mode: str, source_table: str) -> None:
    if not isinstance(spec, dict):
        raise FtsScoreError(f"spécification SQL absente: {query_id}/{mode}")
    sql = spec.get("sql")
    padded_sql = f" {str(sql).lower()} "
    if (
        spec.get("mode") != mode
        or spec.get("source_table") != source_table
        or spec.get("sql_kind") != "select_only"
        or not isinstance(sql, str)
        or not sql.startswith("WITH q AS (SELECT ")
        or ";" in sql
        or any(token in padded_sql for token in FORBIDDEN_SQL)
        or spec.get("sql_fingerprint") != fingerprint(sql)
    ):
        raise FtsScoreError(f"SQL FTS non sûr ou incohérent: {query_id}/{mode}")
    identity = {key: value for key, value in spec.items() if key not in DYNAMIC_SPEC_KEYS}
    recorded = identity.pop("query_spec_fingerprint", None)
    if recorded is not None or spec.get("query_spec_fingerprint") != fingerprint(identity):
        raise FtsScoreError(f"query_spec_fingerprint incohérent: {query_id}/{mode}")
    if spec.get("tsquery_fingerprint") != fingerprint(spec.get("tsquery")):
        raise FtsScoreError(f"tsquery_fingerprint incohérent: {query_id}/{mode}")
    _validate_explain(spec.get("explain"), query_id)


def _validate_run(run: object, query_id: str, spec_fingerprint: str, limit: int) -> None:
    if not isinstance(run, dict):
        raise FtsScoreError(f"exécution FTS absente: {query_id}")
    if run.get("query_spec_fingerprint") != spec_fingerprint:
        raise FtsScoreError(f"spécification d'exécution différente: {query_id}")
    if not _positive_number(run.get("search_latency_s")):
        raise FtsScoreError(f"latence FTS invalide: {query_id}")
    metadata_latency = run.get("metadata_latency_s")
    if (
        isinstance(metadata_latency, bool)
        or not isinstance(metadata_latency, (int, float))
        or not math.isfinite(metadata_latency)
        or metadata_latency < 0
    ):
        raise FtsScoreError(f"latence métadonnées invalide: {query_id}")
    if not _identifier(run.get("statement_timeout")):
        raise FtsScoreError(f"statement_timeout non prouvé: {query_id}")
    timed_out = run.get("timed_out")
    pmids = run.get("pmids")
    metadata = run.get("metadata")
    if (
        not isinstance(timed_out, bool)
        or not isinstance(pmids, list)
        or any(isinstance(pmid, bool) or not isinstance(pmid, int) for pmid in pmids)
        or len(pmids) != len(set(pmids))
        or not isinstance(metadata, list)
    ):
        raise FtsScoreError(f"résultat FTS invalide: {query_id}")
    if timed_out:
        if (
            not isinstance(run.get("error"), str)
            or "statement timeout" not in run["error"].lower()
            or pmids
            or metadata
        ):
            raise FtsScoreError(f"timeout FTS non prouvé: {query_id}")
    elif run.get("error") is not None:
        raise FtsScoreError(f"erreur FTS non-timeout: {query_id}")
    metadata_pmids = [row.get("pmid") for row in metadata if isinstance(row, dict)]
    if len(metadata_pmids) != len(metadata) or metadata_pmids != pmids:
        raise FtsScoreError(f"métadonnées PMID incomplètes: {query_id}")
    coverage = run.get("coverage")
    if coverage != {"returned": len(pmids), "limit": limit, "metadata": len(metadata)}:
        raise FtsScoreError(f"couverture incohérente: {query_id}")


def validate_artifact(run: dict) -> tuple[FtsConfig, list[dict]]:
    if run.get("schema_version") != 1 or run.get("artifact_type") != "fts_paired_screen":
        raise FtsScoreError("artefact fts_paired_screen v1 requis")
    if run.get("complete") is not True or run.get("read_only") is not True:
        raise FtsScoreError("artefact FTS incomplet ou non read-only")
    if run.get("calls") != {"network": False, "llm": False, "db_write": False}:
        raise FtsScoreError("le sidecar FTS doit être sans réseau, LLM et écriture DB")
    if run.get("thermal_protocol") != {
        "single_connection": True,
        "warmups_discarded": True,
        "balanced_ab_ba": True,
    }:
        raise FtsScoreError("protocole thermique apparié absent")
    config_raw = run.get("config")
    if not isinstance(config_raw, dict):
        raise FtsScoreError("configuration FTS absente")
    try:
        config = FtsConfig(**config_raw)
    except (TypeError, ValueError) as exc:
        raise FtsScoreError(f"configuration FTS invalide: {exc}") from exc
    if run.get("config_fingerprint") != fingerprint(config_raw):
        raise FtsScoreError("config_fingerprint FTS incohérent")
    if (
        run.get("round")
        != {"prune_frequent": 24, "anchors_and": 25, "title_boost": 26}[config.candidate_mode]
    ):
        raise FtsScoreError("round FTS incohérent")
    if config.candidate_mode == "anchors_and" and not _identifier(run.get("anchor_plan_sha256")):
        raise FtsScoreError("plan d'ancres non identifié")
    for key in (
        "run_id",
        "database",
        "corpus_fingerprint",
        "machine_fingerprint",
        "source_machine_fingerprint",
        "source_run_id",
        "source_artifact_sha256",
        "runner_sha256",
    ):
        if not _identifier(run.get(key)):
            raise FtsScoreError(f"identité FTS absente: {key}")
    if "autoresearch" not in run["database"]:
        raise FtsScoreError("le run FTS ne cible pas un clone autoresearch")

    cases = run.get("cases")
    expected = run.get("expected_query_ids")
    if not isinstance(cases, list) or not cases:
        raise FtsScoreError("aucun cas FTS")
    actual = [case.get("query_id") for case in cases]
    if (
        not isinstance(expected, list)
        or expected != actual
        or len(actual) != len(set(actual))
        or not all(_identifier(value) for value in actual)
    ):
        raise FtsScoreError("query_id FTS incomplets ou désordonnés")

    expected_orders = paired_schedule(config)
    for case in cases:
        query_id = str(case["query_id"])
        if case.get("error") is not None:
            raise FtsScoreError(f"cas FTS en erreur: {query_id}")
        builder = case.get("query_builder")
        if not isinstance(builder, dict) or case.get("query_builder_fingerprint") != fingerprint(
            builder
        ):
            raise FtsScoreError(f"query-builder incohérent: {query_id}")
        source_table = case.get("source_table")
        if source_table not in ("articles", "article_search"):
            raise FtsScoreError(f"source FTS invalide: {query_id}")
        if case.get("eligible") is False:
            if (
                not isinstance(case.get("ineligibility"), dict)
                or not _identifier(case["ineligibility"].get("reason"))
                or case.get("query_specs") != {}
                or case.get("warmups") != []
                or case.get("repetitions") != []
            ):
                raise FtsScoreError(f"inéligibilité FTS mal formée: {query_id}")
            continue
        if case.get("eligible") is not True or case.get("ineligibility") is not None:
            raise FtsScoreError(f"éligibilité FTS ambiguë: {query_id}")
        specs = case.get("query_specs")
        modes = (BASELINE_MODE, config.candidate_mode)
        if not isinstance(specs, dict) or set(specs) != set(modes):
            raise FtsScoreError(f"paire de specs FTS absente: {query_id}")
        for mode in modes:
            _validate_spec(specs[mode], query_id, mode, source_table)
        if config.candidate_mode == "prune_frequent":
            pruning = case.get("pruning")
            if not isinstance(pruning, dict):
                raise FtsScoreError(f"décision de prune absente: {query_id}")
            recorded = pruning.get("fingerprint")
            if recorded != fingerprint(
                {key: value for key, value in pruning.items() if key != "fingerprint"}
            ):
                raise FtsScoreError(f"décision de prune non gelée: {query_id}")
        warmups = case.get("warmups")
        expected_warmups = [
            (warmup, mode) for warmup in range(1, config.warmup_repetitions + 1) for mode in modes
        ]
        if (
            not isinstance(warmups, list)
            or [(row.get("warmup"), row.get("mode")) for row in warmups] != expected_warmups
        ):
            raise FtsScoreError(f"warm-ups FTS incomplets: {query_id}")
        for row in warmups:
            mode = row["mode"]
            _validate_run(
                row.get("result"),
                query_id,
                specs[mode]["query_spec_fingerprint"],
                config.result_limit,
            )
            if row["result"]["timed_out"]:
                raise FtsScoreError(f"warm-up FTS timeout: {query_id}/{mode}")
        repetitions = case.get("repetitions")
        if (
            not isinstance(repetitions, list)
            or len(repetitions) != config.repetitions
            or [row.get("repetition") for row in repetitions]
            != list(range(1, config.repetitions + 1))
            or [row.get("order") for row in repetitions] != expected_orders
        ):
            raise FtsScoreError(f"ordre AB/BA non équilibré: {query_id}")
        observed_pmids = {mode: [] for mode in modes}
        for repetition in repetitions:
            runs = repetition.get("runs")
            if not isinstance(runs, dict) or set(runs) != set(modes):
                raise FtsScoreError(f"runs appariés absents: {query_id}")
            for mode in modes:
                _validate_run(
                    runs[mode],
                    query_id,
                    specs[mode]["query_spec_fingerprint"],
                    config.result_limit,
                )
                if not runs[mode]["timed_out"]:
                    observed_pmids[mode].append(runs[mode]["pmids"])
        for mode, values in observed_pmids.items():
            if values and any(value != values[0] for value in values[1:]):
                raise FtsScoreError(f"top PMID instable: {query_id}/{mode}")
    return config, cases


def validate_qrels(
    proxy: dict, query_ids: list[str], source_artifact_fingerprint: str
) -> dict[str, dict[int, int]]:
    if (
        proxy.get("schema_version") != 1
        or proxy.get("proxy") is not True
        or proxy.get("frozen_before_scoring") is not True
    ):
        raise FtsScoreError("qrels proxy scellés avant scoring requis")
    if proxy.get("source_artifact_fingerprint") != source_artifact_fingerprint:
        raise FtsScoreError("les qrels ne référencent pas cet artefact FTS exact")
    raw = proxy.get("qrels")
    if not isinstance(raw, dict) or set(raw) != set(query_ids):
        raise FtsScoreError("inventaire qrels différent des query_id FTS")
    normalized = {}
    for query_id in query_ids:
        labels = raw[query_id]
        if not isinstance(labels, dict) or not labels:
            raise FtsScoreError(f"qrels vides: {query_id}")
        values = {}
        for raw_pmid, grade in labels.items():
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
                raise FtsScoreError(f"grade qrels invalide: {query_id}/{raw_pmid}")
            try:
                pmid = int(raw_pmid)
            except (TypeError, ValueError) as exc:
                raise FtsScoreError(f"PMID qrels invalide: {query_id}/{raw_pmid}") from exc
            if pmid in values:
                raise FtsScoreError(f"PMID qrels dupliqué: {query_id}/{pmid}")
            values[pmid] = grade
        normalized[query_id] = values
    pool = {query_id: sorted(values) for query_id, values in normalized.items()}
    if proxy.get("pool_fingerprint") != fingerprint(pool):
        raise FtsScoreError("pool qrels scellé incohérent")
    return normalized


def _entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    size = len(values)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def _metrics(run: dict, labels: dict[int, int]) -> dict:
    pmids = run["pmids"]
    metadata = run["metadata"]
    grades10 = [labels[pmid] for pmid in pmids[:10]]
    grades50 = [labels[pmid] for pmid in pmids[:50]]
    ideal_dcg = _dcg(sorted(labels.values(), reverse=True)[:10])
    relevant_total = sum(grade >= RELEVANT_GRADE for grade in labels.values())
    relevant_count = sum(grade >= RELEVANT_GRADE for grade in grades50)
    relevant_rows = [row for row in metadata[:50] if labels[row["pmid"]] >= RELEVANT_GRADE]
    dimensions = {
        "journal": [str(row["journal"]) for row in relevant_rows if row.get("journal")],
        "year": [str(row["pub_year"]) for row in relevant_rows if row.get("pub_year") is not None],
        "evidence": [
            str(row["evidence_level"])
            for row in relevant_rows
            if row.get("evidence_level") is not None
        ],
    }
    diversity = {
        key: value
        for dimension, values in dimensions.items()
        for key, value in (
            (f"{dimension}_entropy", _entropy(values)),
            (f"{dimension}_coverage", float(len(set(values)))),
        )
    }
    return {
        "ndcg_at_10": _dcg(grades10) / ideal_dcg if ideal_dcg else 0.0,
        "p_at_10": sum(grade >= RELEVANT_GRADE for grade in grades10) / 10.0,
        "recall_at_50": relevant_count / relevant_total if relevant_total else 0.0,
        "relevant_count": float(relevant_count),
        "diversity": diversity,
    }


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _aggregate(per_query: dict[str, dict], widths: dict[str, str]) -> dict:
    def summarize(query_ids: list[str]) -> dict:
        rows = [per_query[query_id] for query_id in query_ids]
        return {
            "queries": len(rows),
            **{key: _mean([row[key] for row in rows]) for key in NORMALIZED_KEYS},
            "relevant_count_total": sum(row["relevant_count"] for row in rows),
            "diversity": {
                key: _mean([row["diversity"][key] for row in rows]) for key in DIVERSITY_KEYS
            },
        }

    query_ids = list(per_query)
    return {
        "global": summarize(query_ids),
        "widths": {
            width: summarize([query_id for query_id in query_ids if widths[query_id] == width])
            for width in sorted(set(widths.values()))
        },
    }


def _group_failures(base: dict, candidate: dict) -> list[dict]:
    failures = []
    for key in NORMALIZED_KEYS:
        margin = NORMALIZED_QUALITY_MARGIN
        if candidate[key] + EPSILON < base[key] - margin:
            failures.append(
                {
                    "metric": key,
                    "baseline": base[key],
                    "candidate": candidate[key],
                    "margin": margin,
                }
            )
    relevant_margin = float(
        max(
            RELEVANT_COUNT_MIN_MARGIN,
            math.floor(RELEVANT_COUNT_RELATIVE_MARGIN * base["relevant_count_total"]),
        )
    )
    if candidate["relevant_count_total"] + EPSILON < base["relevant_count_total"] - relevant_margin:
        failures.append(
            {
                "metric": "relevant_count_total",
                "baseline": base["relevant_count_total"],
                "candidate": candidate["relevant_count_total"],
                "margin": relevant_margin,
            }
        )
    for key in DIVERSITY_KEYS:
        margin = (
            max(DIVERSITY_ENTROPY_MIN_MARGIN, DIVERSITY_RELATIVE_MARGIN * base["diversity"][key])
            if "entropy" in key
            else max(
                RETRIEVAL_COVERAGE_MIN_MARGIN, DIVERSITY_RELATIVE_MARGIN * base["diversity"][key]
            )
        )
        if candidate["diversity"][key] + EPSILON < base["diversity"][key] - margin:
            failures.append(
                {
                    "metric": f"diversity.{key}",
                    "baseline": base["diversity"][key],
                    "candidate": candidate["diversity"][key],
                    "margin": margin,
                }
            )
    return failures


def _first_successful(case: dict, mode: str) -> dict | None:
    return next(
        (
            repetition["runs"][mode]
            for repetition in case["repetitions"]
            if not repetition["runs"][mode]["timed_out"]
        ),
        None,
    )


def _ineligible(reason: str, **details) -> dict:
    return {
        "schema_version": 1,
        "gate": "fts_paired_proxy",
        "proxy": True,
        "production_promotion": False,
        "verdict": "ineligible",
        "reason": reason,
        "disclaimer": (
            "Screening FTS sur qrels proxy scellés : aucune vérité clinique ni "
            "promotion production n'est démontrée."
        ),
        **details,
    }


def score(run: dict, proxy: dict) -> dict:
    config, cases = validate_artifact(run)
    ineligible_cases = {
        str(case["query_id"]): case["ineligibility"] for case in cases if case["eligible"] is False
    }
    if ineligible_cases:
        return _ineligible(
            "au moins une transformation FTS est irréalisable sans changer le chemin d'accès",
            ineligible_cases=ineligible_cases,
        )
    query_ids = [str(case["query_id"]) for case in cases]
    modes = (BASELINE_MODE, config.candidate_mode)
    returned_pool = {}
    for case in cases:
        query_id = str(case["query_id"])
        returned_pool[query_id] = sorted(
            {
                pmid
                for repetition in case["repetitions"]
                for mode in modes
                for pmid in repetition["runs"][mode]["pmids"]
            }
        )
    qrels = validate_qrels(proxy, query_ids, fingerprint(run))
    qrel_pool = {query_id: sorted(labels) for query_id, labels in qrels.items()}
    if qrel_pool != returned_pool:
        return _ineligible(
            "pool qrels différent de l'union symétrique baseline/candidat",
            pool_mismatch={
                query_id: {
                    "missing": sorted(set(returned_pool[query_id]) - set(qrel_pool[query_id])),
                    "unexpected": sorted(set(qrel_pool[query_id]) - set(returned_pool[query_id])),
                }
                for query_id in query_ids
                if qrel_pool[query_id] != returned_pool[query_id]
            },
        )

    timeout_counts = {
        mode: {
            str(case["query_id"]): sum(
                repetition["runs"][mode]["timed_out"] for repetition in case["repetitions"]
            )
            for case in cases
        }
        for mode in modes
    }
    baseline_timeouts = sum(timeout_counts[BASELINE_MODE].values())
    candidate_timeouts = sum(timeout_counts[config.candidate_mode].values())
    if baseline_timeouts:
        return _ineligible(
            "latence baseline censurée par timeout; qualité et vitesse non comparables",
            timeout_counts=timeout_counts,
        )

    widths = {str(case["query_id"]): str(case.get("width") or "unspecified") for case in cases}
    quality_per_query = {mode: {} for mode in modes}
    for case in cases:
        query_id = str(case["query_id"])
        for mode in modes:
            selected = _first_successful(case, mode)
            if selected is not None:
                quality_per_query[mode][query_id] = _metrics(selected, qrels[query_id])
    quality_available = all(set(quality_per_query[mode]) == set(query_ids) for mode in modes)
    quality = None
    quality_passed = False
    if quality_available:
        aggregates = {mode: _aggregate(quality_per_query[mode], widths) for mode in modes}
        global_failures = _group_failures(
            aggregates[BASELINE_MODE]["global"],
            aggregates[config.candidate_mode]["global"],
        )
        width_failures = {
            width: failures
            for width in aggregates[BASELINE_MODE]["widths"]
            if (
                failures := _group_failures(
                    aggregates[BASELINE_MODE]["widths"][width],
                    aggregates[config.candidate_mode]["widths"][width],
                )
            )
        }
        ndcg_deltas = [
            quality_per_query[config.candidate_mode][query_id]["ndcg_at_10"]
            - quality_per_query[BASELINE_MODE][query_id]["ndcg_at_10"]
            for query_id in query_ids
        ]
        quartile_size = max(1, math.ceil(len(ndcg_deltas) / 4))
        worst_quartile = statistics.fmean(sorted(ndcg_deltas)[:quartile_size])
        bootstrap = _paired_bootstrap(ndcg_deltas)
        diversity_worst = {}
        diversity_failures = []
        for key in DIVERSITY_KEYS:
            deltas = sorted(
                quality_per_query[config.candidate_mode][query_id]["diversity"][key]
                - quality_per_query[BASELINE_MODE][query_id]["diversity"][key]
                for query_id in query_ids
            )
            value = statistics.fmean(deltas[:quartile_size])
            floor = (
                DIVERSITY_ENTROPY_WORST_QUARTILE_FLOOR
                if "entropy" in key
                else RETRIEVAL_COVERAGE_WORST_QUARTILE_FLOOR
            )
            diversity_worst[key] = {
                "mean_delta": value,
                "floor": floor,
                "passed": value + EPSILON >= floor,
            }
            if value + EPSILON < floor:
                diversity_failures.append(key)
        quality_passed = (
            not global_failures
            and not width_failures
            and worst_quartile + EPSILON >= NDCG_WORST_QUARTILE_FLOOR
            and bootstrap["lower_95"] + EPSILON >= NDCG_BOOTSTRAP_LOWER_FLOOR
            and not diversity_failures
        )
        quality = {
            "passed": quality_passed,
            "margins_source": "score_retrieval.py",
            "per_query": quality_per_query,
            "aggregate": aggregates,
            "global_failures": global_failures,
            "width_failures": width_failures,
            "worst_quartile_ndcg": {
                "mean_delta": worst_quartile,
                "floor": NDCG_WORST_QUARTILE_FLOOR,
            },
            "paired_bootstrap_ndcg": {
                **bootstrap,
                "lower_floor": NDCG_BOOTSTRAP_LOWER_FLOOR,
            },
            "diversity_worst_quartile": diversity_worst,
        }

    gains = []
    by_order = {"baseline_first": [], "candidate_first": []}
    for case in cases:
        query_id = str(case["query_id"])
        for repetition in case["repetitions"]:
            baseline = repetition["runs"][BASELINE_MODE]
            candidate = repetition["runs"][config.candidate_mode]
            if baseline["timed_out"] or candidate["timed_out"]:
                continue
            gain = (baseline["search_latency_s"] - candidate["search_latency_s"]) / baseline[
                "search_latency_s"
            ]
            order_key = (
                "baseline_first" if repetition["order"][0] == BASELINE_MODE else "candidate_first"
            )
            gains.append(
                {
                    "query_id": query_id,
                    "repetition": repetition["repetition"],
                    "gain": gain,
                    "order": order_key,
                }
            )
            by_order[order_key].append(gain)
    order_medians = {
        key: statistics.median(values) if values else None for key, values in by_order.items()
    }
    median_gain = statistics.median([row["gain"] for row in gains]) if gains else None
    thermal_passed = (
        median_gain is not None
        and median_gain + EPSILON >= MIN_PAIRED_LATENCY_GAIN
        and all(
            value is not None and value + EPSILON >= MIN_PAIRED_LATENCY_GAIN
            for value in order_medians.values()
        )
    )
    robustness_passed = candidate_timeouts <= baseline_timeouts

    if not robustness_passed:
        verdict = "reject"
        reason = "la robustesse timeout FTS régresse"
    elif not quality_available or not quality_passed:
        verdict = "reject"
        reason = "la non-infériorité proxy FTS échoue"
    elif not thermal_passed:
        verdict = "reject"
        reason = "le gain apparié thermiquement comparable reste sous 10 %"
    else:
        verdict = "keep_screen"
        reason = "non-infériorité proxy, robustesse et gain apparié FTS passés"
    return {
        "schema_version": 1,
        "gate": "fts_paired_proxy",
        "proxy": True,
        "production_promotion": False,
        "verdict": verdict,
        "reason": reason,
        "disclaimer": (
            "Screening FTS sur qrels proxy scellés : aucune vérité clinique ni "
            "promotion production n'est démontrée."
        ),
        "symmetric_pool": True,
        "pool_fingerprint": proxy["pool_fingerprint"],
        "quality_gate": quality,
        "robustness_gate": {
            "passed": robustness_passed,
            "timeout_counts": timeout_counts,
        },
        "efficiency_gate": {
            "passed": thermal_passed,
            "required_gain": MIN_PAIRED_LATENCY_GAIN,
            "median_paired_gain": median_gain,
            "median_by_order": order_medians,
            "pairs": gains,
            "warmups_excluded": True,
        },
    }


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("qrels", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = score(load_json(args.artifact), load_json(args.qrels))
    except FtsScoreError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    _write_atomic(args.out, result)
    print(json.dumps({"verdict": result["verdict"], "reason": result["reason"]}))


if __name__ == "__main__":
    main()
