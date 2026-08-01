"""Sidecar apparié des rounds FTS 24--26, sans réseau, LLM ni écriture DB.

La baseline OR et une seule variante sont exécutées sur la même connexion au
clone autoresearch, après un warm-up jeté, dans un ordre AB/BA équilibré. Les
transformations sont préparées une fois avant les répétitions puis fingerprintées :
elles ne peuvent donc pas changer d'identité selon l'ordre ou la température.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.api.search import LOCAL_SEARCH_TIMEOUT_MS, _year
from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_live_baseline import (
    _database_url,
    _machine_fingerprint,
    _validate_clone,
    _write_atomic,
)
from experiments.autoresearch_xmed.run_retrieval_screen import validate_live_source
from experiments.autoresearch_xmed.score import InvalidArtifact, load_json

BASELINE_MODE = "baseline_or"
CANDIDATE_MODES = ("prune_frequent", "anchors_and", "title_boost")
SOURCE_TABLES = ("articles", "article_search")
ROUND_BY_MODE = {"prune_frequent": 24, "anchors_and": 25, "title_boost": 26}
SQL_KIND = "select_only"


class FtsScreenError(RuntimeError):
    """Entrée ou transformation FTS non démontrable."""


@dataclass(frozen=True)
class FtsConfig:
    candidate_mode: str
    result_limit: int = 50
    repetitions: int = 4
    warmup_repetitions: int = 1
    statement_timeout_ms: int = LOCAL_SEARCH_TIMEOUT_MS
    max_est_selectivity: float = 0.05
    title_boost_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.candidate_mode not in CANDIDATE_MODES:
            raise ValueError(f"candidate_mode doit être dans {CANDIDATE_MODES}")
        for name in ("result_limit", "warmup_repetitions", "statement_timeout_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} doit être un entier strictement positif")
        if (
            isinstance(self.repetitions, bool)
            or not isinstance(self.repetitions, int)
            or self.repetitions < 4
            or self.repetitions % 2
        ):
            raise ValueError("repetitions doit être un entier pair >= 4")
        if (
            isinstance(self.max_est_selectivity, bool)
            or not isinstance(self.max_est_selectivity, (int, float))
            or not math.isfinite(self.max_est_selectivity)
            or not 0 < self.max_est_selectivity < 1
        ):
            raise ValueError("max_est_selectivity doit être dans ]0, 1[")
        if (
            isinstance(self.title_boost_weight, bool)
            or not isinstance(self.title_boost_weight, (int, float))
            or not math.isfinite(self.title_boost_weight)
            or self.title_boost_weight <= 0
        ):
            raise ValueError("title_boost_weight doit être strictement positif")


def validate_fts_source(run: dict) -> list[dict]:
    """Ajoute aux contrôles live les identités nécessaires au sidecar DB-only."""

    cases = validate_live_source(run)
    for key in ("run_id", "corpus_fingerprint", "machine_fingerprint"):
        if not isinstance(run.get(key), str) or not run[key]:
            raise InvalidArtifact(f"identité live absente: {key}")
    experiment = run.get("experiment")
    if not isinstance(experiment, dict) or not isinstance(
        experiment.get("use_narrow_search"), bool
    ):
        raise InvalidArtifact("routage FTS live non capturé")
    for case in cases:
        keywords = case["external"]["query_builder"]["data"]["keywords_en"]
        if not keywords or any(not value.strip() for value in keywords):
            raise InvalidArtifact(f"keywords_en vides: {case['query_id']}")
        if len(keywords) != len(set(keywords)):
            raise InvalidArtifact(f"keywords_en dupliqués: {case['query_id']}")
    return cases


def choose_source_table(case: dict, *, use_narrow_search: bool, min_year: int) -> str:
    year_from = _year(case.get("date_from"))
    if use_narrow_search and year_from is not None and year_from >= min_year:
        return "article_search"
    return "articles"


def load_anchor_plan(path: Path, cases: list[dict]) -> dict[str, list[list[str]]]:
    """Charge un partitionnement explicite; aucune structure n'est inférée."""

    try:
        raw_bytes = path.read_bytes()
        plan = json.loads(raw_bytes)
    except (OSError, ValueError) as exc:
        raise FtsScreenError(f"plan d'ancres illisible: {path}") from exc
    expected_ids = [str(case["query_id"]) for case in cases]
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != 1
        or plan.get("mode") != "anchors_and"
        or plan.get("frozen_before_qrels") is not True
        or plan.get("expected_query_ids") != expected_ids
        or plan.get("sha256") != hashlib.sha256(raw_bytes_without_sha(plan)).hexdigest()
    ):
        raise FtsScreenError("plan d'ancres non scellé ou d'identité incorrecte")
    raw_queries = plan.get("queries")
    if not isinstance(raw_queries, dict) or set(raw_queries) != set(expected_ids):
        raise FtsScreenError("inventaire du plan d'ancres incomplet")

    out = {}
    for case in cases:
        query_id = str(case["query_id"])
        builder = case["external"]["query_builder"]["data"]
        row = raw_queries[query_id]
        groups = row.get("groups") if isinstance(row, dict) else None
        if (
            not isinstance(groups, list)
            or len(groups) < 2
            or any(not isinstance(group, list) or not group for group in groups)
            or [term for group in groups for term in group] != builder["keywords_en"]
            or row.get("query_builder_fingerprint") != fingerprint(builder)
        ):
            raise FtsScreenError(f"groupes d'ancres ambigus: {query_id}")
        out[query_id] = groups
    return out


def raw_bytes_without_sha(plan: dict) -> bytes:
    payload = {key: value for key, value in plan.items() if key != "sha256"}
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()


def seal_anchor_plan(plan: dict) -> dict:
    """Helper déterministe destiné à la préparation manuelle du plan."""

    sealed = {key: value for key, value in plan.items() if key != "sha256"}
    sealed["sha256"] = hashlib.sha256(raw_bytes_without_sha(sealed)).hexdigest()
    return sealed


def _date_sql(case: dict) -> tuple[str, dict]:
    clauses = []
    params = {}
    if (year_from := _year(case.get("date_from"))) is not None:
        clauses.append("s.pub_year >= :year_from")
        params["year_from"] = year_from
    if (year_to := _year(case.get("date_to"))) is not None:
        clauses.append("s.pub_year <= :year_to")
        params["year_to"] = year_to
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def _or_expression(terms: list[str]) -> tuple[str, dict]:
    return "websearch_to_tsquery('english', :query_text)", {"query_text": " OR ".join(terms)}


def _anchor_expression(groups: list[list[str]]) -> tuple[str, dict]:
    params = {}
    expressions = []
    for group_index, group in enumerate(groups):
        synonyms = []
        for term_index, term in enumerate(group):
            key = f"anchor_{group_index}_{term_index}"
            params[key] = term
            synonyms.append(f"phraseto_tsquery('english', :{key})")
        expressions.append("(" + " || ".join(synonyms) + ")")
    return "(" + " && ".join(expressions) + ")", params


def build_query_spec(
    case: dict,
    mode: str,
    source_table: str,
    *,
    terms: list[str] | None = None,
    anchor_groups: list[list[str]] | None = None,
    title_boost_weight: float = 1.0,
) -> dict:
    if source_table not in SOURCE_TABLES:
        raise FtsScreenError(f"table source interdite: {source_table}")
    builder = case["external"]["query_builder"]["data"]
    selected_terms = terms if terms is not None else builder["keywords_en"]
    if mode in (BASELINE_MODE, "prune_frequent"):
        if not selected_terms:
            raise FtsScreenError("aucun terme FTS conservé")
        tsquery_sql, params = _or_expression(selected_terms)
    elif mode == "anchors_and":
        if not anchor_groups:
            raise FtsScreenError("plan d'ancres explicite requis")
        tsquery_sql, params = _anchor_expression(anchor_groups)
    elif mode == "title_boost":
        if source_table != "articles":
            raise FtsScreenError(
                "boost titre inéligible sur article_search: la colonne title est absente"
            )
        tsquery_sql, params = _or_expression(selected_terms)
    else:
        raise FtsScreenError(f"mode FTS inconnu: {mode}")

    date_sql, date_params = _date_sql(case)
    params.update(date_params)
    params["result_limit"] = 0  # remplacé par la config avant exécution
    rank_sql = "ts_rank(s.fts, q.value)"
    cost = {"extra_runtime_expression": False, "new_schema_or_index": False}
    if mode == "title_boost":
        rank_sql += (
            " + :title_boost_weight * "
            "ts_rank(to_tsvector('english', coalesce(s.title, '')), q.value)"
        )
        params["title_boost_weight"] = title_boost_weight
        cost["extra_runtime_expression"] = True
    sql = (
        f"WITH q AS (SELECT {tsquery_sql} AS value) "
        f"SELECT s.pmid, {rank_sql} AS rank FROM {source_table} AS s CROSS JOIN q "
        f"WHERE s.fts @@ q.value{date_sql} "
        "ORDER BY rank DESC, s.pmid ASC LIMIT :result_limit"
    )
    tsquery_probe_sql = f"SELECT ({tsquery_sql})::text"
    identity = {
        "mode": mode,
        "source_table": source_table,
        "sql_kind": SQL_KIND,
        "sql": sql,
        "sql_fingerprint": fingerprint(sql),
        "tsquery_probe_sql": tsquery_probe_sql,
        "params_without_limit": {
            key: value for key, value in params.items() if key != "result_limit"
        },
        "terms": selected_terms,
        "anchor_groups": anchor_groups,
        "cost": cost,
    }
    identity["query_spec_fingerprint"] = fingerprint(identity)
    return identity


def _plan_shape(node: dict) -> dict:
    keys = ("Node Type", "Relation Name", "Index Name", "Join Type", "Strategy")
    shape = {key: node[key] for key in keys if key in node}
    if isinstance(node.get("Plans"), list):
        shape["Plans"] = [_plan_shape(child) for child in node["Plans"]]
    return shape


def explain_spec(connection, spec: dict, result_limit: int) -> dict:
    params = {**spec["params_without_limit"], "result_limit": result_limit}
    row = connection.scalar(
        text("EXPLAIN (FORMAT JSON, ANALYZE FALSE, COSTS TRUE, SUMMARY FALSE) " + spec["sql"]),
        params,
    )
    plan = json.loads(row) if isinstance(row, str) else row
    if not isinstance(plan, list) or not plan or not isinstance(plan[0], dict):
        raise FtsScreenError("plan EXPLAIN JSON invalide")
    root = plan[0].get("Plan")
    if not isinstance(root, dict):
        raise FtsScreenError("racine du plan EXPLAIN absente")
    shape = _plan_shape(root)
    return {
        "analyze": False,
        "plan": plan,
        "plan_fingerprint": fingerprint(plan),
        "plan_shape": shape,
        "plan_shape_fingerprint": fingerprint(shape),
    }


def freeze_pruning(
    connection,
    case: dict,
    source_table: str,
    max_est_selectivity: float,
) -> dict:
    """Gèle les décisions depuis les estimations planner, hors chronométrage."""

    if source_table not in SOURCE_TABLES:
        raise FtsScreenError("table source interdite")
    source_rows = connection.scalar(
        text("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:table_name)"),
        {"table_name": f"public.{source_table}"},
    )
    if isinstance(source_rows, bool) or not isinstance(source_rows, int) or source_rows <= 0:
        raise FtsScreenError("estimation du nombre de lignes source invalide")
    date_sql, date_params = _date_sql(case)
    decisions = []
    builder = case["external"]["query_builder"]["data"]
    for term in builder["keywords_en"]:
        sql = (
            f"SELECT 1 FROM {source_table} AS s WHERE "
            f"s.fts @@ websearch_to_tsquery('english', :term){date_sql}"
        )
        raw_plan = connection.scalar(
            text("EXPLAIN (FORMAT JSON, ANALYZE FALSE, COSTS TRUE, SUMMARY FALSE) " + sql),
            {"term": term, **date_params},
        )
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        try:
            estimated_rows = int(plan[0]["Plan"]["Plan Rows"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise FtsScreenError("cardinalité planner absente") from exc
        selectivity = estimated_rows / source_rows
        decisions.append(
            {
                "term": term,
                "estimated_rows": estimated_rows,
                "estimated_selectivity": selectivity,
                "kept": selectivity <= max_est_selectivity,
                "explain_analyze": False,
            }
        )
    frozen = {
        "method": "planner_estimated_selectivity_explain_without_analyze",
        "leakage_inputs": "captured_keywords_and_corpus_statistics_only",
        "max_est_selectivity": max_est_selectivity,
        "source_rows_estimate": source_rows,
        "decisions": decisions,
    }
    frozen["fingerprint"] = fingerprint(frozen)
    return frozen


def _metadata(connection, pmids: list[int]) -> tuple[list[dict], float]:
    if not pmids:
        return [], 0.0
    started = time.monotonic()
    with connection.begin():
        rows = connection.execute(
            text(
                "SELECT pmid, title, journal, pub_year, evidence_level FROM articles "
                "WHERE pmid = ANY(:pmids)"
            ),
            {"pmids": pmids},
        ).mappings()
        by_pmid = {int(row["pmid"]): dict(row) for row in rows}
    return [by_pmid[pmid] for pmid in pmids if pmid in by_pmid], time.monotonic() - started


def execute_spec(connection, spec: dict, config: FtsConfig) -> dict:
    params = {**spec["params_without_limit"], "result_limit": config.result_limit}
    started = time.monotonic()
    timeout_setting = None
    try:
        with connection.begin():
            connection.scalar(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{config.statement_timeout_ms}ms"},
            )
            timeout_setting = connection.scalar(text("SHOW statement_timeout"))
            rows = connection.execute(text(spec["sql"]), params).mappings().all()
    except OperationalError as exc:
        elapsed = time.monotonic() - started
        timed_out = "statement timeout" in str(exc).lower()
        return {
            "query_spec_fingerprint": spec["query_spec_fingerprint"],
            "search_latency_s": elapsed,
            "metadata_latency_s": 0.0,
            "statement_timeout": timeout_setting,
            "timed_out": timed_out,
            "error": f"{type(exc).__name__}: {exc}",
            "pmids": [],
            "metadata": [],
            "coverage": {"returned": 0, "limit": config.result_limit, "metadata": 0},
        }
    elapsed = time.monotonic() - started
    pmids = [int(row["pmid"]) for row in rows]
    metadata, metadata_latency = _metadata(connection, pmids)
    return {
        "query_spec_fingerprint": spec["query_spec_fingerprint"],
        "search_latency_s": elapsed,
        "metadata_latency_s": metadata_latency,
        "statement_timeout": timeout_setting,
        "timed_out": False,
        "error": None,
        "pmids": pmids,
        "metadata": metadata,
        "coverage": {
            "returned": len(pmids),
            "limit": config.result_limit,
            "metadata": len(metadata),
        },
    }


RunSpec = Callable[[str, dict], dict]


def paired_schedule(config: FtsConfig) -> list[list[str]]:
    modes = [BASELINE_MODE, config.candidate_mode]
    return [
        modes if index % 2 == 0 else list(reversed(modes)) for index in range(config.repetitions)
    ]


def run_paired_specs(specs: dict[str, dict], config: FtsConfig, execute: RunSpec) -> dict:
    expected = {BASELINE_MODE, config.candidate_mode}
    if set(specs) != expected:
        raise FtsScreenError("les deux spécifications FTS sont requises")
    warmups = []
    for warmup in range(1, config.warmup_repetitions + 1):
        for mode in (BASELINE_MODE, config.candidate_mode):
            warmups.append({"warmup": warmup, "mode": mode, "result": execute(mode, specs[mode])})
    repetitions = []
    for repetition, order in enumerate(paired_schedule(config), 1):
        runs = {mode: execute(mode, specs[mode]) for mode in order}
        repetitions.append({"repetition": repetition, "order": order, "runs": runs})
    return {"warmups": warmups, "repetitions": repetitions}


def _prepare_case(
    connection,
    case: dict,
    config: FtsConfig,
    source_table: str,
    anchor_groups: list[list[str]] | None,
) -> tuple[dict[str, dict], dict | None]:
    builder = case["external"]["query_builder"]["data"]
    baseline = build_query_spec(case, BASELINE_MODE, source_table)
    pruning = None
    if config.candidate_mode == "prune_frequent":
        pruning = freeze_pruning(connection, case, source_table, config.max_est_selectivity)
        terms = [row["term"] for row in pruning["decisions"] if row["kept"]]
        candidate = build_query_spec(case, config.candidate_mode, source_table, terms=terms)
    elif config.candidate_mode == "anchors_and":
        candidate = build_query_spec(
            case, config.candidate_mode, source_table, anchor_groups=anchor_groups
        )
    else:
        candidate = build_query_spec(
            case,
            config.candidate_mode,
            source_table,
            title_boost_weight=config.title_boost_weight,
        )
    for spec in (baseline, candidate):
        spec["tsquery"] = connection.scalar(
            text(spec["tsquery_probe_sql"]), spec["params_without_limit"]
        )
        spec["tsquery_fingerprint"] = fingerprint(spec["tsquery"])
        spec["explain"] = explain_spec(connection, spec, config.result_limit)
    if not set(candidate["terms"]).issubset(builder["keywords_en"]):
        raise FtsScreenError("la variante introduit un terme hors query-builder")
    return {BASELINE_MODE: baseline, config.candidate_mode: candidate}, pruning


def run_case(
    connection,
    case: dict,
    config: FtsConfig,
    *,
    use_narrow_search: bool,
    min_year: int,
    anchor_groups: list[list[str]] | None,
) -> dict:
    query_id = str(case["query_id"])
    source_table = choose_source_table(case, use_narrow_search=use_narrow_search, min_year=min_year)
    common = {
        "query_id": query_id,
        "query": case["query"],
        "width": case.get("width"),
        "date_from": case.get("date_from"),
        "date_to": case.get("date_to"),
        "source_table": source_table,
        "query_builder": case["external"]["query_builder"]["data"],
        "query_builder_fingerprint": fingerprint(case["external"]["query_builder"]["data"]),
    }
    if config.candidate_mode == "title_boost" and source_table != "articles":
        return {
            **common,
            "eligible": False,
            "ineligibility": {
                "reason": "title_absent_from_article_search",
                "cost": (
                    "Un JOIN vers articles changerait le chemin d'accès; aucun schéma/index "
                    "nouveau n'est autorisé par ce sidecar."
                ),
            },
            "query_specs": {},
            "warmups": [],
            "repetitions": [],
            "error": None,
        }
    try:
        with connection.begin():
            specs, pruning = _prepare_case(connection, case, config, source_table, anchor_groups)
    except FtsScreenError as exc:
        return {
            **common,
            "eligible": False,
            "ineligibility": {"reason": str(exc), "cost": None},
            "query_specs": {},
            "warmups": [],
            "repetitions": [],
            "error": None,
        }
    paired = run_paired_specs(
        specs, config, lambda _mode, spec: execute_spec(connection, spec, config)
    )
    return {
        **common,
        "eligible": True,
        "ineligibility": None,
        "pruning": pruning,
        "query_specs": specs,
        **paired,
        "error": None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="artefact live complet et validé")
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=CANDIDATE_MODES, required=True)
    parser.add_argument("--anchor-plan", type=Path)
    parser.add_argument("--result-limit", type=int, default=50)
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument("--warmup-repetitions", type=int, default=1)
    parser.add_argument("--statement-timeout-ms", type=int, default=LOCAL_SEARCH_TIMEOUT_MS)
    parser.add_argument("--max-est-selectivity", type=float, default=0.05)
    parser.add_argument("--title-boost-weight", type=float, default=1.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = FtsConfig(
            candidate_mode=args.mode,
            result_limit=args.result_limit,
            repetitions=args.repetitions,
            warmup_repetitions=args.warmup_repetitions,
            statement_timeout_ms=args.statement_timeout_ms,
            max_est_selectivity=args.max_est_selectivity,
            title_boost_weight=args.title_boost_weight,
        )
    except ValueError as exc:
        raise SystemExit(f"REFUS: configuration FTS invalide ({exc})") from exc
    if "autoresearch" not in args.database:
        raise SystemExit("REFUS: la base doit contenir 'autoresearch'")
    try:
        source = load_json(args.source)
        cases = validate_fts_source(source)
    except (OSError, ValueError, InvalidArtifact) as exc:
        raise SystemExit(f"REFUS: artefact live invalide ({exc})") from exc
    if config.candidate_mode == "anchors_and" and args.anchor_plan is None:
        raise SystemExit("REFUS: --anchor-plan est obligatoire pour anchors_and")
    if config.candidate_mode != "anchors_and" and args.anchor_plan is not None:
        raise SystemExit("REFUS: --anchor-plan n'est accepté que pour anchors_and")
    try:
        anchors = load_anchor_plan(args.anchor_plan, cases) if args.anchor_plan else {}
    except FtsScreenError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc

    engine = create_engine(
        _database_url(args.database),
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    config_json = asdict(config)
    output = {
        "schema_version": 1,
        "artifact_type": "fts_paired_screen",
        "run_id": f"fts-round-{ROUND_BY_MODE[config.candidate_mode]}-{time.time_ns()}",
        "round": ROUND_BY_MODE[config.candidate_mode],
        "complete": False,
        "expected_query_ids": [str(case["query_id"]) for case in cases],
        "database": args.database,
        "corpus_fingerprint": source["corpus_fingerprint"],
        "machine_fingerprint": _machine_fingerprint(),
        "source_machine_fingerprint": source["machine_fingerprint"],
        "source_run_id": source["run_id"],
        "source_artifact_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "read_only": True,
        "config": config_json,
        "config_fingerprint": fingerprint(config_json),
        "anchor_plan_sha256": hashlib.sha256(args.anchor_plan.read_bytes()).hexdigest()
        if args.anchor_plan
        else None,
        "calls": {"network": False, "llm": False, "db_write": False},
        "thermal_protocol": {
            "single_connection": True,
            "warmups_discarded": True,
            "balanced_ab_ba": True,
        },
        "cases": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(args.out, output)
    try:
        with engine.connect() as connection:
            clone_metadata, clone_fingerprint = _validate_clone(
                connection,
                args.database,
                allow_recent=source.get("corpus_scope") == "recent",
            )
            if clone_fingerprint != source["corpus_fingerprint"]:
                raise SystemExit("REFUS: le clone ne correspond pas à l'artefact live")
            min_year = connection.scalar(text("SELECT article_search_min_year()"))
            if isinstance(min_year, bool) or not isinstance(min_year, int):
                raise SystemExit("REFUS: article_search_min_year() invalide")
            connection.rollback()
            output["clone_metadata"] = clone_metadata
            output["article_search_min_year"] = min_year
            for case in cases:
                result = run_case(
                    connection,
                    case,
                    config,
                    use_narrow_search=source["experiment"]["use_narrow_search"],
                    min_year=min_year,
                    anchor_groups=anchors.get(str(case["query_id"])),
                )
                output["cases"].append(result)
                _write_atomic(args.out, output)
    finally:
        engine.dispose()
    output["complete"] = True
    _write_atomic(args.out, output)


if __name__ == "__main__":
    main()
