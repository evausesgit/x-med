"""Collecte une baseline bout-en-bout sur la base clonée autoresearch.

Le runner appelle directement le cœur applicatif, sans HTTP, notification, run_store
ou saved_search. Les deux sessions PostgreSQL sont forcées en lecture seule et la
traduction reçoit `session=None`, donc aucun cache n'est écrit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api import search as search_api
from app.api.search import DeepSearchRequest, _run_deep_search, _translate_kept
from app.config import settings
from app.services import codex_judge, pubmed_eutils, query_builder
from app.services.query_builder import _PROMPT as QUERY_PROMPT
from app.services.translate import _PROMPT_HEAD as TRANSLATE_PROMPT_HEAD
from app.services.translate import _render as render_translations
from app.services.translate import translate_abstracts
from experiments.autoresearch_xmed.experiment import config
from experiments.autoresearch_xmed.manifest import (
    BASELINE_BEHAVIOR_CONFIG,
    ManifestError,
    behavior_config,
    load_manifest_identity,
    variant_identity,
)
from experiments.autoresearch_xmed.optimizations import (
    fetch_articles_projected,
    translation_inputs_from_hits,
)

HERE = Path(__file__).resolve().parent


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha_text(payload)


def _database_url(database: str) -> str:
    return (
        make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)
    )


def _validate_clone(connection, database: str, allow_recent: bool = False) -> tuple[dict, str]:
    if connection.scalar(text("SHOW default_transaction_read_only")) != "on":
        raise SystemExit("REFUS: connexion non read-only")
    if connection.scalar(text("SELECT current_database()")) != database:
        raise SystemExit("REFUS: identité DB inattendue")
    if connection.scalar(text("SELECT to_regclass('public.articles')")) is None:
        raise SystemExit("REFUS: clone non préparé")
    if connection.scalar(text("SELECT to_regclass('public.autoresearch_meta')")) is None:
        raise SystemExit("REFUS: métadonnées du clone absentes")
    metadata = dict(
        connection.execute(text("SELECT key, value FROM autoresearch_meta")).tuples().all()
    )
    if metadata.get("prepared") != "true" or not metadata.get("snapshot_rows"):
        raise SystemExit("REFUS: clone incomplet")
    if metadata.get("scope") != "full" and not allow_recent:
        raise SystemExit(
            "REFUS: un clone récent ne peut servir que de smoke test explicite "
            "(--allow-recent-smoke)"
        )
    return metadata, _sha_json(metadata)


def _write_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _machine_fingerprint() -> str:
    return _sha_json(
        {
            "node": platform.node(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        }
    )


def _queries(path: Path, selected: set[str] | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if selected:
        rows = [row for row in rows if row["id"] in selected]
    return rows


def _result_dict(hit) -> dict:
    return {
        "pmid": hit.pmid,
        "title": hit.title,
        "abstract": hit.abstract,
        "title_fr": hit.title_fr,
        "abstract_fr": hit.abstract_fr,
        "journal": hit.journal,
        "pub_year": hit.pub_year,
        "evidence_level": hit.evidence_level,
        "source": hit.source,
        "score": hit.score,
        "relevance_pct": hit.relevance_pct,
        "reason": hit.reason,
        "doi": hit.doi,
        "in_db": hit.in_db,
    }


def run_case(row: dict, session_factory, experiment: dict) -> dict:
    phases = []
    judge_capture: dict = {}
    translation_capture: dict = {}
    external_capture: dict = {}
    started = time.monotonic()

    def progress(phase: str, message: str, data: dict) -> None:
        phases.append(
            {
                "phase": phase,
                "message": message,
                "elapsed_s": time.monotonic() - started,
                "data": data,
            }
        )

    original_judge = codex_judge.judge_articles
    original_builder = query_builder.build_pubmed_query
    original_esearch = pubmed_eutils.esearch
    original_esummary = pubmed_eutils.esummary
    original_efetch = pubmed_eutils.efetch_abstracts
    original_candidate_order = search_api._candidate_order

    def capture_builder(question: str, timeout: int = 180):
        data, usage = original_builder(question, timeout)
        external_capture["query_builder"] = {"data": data, "usage": usage.as_dict()}
        return data, usage

    def capture_esearch(*args, **kwargs):
        total, pmids = original_esearch(*args, **kwargs)
        external_capture["esearch"] = {
            "args": list(args),
            "kwargs": kwargs,
            "total": total,
            "pmids": pmids,
        }
        return total, pmids

    def capture_esummary(pmids: list[int]):
        result = original_esummary(pmids)
        external_capture["esummary"] = {
            "requested_pmids": list(pmids),
            "values": {str(pmid): asdict(summary) for pmid, summary in result.items()},
        }
        return result

    def capture_efetch(pmids: list[int]):
        result = original_efetch(pmids)
        external_capture["efetch"] = {
            "requested_pmids": list(pmids),
            "values": {str(pmid): abstract for pmid, abstract in result.items()},
        }
        return result

    def capture_candidate_order(a_pmids, local_pmids, rrf, k=60):
        external_capture["pubmed_pmids"] = list(a_pmids)
        external_capture["local_pmids"] = list(local_pmids)
        return original_candidate_order(a_pmids, local_pmids, rrf, k)

    def capture_judge(prm: str, articles: list[dict], timeout: int = 420):
        prompt = codex_judge._PROMPT_HEAD.format(prm=prm) + codex_judge._render_articles(articles)
        judge_capture["input_sha256"] = _sha_json(articles)
        judge_capture["prompt_sha256"] = _sha_text(prompt)
        judge_capture["pmids"] = [article["pmid"] for article in articles]
        result, usage = original_judge(prm, articles, timeout)
        judge_capture["usage"] = usage.as_dict()
        judge_capture["judgements"] = {
            str(pmid): {
                "score": judgement.score,
                "reason": judgement.reason,
                "relevance_pct": judgement.relevance_pct,
            }
            for pmid, judgement in result.items()
        }
        return result, usage

    request = DeepSearchRequest(
        query=row["query"],
        date_from=row.get("date_from"),
        date_to=row.get("date_to"),
        k_pubmed=experiment["k_pubmed"],
        max_local=experiment["max_local"],
        judge_batch=experiment["judge_batch"],
        min_score=experiment["min_score"],
        rrf=experiment["rrf"],
        local_floor=experiment["local_floor"],
    )
    with ExitStack() as stack:
        corpus = stack.enter_context(session_factory())
        app_db = stack.enter_context(session_factory())
        stack.enter_context(patch.object(codex_judge, "judge_articles", capture_judge))
        stack.enter_context(patch.object(query_builder, "build_pubmed_query", capture_builder))
        stack.enter_context(patch.object(pubmed_eutils, "esearch", capture_esearch))
        stack.enter_context(patch.object(pubmed_eutils, "esummary", capture_esummary))
        stack.enter_context(patch.object(pubmed_eutils, "efetch_abstracts", capture_efetch))
        stack.enter_context(patch.object(search_api, "_candidate_order", capture_candidate_order))
        stack.enter_context(
            patch.object(settings, "use_narrow_search", experiment["use_narrow_search"])
        )
        if experiment["project_articles"]:
            stack.enter_context(
                patch.object(search_api, "_fetch_articles", fetch_articles_projected)
            )
        response = _run_deep_search(request, corpus, app_db, progress)
    usable_latency = time.monotonic() - started

    if experiment["reuse_hydrated_translation_input"]:
        translation_items, missing = translation_inputs_from_hits(response.results)
        if missing:
            raise RuntimeError("fixture clone inattendue: hit retenu sans abstract")
        translation_prompt = (
            TRANSLATE_PROMPT_HEAD + render_translations(translation_items)
            if translation_items
            else ""
        )
        translations, translation_usage = translate_abstracts(translation_items, session=None)
        translated_payload = {
            str(pmid): {"title_fr": value.title_fr, "abstract_fr": value.abstract_fr}
            for pmid, value in translations.items()
        }
    else:
        from app.services import translate as translate_service

        original_translate = translate_service.translate_abstracts

        def capture_translate(items, session=None, timeout=600):
            prompt = TRANSLATE_PROMPT_HEAD + render_translations(items) if items else ""
            translation_capture["prompt"] = prompt
            result, usage = original_translate(items, session=None, timeout=timeout)
            translation_capture["usage"] = usage
            return result, usage

        with ExitStack() as stack:
            corpus = stack.enter_context(session_factory())
            app_db = stack.enter_context(session_factory())
            stack.enter_context(
                patch.object(translate_service, "translate_abstracts", capture_translate)
            )
            translated_payload = _translate_kept(response, corpus, app_db, progress)
        translation_prompt = translation_capture.get("prompt", "")
        translation_usage = translation_capture.get("usage")
        if translation_usage is None:
            from app.services.codex_cli import CodexUsage

            translation_usage = CodexUsage()

    for hit in response.results:
        if translated := translated_payload.get(str(hit.pmid)):
            hit.title_fr = translated["title_fr"]
            hit.abstract_fr = translated["abstract_fr"]
    complete_latency = time.monotonic() - started
    query_tokens = int(response.codex_tokens.get("query", 0))
    judge_tokens = int(response.codex_tokens.get("judge", 0))
    translation_tokens = translation_usage.total_tokens
    return {
        "query_id": row["id"],
        "theme": row.get("theme"),
        "intent": row.get("intent"),
        "width": row.get("width"),
        "query": row["query"],
        "date_from": row.get("date_from"),
        "date_to": row.get("date_to"),
        "latency_s": complete_latency,
        "usable_latency_s": usable_latency,
        "complete_latency_s": complete_latency,
        "tokens": {
            "query": query_tokens,
            "judge": judge_tokens,
            "translate": translation_tokens,
            "total": query_tokens + judge_tokens + translation_tokens,
        },
        "query_prompt_sha256": _sha_text(QUERY_PROMPT.format(q=row["query"])),
        "judge_input_sha256": judge_capture.get("input_sha256"),
        "judge_prompt_sha256": judge_capture.get("prompt_sha256"),
        "translate_prompt_sha256": _sha_text(translation_prompt),
        "judge_pmids": judge_capture.get("pmids", []),
        "judge_usage": judge_capture.get("usage", {}),
        "judge_outputs": judge_capture.get("judgements", {}),
        "translation_usage": translation_usage.as_dict(),
        "external": external_capture,
        "pubmed_query": response.pubmed_query,
        "keywords_en": response.keywords_en,
        "mesh_terms": response.mesh_terms,
        "counts": response.counts,
        "phases": phases,
        "results": [_result_dict(hit) for hit in response.results],
        "error": None,
    }


def _collection_contract(
    *,
    run_role: str,
    manifest: dict,
    experiment: dict,
    corpus_scope: str,
    selected: set[str] | None,
    queries_path: Path,
    rows: list[dict],
) -> str:
    """Valide les invariants sans ouvrir la DB ni appeler le réseau/LLM."""
    if run_role not in {"baseline", "variant"}:
        raise ValueError("run_role doit valoir baseline ou variant")
    current_behavior = behavior_config(experiment)
    if run_role == "baseline" and current_behavior != BASELINE_BEHAVIOR_CONFIG:
        raise SystemExit("REFUS: une capture baseline exige la configuration baseline")
    if run_role == "variant" and manifest["legacy"]:
        raise SystemExit("REFUS: le runner variante exige un manifeste v2")
    if manifest["legacy"] and corpus_scope != "recent":
        raise SystemExit("REFUS: un manifeste legacy ne peut produire qu'un smoke récent")
    if not manifest["legacy"] and manifest["baseline_behavior_config"] != (
        BASELINE_BEHAVIOR_CONFIG
    ):
        raise SystemExit("REFUS: configuration baseline du manifeste v2 incohérente")
    if corpus_scope == "full":
        if selected or queries_path.resolve() != (HERE / "queries.jsonl").resolve():
            raise SystemExit("REFUS: un run full exige le corpus de requêtes canonique complet")
        expected_ids = [f"q{index:02d}" for index in range(1, 19)]
        if (
            manifest["legacy"]
            or manifest["query_count"] != len(expected_ids)
            or [row.get("id") for row in rows] != expected_ids
        ):
            raise SystemExit("REFUS: couverture incomplète ou non canonique du run full")
        return "benchmark_full"
    if corpus_scope != "recent":
        raise SystemExit("REFUS: scope de clone inconnu")
    return "legacy_smoke_recent" if manifest["legacy"] else "smoke_recent"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--queries", type=Path, default=HERE / "queries.jsonl")
    parser.add_argument("--manifest", type=Path, default=HERE / "artifacts" / "manifest.json")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--allow-recent-smoke", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def collect_live(args: argparse.Namespace, *, run_role: str) -> None:
    if "autoresearch" not in args.database:
        raise SystemExit("REFUS: la base doit contenir 'autoresearch'")
    try:
        manifest = load_manifest_identity(
            args.manifest,
            allow_legacy_smoke=args.allow_recent_smoke and run_role == "baseline",
        )
        # Appel unique : la même valeur est enregistrée dans l'enveloppe et passée à
        # tous les cas, sans possibilité de dérive au milieu d'un run.
        experiment = config()
        variant = variant_identity(experiment, HERE / "experiment.py")
    except ManifestError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc

    engine = create_engine(
        _database_url(args.database),
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    with engine.connect() as connection:
        clone_metadata, corpus_fingerprint = _validate_clone(
            connection, args.database, args.allow_recent_smoke
        )
    corpus_scope = clone_metadata["scope"]
    selected = set(args.ids) if args.ids else None
    rows = _queries(args.queries, selected)
    if selected:
        missing_ids = sorted(selected - {row["id"] for row in rows})
        if missing_ids:
            raise SystemExit("REFUS: query_id inconnus: " + ", ".join(missing_ids))
    benchmark_tier = _collection_contract(
        run_role=run_role,
        manifest=manifest,
        experiment=experiment,
        corpus_scope=corpus_scope,
        selected=selected,
        queries_path=args.queries,
        rows=rows,
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    output = {
        "schema_version": 1,
        "run_id": f"{run_role}-{int(time.time())}",
        "run_kind": "live",
        "run_role": run_role,
        "complete": False,
        "expected_query_ids": [row["id"] for row in rows],
        "database": args.database,
        "corpus_scope": corpus_scope,
        "corpus_fingerprint": corpus_fingerprint,
        "machine_fingerprint": _machine_fingerprint(),
        "benchmark_tier": benchmark_tier,
        "clone_metadata": clone_metadata,
        "read_only": True,
        "experiment": experiment,
        **variant,
        "cases": [],
    }
    if manifest["legacy"]:
        output["manifest_fingerprint"] = manifest["legacy_manifest_sha256"]
        output["legacy_manifest_sha256"] = manifest["legacy_manifest_sha256"]
    else:
        output["protocol_fingerprint"] = manifest["protocol_fingerprint"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for row in rows:
        print(f"[{row['id']}] {row['query']}", flush=True)
        case_started = time.monotonic()
        try:
            case = run_case(row, factory, experiment)
        except Exception as exc:  # un cas ne détruit pas le run complet
            failed_latency = time.monotonic() - case_started
            case = {
                "query_id": row["id"],
                "theme": row.get("theme"),
                "intent": row.get("intent"),
                "width": row.get("width"),
                "query": row["query"],
                "latency_s": failed_latency,
                "usable_latency_s": failed_latency,
                "complete_latency_s": failed_latency,
                "tokens": {"total": 0},
                "results": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"  ERROR {case['error']}", flush=True)
        else:
            print(
                f"  usable={case['usable_latency_s']:.1f}s "
                f"complete={case['complete_latency_s']:.1f}s "
                f"kept={len(case['results'])} tokens={case['tokens']['total']}",
                flush=True,
            )
        output["cases"].append(case)
        _write_atomic(args.out, output)
    output["complete"] = True
    _write_atomic(args.out, output)
    engine.dispose()


def main(*, run_role: str = "baseline") -> None:
    collect_live(_parser().parse_args(), run_role=run_role)


if __name__ == "__main__":
    main()
