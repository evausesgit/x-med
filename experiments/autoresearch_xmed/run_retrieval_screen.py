"""Screening retrieval des rounds 11-20, sans juge LLM ni traduction.

Le query-builder n'est jamais rappelé : sa sortie est reprise, vérifiée et
fingerprintée depuis un artefact live complet. PubMed ``esearch`` peut en revanche
être relancé avec une fenêtre ``k_pubmed`` différente. Le FTS et l'hydratation
s'exécutent uniquement sur un clone ``autoresearch`` ouvert en lecture seule.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.api import search as search_api
from app.config import settings
from app.services import pubmed_eutils
from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.run_live_baseline import (
    _database_url,
    _machine_fingerprint,
    _validate_clone,
    _write_atomic,
)
from experiments.autoresearch_xmed.score import InvalidArtifact, load_json


@dataclass(frozen=True)
class RetrievalConfig:
    """Knobs autorisés pendant le screening retrieval."""

    k_pubmed: int = 20
    max_local: int = 200
    judge_batch: int = 50
    rrf: bool = False
    rrf_k: int = 60
    local_floor: int = 0
    use_narrow_search: bool = False

    def __post_init__(self) -> None:
        positive = ("k_pubmed", "judge_batch", "rrf_k")
        nonnegative = ("max_local", "local_floor")
        for name in positive:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} doit être un entier strictement positif")
        for name in nonnegative:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} doit être un entier positif ou nul")
        for name in ("rrf", "use_narrow_search"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} doit être booléen")


def validate_live_source(run: dict) -> list[dict]:
    """Valide le contrat plus strict requis par un screening retrieval.

    ``score.load_json`` vérifie déjà complétude et unicité. Ici on refuse aussi
    les cas live dégradés : ils ne prouvent pas quelle sortie query-builder a été
    réellement utilisée.
    """

    if run.get("run_kind") != "live" or run.get("complete") is not True:
        raise InvalidArtifact("la source doit être un artefact live complet")
    if run.get("read_only") is not True:
        raise InvalidArtifact("la source live ne prouve pas une exécution read-only")
    database = run.get("database")
    if not isinstance(database, str) or "autoresearch" not in database:
        raise InvalidArtifact("la source live ne provient pas d'un clone autoresearch")

    cases = run.get("cases")
    if not isinstance(cases, list) or not cases:
        raise InvalidArtifact("la source live ne contient aucun cas")
    expected = run.get("expected_query_ids")
    actual = [case.get("query_id") for case in cases]
    if (
        not isinstance(expected, list)
        or not all(isinstance(value, str) and value for value in expected)
        or expected != actual
        or len(actual) != len(set(actual))
    ):
        raise InvalidArtifact("les query_id live ne correspondent pas exactement")

    for case in cases:
        query_id = str(case.get("query_id"))
        if case.get("error"):
            raise InvalidArtifact(f"cas live dégradé interdit: {query_id}")
        external = case.get("external")
        captured = external.get("query_builder") if isinstance(external, dict) else None
        builder = captured.get("data") if isinstance(captured, dict) else None
        if not isinstance(builder, dict):
            raise InvalidArtifact(f"sortie query-builder absente: {query_id}")
        if not isinstance(builder.get("pubmed_query"), str) or not builder["pubmed_query"].strip():
            raise InvalidArtifact(f"pubmed_query absente: {query_id}")
        for key in ("mesh_terms", "keywords_en"):
            values = builder.get(key)
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise InvalidArtifact(f"{key} query-builder invalide: {query_id}")
        for key in ("pubmed_query", "mesh_terms", "keywords_en"):
            if case.get(key) != builder[key]:
                raise InvalidArtifact(f"capture query-builder incohérente ({key}): {query_id}")
    return cases


def select_batch(
    pubmed_pmids: list[int],
    local_pmids: list[int],
    abstract_pmids: set[int],
    config: RetrievalConfig,
) -> tuple[list[int], list[int], list[int]]:
    """Retourne candidats, jugeables et lot, dans leur ordre exact."""

    candidates = search_api._candidate_order(pubmed_pmids, local_pmids, config.rrf, k=config.rrf_k)
    judgeable = [pmid for pmid in candidates if pmid in abstract_pmids]
    selected = search_api._pick_judge_batch(
        judgeable,
        set(pubmed_pmids),
        config.judge_batch,
        config.local_floor,
    )
    return candidates, judgeable, selected


def validate_screen_case(case: dict) -> None:
    """Refuse toute ambiguïté d'identité dans un lot prêt à juger."""

    candidates = case.get("candidate_pmids")
    judgeable = case.get("judgeable_pmids")
    selected = case.get("judge_pmids")
    judge_items = case.get("judge_items")
    metadata = case.get("selected_metadata")
    for name, values in (
        ("candidate_pmids", candidates),
        ("judgeable_pmids", judgeable),
        ("judge_pmids", selected),
    ):
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
            raise ValueError(f"{name} doit être une liste de PMID entiers")
        if len(values) != len(set(values)):
            raise ValueError(f"{name} contient des doublons")
    if not set(judgeable).issubset(candidates) or not set(selected).issubset(judgeable):
        raise ValueError("hiérarchie candidate/judgeable/judge incohérente")
    if not isinstance(judge_items, list) or not isinstance(metadata, list):
        raise ValueError("métadonnées du lot absentes")
    if [item.get("pmid") for item in judge_items] != selected:
        raise ValueError("judge_items ne correspond pas exactement à judge_pmids")
    if [item.get("pmid") for item in metadata] != selected:
        raise ValueError("selected_metadata ne correspond pas exactement à judge_pmids")


def _local_search(
    case: dict, builder: dict, config: RetrievalConfig, corpus
) -> tuple[list[int], dict]:
    started = time.monotonic()
    query_text = " OR ".join(builder["keywords_en"]) or case["query"]
    tsquery = func.websearch_to_tsquery("english", query_text)
    with patch.object(settings, "use_narrow_search", config.use_narrow_search):
        source = search_api._prefilter_source(corpus, case.get("date_from"))

    conditions = [source.fts.op("@@")(tsquery)]
    year_from = search_api._year(case.get("date_from"))
    year_to = search_api._year(case.get("date_to"))
    if year_from is not None:
        conditions.append(source.pub_year >= year_from)
    if year_to is not None:
        conditions.append(source.pub_year <= year_to)

    timed_out = False
    error = None
    try:
        corpus.execute(
            text(f"SET LOCAL statement_timeout = '{search_api.LOCAL_SEARCH_TIMEOUT_MS}ms'")
        )
        pmids = list(
            corpus.scalars(
                select(source.pmid)
                .where(*conditions)
                .order_by(func.ts_rank(source.fts, tsquery).desc())
                .limit(config.max_local)
            ).all()
        )
    except OperationalError as exc:
        corpus.rollback()
        pmids = []
        timed_out = "statement timeout" in str(exc).lower()
        error = f"{type(exc).__name__}: {exc}"
    else:
        corpus.commit()
    return pmids, {
        "source": source.__tablename__,
        "timed_out": timed_out,
        "error": error,
        "elapsed_s": time.monotonic() - started,
    }


def _article_payload(
    pmid: int,
    db: dict,
    meta: dict,
    abstracts: dict,
    sources: tuple[set[int], set[int]],
) -> dict:
    pubmed_set, local_set = sources
    article = db.get(pmid)
    summary = meta.get(pmid)
    if pmid in pubmed_set and pmid in local_set:
        source = "both"
    elif pmid in pubmed_set:
        source = "pubmed"
    else:
        source = "local"
    return {
        "pmid": pmid,
        "title": article.title if article else (summary.title if summary else str(pmid)),
        "abstract": article.abstract if article else abstracts.get(pmid),
        "journal": article.journal if article else (summary.journal if summary else None),
        "pub_year": article.pub_year if article else (summary.pub_year if summary else None),
        "evidence_level": article.evidence_level if article else None,
        "doi": article.doi if article else (summary.doi if summary else None),
        "source": source,
        "in_db": article is not None,
    }


def screen_case(case: dict, config: RetrievalConfig, session_factory) -> dict:
    """Exécute retrieval + hydratation et s'arrête juste avant ``judge_articles``."""

    total_started = time.monotonic()
    builder = case["external"]["query_builder"]["data"]
    timings: dict[str, float] = {}

    started = time.monotonic()
    pubmed_total, pubmed_pmids = pubmed_eutils.esearch(
        builder["pubmed_query"],
        retmax=config.k_pubmed,
        mindate=case.get("date_from"),
        maxdate=case.get("date_to"),
    )
    timings["esearch_s"] = time.monotonic() - started

    with session_factory() as corpus:
        local_pmids, local_status = _local_search(case, builder, config, corpus)
        timings["local_fts_s"] = local_status["elapsed_s"]

        pubmed_set = set(pubmed_pmids)
        local_set = set(local_pmids)
        ordered = search_api._candidate_order(pubmed_pmids, local_pmids, config.rrf, k=config.rrf_k)

        started = time.monotonic()
        db = search_api._fetch_articles(corpus, ordered)
        timings["clone_hydration_s"] = time.monotonic() - started

        started = time.monotonic()
        local_dropped = 0
        local_unverified = 0
        if case.get("date_from") or case.get("date_to"):
            windowed = []
            for pmid in ordered:
                article = db.get(pmid)
                if pmid in pubmed_set or article is None:
                    windowed.append(pmid)
                    continue
                keep, unverified = search_api._window_keep(
                    article.pub_date,
                    article.pub_year,
                    case.get("date_from"),
                    case.get("date_to"),
                )
                local_unverified += int(keep and unverified)
                if keep:
                    windowed.append(pmid)
                else:
                    local_dropped += 1
            ordered = windowed
            local_set &= set(windowed)
        timings["window_filter_s"] = time.monotonic() - started

    missing = [pmid for pmid in pubmed_pmids if pmid not in db]
    hydration_errors: dict[str, str] = {}
    started = time.monotonic()
    try:
        metadata = pubmed_eutils.esummary(missing)
    except Exception as exc:  # best-effort identique à la production
        metadata = {}
        hydration_errors["esummary"] = f"{type(exc).__name__}: {exc}"
    try:
        abstracts = pubmed_eutils.efetch_abstracts(missing)
    except Exception as exc:  # best-effort identique à la production
        abstracts = {}
        hydration_errors["efetch"] = f"{type(exc).__name__}: {exc}"
    timings["ncbi_hydration_s"] = time.monotonic() - started

    started = time.monotonic()
    payloads = {
        pmid: _article_payload(
            pmid,
            db,
            metadata,
            abstracts,
            (pubmed_set, local_set),
        )
        for pmid in ordered
    }
    abstract_pmids = {
        pmid for pmid, article in payloads.items() if (article.get("abstract") or "").strip()
    }
    # L'ordre a été fusionné avant le contrôle de fenêtre, comme en production :
    # retirer un local hors fenêtre ne doit pas recalculer les rangs RRF restants.
    judgeable = [pmid for pmid in ordered if pmid in abstract_pmids]
    selected = search_api._pick_judge_batch(
        judgeable, pubmed_set, config.judge_batch, config.local_floor
    )
    judge_items = [
        {
            key: payloads[pmid][key]
            for key in ("pmid", "title", "abstract", "journal", "pub_year", "evidence_level")
        }
        for pmid in selected
    ]
    timings["selection_s"] = time.monotonic() - started
    timings["total_s"] = time.monotonic() - total_started
    result = {
        **{
            key: case.get(key)
            for key in (
                "query_id",
                "theme",
                "intent",
                "width",
                "query",
                "date_from",
                "date_to",
            )
        },
        "config": asdict(config),
        "query_builder": builder,
        "query_builder_fingerprint": fingerprint(builder),
        "pubmed_total_hits": pubmed_total,
        "pubmed_pmids": pubmed_pmids,
        "local_pmids_raw": local_pmids,
        "local_pmids": [pmid for pmid in local_pmids if pmid in local_set],
        "candidate_pmids": ordered,
        "judgeable_pmids": judgeable,
        "judge_pmids": selected,
        "judge_items": judge_items,
        "selected_metadata": [payloads[pmid] for pmid in selected],
        "counts": {
            "pubmed": len(pubmed_set),
            "local": len(local_set),
            "merged": len(ordered),
            "judgeable": len(judgeable),
            "selected": len(selected),
            "local_dropped_window": local_dropped,
            "local_date_unverified": local_unverified,
            "external_missing": len(missing),
        },
        "local_search": local_status,
        "hydration_errors": hydration_errors,
        "timings": timings,
        "error": None,
    }
    validate_screen_case(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="artefact live complet")
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--k-pubmed", type=int, default=20)
    parser.add_argument("--max-local", type=int, default=200)
    parser.add_argument("--judge-batch", type=int, default=50)
    parser.add_argument("--rrf", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--local-floor", type=int, default=0)
    parser.add_argument("--use-narrow-search", action=argparse.BooleanOptionalAction, default=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RetrievalConfig(
        k_pubmed=args.k_pubmed,
        max_local=args.max_local,
        judge_batch=args.judge_batch,
        rrf=args.rrf,
        rrf_k=args.rrf_k,
        local_floor=args.local_floor,
        use_narrow_search=args.use_narrow_search,
    )
    if "autoresearch" not in args.database:
        raise SystemExit("REFUS: la base doit contenir 'autoresearch'")
    try:
        source = load_json(args.source)
        cases = validate_live_source(source)
    except (OSError, ValueError, InvalidArtifact) as exc:
        raise SystemExit(f"REFUS: artefact live invalide ({exc})") from exc

    engine = create_engine(
        _database_url(args.database),
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    with engine.connect() as connection:
        clone_metadata, corpus_fingerprint = _validate_clone(
            connection,
            args.database,
            allow_recent=source.get("corpus_scope") == "recent",
        )
    if source.get("corpus_fingerprint") != corpus_fingerprint:
        raise SystemExit("REFUS: le clone ne correspond pas à l'artefact live")

    factory = sessionmaker(engine, expire_on_commit=False)
    config_dict = asdict(config)
    source_identity = (
        {
            "protocol_fingerprint": source["protocol_fingerprint"],
            "benchmark_tier": source.get("benchmark_tier"),
        }
        if source.get("protocol_fingerprint")
        else {
            "manifest_fingerprint": source["manifest_fingerprint"],
            "benchmark_tier": source.get("benchmark_tier", "legacy_smoke_recent"),
        }
    )
    output = {
        "schema_version": 1,
        "artifact_type": "retrieval_screen",
        "run_id": f"retrieval-screen-{time.time_ns()}",
        "complete": False,
        "expected_query_ids": [str(case["query_id"]) for case in cases],
        "database": args.database,
        "corpus_scope": clone_metadata["scope"],
        "corpus_fingerprint": corpus_fingerprint,
        "machine_fingerprint": _machine_fingerprint(),
        **source_identity,
        "clone_metadata": clone_metadata,
        "read_only": True,
        "source_run_id": source.get("run_id"),
        "source_artifact_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config": config_dict,
        "config_fingerprint": fingerprint(config_dict),
        "calls": {"query_builder": False, "judge": False, "translate": False},
        "cases": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(args.out, output)
    for case in cases:
        print(f"[{case['query_id']}] {case['query']}", flush=True)
        started = time.monotonic()
        try:
            screened = screen_case(case, config, factory)
        except Exception as exc:  # un cas réseau/DB ne détruit pas les autres
            screened = {
                **{
                    key: case.get(key)
                    for key in (
                        "query_id",
                        "theme",
                        "intent",
                        "width",
                        "query",
                        "date_from",
                        "date_to",
                    )
                },
                "config": config_dict,
                "query_builder": case["external"]["query_builder"]["data"],
                "query_builder_fingerprint": fingerprint(case["external"]["query_builder"]["data"]),
                "judge_pmids": [],
                "judge_items": [],
                "selected_metadata": [],
                "timings": {"total_s": time.monotonic() - started},
                "error": f"{type(exc).__name__}: {exc}",
            }
        output["cases"].append(screened)
        _write_atomic(args.out, output)
    output["complete"] = True
    _write_atomic(args.out, output)
    engine.dispose()


if __name__ == "__main__":
    main()
