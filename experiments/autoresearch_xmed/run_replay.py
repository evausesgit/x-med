"""Rejoue un artefact live sans réseau ni LLM sur le clone PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import search as search_api
from app.api.search import DeepSearchRequest, _run_deep_search, _translate_kept
from app.config import settings
from app.services import codex_judge, pubmed_eutils, query_builder
from app.services.codex_cli import CodexUsage
from app.services.codex_judge import Judgement
from app.services.pubmed_eutils import PubmedHit
from app.services.translate import Translation
from experiments.autoresearch_xmed.experiment import config
from experiments.autoresearch_xmed.manifest import (
    ManifestError,
    load_manifest_identity,
    variant_identity,
)
from experiments.autoresearch_xmed.optimizations import (
    fetch_articles_projected,
    translation_inputs_from_hits,
)
from experiments.autoresearch_xmed.run_live_baseline import (
    _database_url,
    _result_dict,
    _sha_json,
    _sha_text,
    _machine_fingerprint,
    _validate_clone,
    _write_atomic,
)
from experiments.autoresearch_xmed.score import load_json


def _usage(value: dict) -> CodexUsage:
    return CodexUsage(
        input_tokens=int(value.get("input_tokens", 0)),
        cached_input_tokens=int(value.get("cached_input_tokens", 0)),
        output_tokens=int(value.get("output_tokens", 0)),
        reasoning_output_tokens=int(value.get("reasoning_output_tokens", 0)),
    )


def replay_case(baseline: dict, session_factory, experiment: dict) -> dict:
    external = baseline["external"]
    phases = []
    captures: dict = {}
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

    def builder(question: str, timeout: int = 180):
        del timeout
        if question != baseline["query"]:
            raise RuntimeError("replay impossible: question du query-builder différente")
        value = external["query_builder"]
        return value["data"], _usage(value["usage"])

    def esearch(*args, **kwargs):
        value = external["esearch"]
        if "args" in value and (list(args) != value["args"] or kwargs != value["kwargs"]):
            raise RuntimeError("replay impossible: paramètres esearch différents")
        return int(value["total"]), [int(pmid) for pmid in value["pmids"]]

    def esummary(pmids: list[int]):
        raw = external.get("esummary", {})
        if "values" in raw and list(pmids) != raw.get("requested_pmids"):
            raise RuntimeError("replay impossible: appel esummary différent")
        values = raw.get("values", raw)
        captured = {int(pmid): value for pmid, value in values.items()}
        unknown = sorted(set(pmids) - set(captured))
        if unknown:
            raise RuntimeError(
                "replay impossible: esummary non capturé pour "
                + ", ".join(str(pmid) for pmid in unknown)
            )
        return {pmid: PubmedHit(**captured[pmid]) for pmid in pmids}

    def efetch(pmids: list[int]):
        raw = external.get("efetch", {})
        if "values" in raw and list(pmids) != raw.get("requested_pmids"):
            raise RuntimeError("replay impossible: appel efetch différent")
        values = raw.get("values", raw)
        captured = {int(pmid): value for pmid, value in values.items()}
        unknown = sorted(set(pmids) - set(captured))
        if unknown:
            raise RuntimeError(
                "replay impossible: efetch non capturé pour "
                + ", ".join(str(pmid) for pmid in unknown)
            )
        return {pmid: captured[pmid] for pmid in pmids}

    def judge(prm: str, articles: list[dict], timeout: int = 420):
        del timeout
        prompt = codex_judge._PROMPT_HEAD.format(prm=prm) + codex_judge._render_articles(articles)
        captures["judge_input_sha256"] = _sha_json(articles)
        captures["judge_prompt_sha256"] = _sha_text(prompt)
        values = baseline.get("judge_outputs", {})
        requested = {int(article["pmid"]) for article in articles}
        unknown = sorted(requested - {int(pmid) for pmid in values})
        if unknown:
            raise RuntimeError(
                "replay impossible: nouveaux PMID sans jugement live: "
                + ", ".join(str(pmid) for pmid in unknown)
            )
        result = {
            int(pmid): Judgement(
                score=int(value["score"]),
                reason=value["reason"],
                relevance_pct=value.get("relevance_pct"),
            )
            for pmid, value in values.items()
            if int(pmid) in requested
        }
        return result, _usage(baseline.get("judge_usage", {}))

    request = DeepSearchRequest(
        query=baseline["query"],
        date_from=baseline.get("date_from"),
        date_to=baseline.get("date_to"),
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
        stack.enter_context(patch.object(query_builder, "build_pubmed_query", builder))
        stack.enter_context(patch.object(pubmed_eutils, "esearch", esearch))
        stack.enter_context(patch.object(pubmed_eutils, "esummary", esummary))
        stack.enter_context(patch.object(pubmed_eutils, "efetch_abstracts", efetch))
        stack.enter_context(patch.object(codex_judge, "judge_articles", judge))
        stack.enter_context(
            patch.object(settings, "use_narrow_search", experiment["use_narrow_search"])
        )
        if experiment["project_articles"]:
            stack.enter_context(
                patch.object(search_api, "_fetch_articles", fetch_articles_projected)
            )
        response = _run_deep_search(request, corpus, app_db, progress)
    usable_latency = time.monotonic() - started

    baseline_translations = {
        int(row["pmid"]): Translation(row.get("title_fr") or "", row["abstract_fr"])
        for row in baseline.get("results", [])
        if row.get("abstract_fr")
    }
    baseline_result_pmids = {int(row["pmid"]) for row in baseline.get("results", [])}
    translation_usage = _usage(baseline.get("translation_usage", {}))
    translation_prompt = ""

    def translate(items, session=None, timeout=600):
        del session, timeout
        nonlocal translation_prompt
        from app.services.translate import _PROMPT_HEAD, _render

        translation_prompt = _PROMPT_HEAD + _render(items) if items else ""
        requested = {int(item["pmid"]) for item in items}
        unknown = sorted(requested - baseline_result_pmids)
        if unknown:
            raise RuntimeError(
                "replay impossible: nouveaux PMID sans traduction live: "
                + ", ".join(str(pmid) for pmid in unknown)
            )
        return (
            {pmid: value for pmid, value in baseline_translations.items() if pmid in requested},
            translation_usage,
        )

    from app.services import translate as translate_service

    with patch.object(translate_service, "translate_abstracts", translate):
        if experiment["reuse_hydrated_translation_input"]:
            items, missing = translation_inputs_from_hits(response.results)
            if missing:
                # Le candidat conserve le fallback actuel pour ces cas.
                with ExitStack() as stack:
                    corpus = stack.enter_context(session_factory())
                    app_db = stack.enter_context(session_factory())
                    translated_payload = _translate_kept(response, corpus, app_db, progress)
            else:
                values, _ = translate(items, session=None)
                translated_payload = {
                    str(pmid): {
                        "title_fr": value.title_fr,
                        "abstract_fr": value.abstract_fr,
                    }
                    for pmid, value in values.items()
                }
        else:
            with ExitStack() as stack:
                corpus = stack.enter_context(session_factory())
                app_db = stack.enter_context(session_factory())
                translated_payload = _translate_kept(response, corpus, app_db, progress)
    for hit in response.results:
        if translated := translated_payload.get(str(hit.pmid)):
            hit.title_fr = translated["title_fr"]
            hit.abstract_fr = translated["abstract_fr"]
    complete_latency = time.monotonic() - started
    return {
        **{key: baseline.get(key) for key in ("query_id", "theme", "intent", "width", "query")},
        "date_from": baseline.get("date_from"),
        "date_to": baseline.get("date_to"),
        "latency_s": complete_latency,
        "usable_latency_s": usable_latency,
        "complete_latency_s": complete_latency,
        "tokens": baseline.get("tokens", {"total": 0}),
        "judge_input_sha256": captures.get("judge_input_sha256"),
        "judge_prompt_sha256": captures.get("judge_prompt_sha256"),
        "translate_prompt_sha256": _sha_text(translation_prompt),
        "results": [_result_dict(hit) for hit in response.results],
        "counts": response.counts,
        "phases": phases,
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts" / "manifest.json",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if "autoresearch" not in args.database:
        raise SystemExit("REFUS: la base doit contenir 'autoresearch'")
    baseline = load_json(args.baseline)
    if baseline.get("run_kind") != "live":
        raise SystemExit("REFUS: la source du replay doit être un artefact live complet")
    legacy_source = not bool(baseline.get("protocol_fingerprint"))
    if legacy_source and baseline.get("corpus_scope") != "recent":
        raise SystemExit("REFUS: une source full legacy n'est pas rejouable")
    try:
        manifest = load_manifest_identity(
            args.manifest,
            allow_legacy_smoke=legacy_source,
        )
        experiment = config()
        variant = variant_identity(
            experiment,
            Path(__file__).resolve().parent / "experiment.py",
        )
    except ManifestError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    if legacy_source:
        if not manifest["legacy"] or baseline.get("manifest_fingerprint") != manifest.get(
            "legacy_manifest_sha256"
        ):
            raise SystemExit("REFUS: manifeste legacy différent de la capture live")
    elif manifest["legacy"] or baseline["protocol_fingerprint"] != manifest.get(
        "protocol_fingerprint"
    ):
        raise SystemExit("REFUS: protocole différent de la capture live")
    engine = create_engine(
        _database_url(args.database),
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    with engine.connect() as connection:
        clone_metadata, corpus_fingerprint = _validate_clone(
            connection,
            args.database,
            allow_recent=baseline.get("corpus_scope") == "recent",
        )
    expected_fingerprint = baseline.get("corpus_fingerprint")
    if expected_fingerprint and expected_fingerprint != corpus_fingerprint:
        raise SystemExit("REFUS: le clone ne correspond pas à l'artefact live")
    factory = sessionmaker(engine, expire_on_commit=False)
    source_sha256 = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    output = {
        "schema_version": 1,
        "run_id": f"replay-{int(time.time())}",
        "run_kind": "replay",
        "complete": False,
        "expected_query_ids": [str(case["query_id"]) for case in baseline["cases"]],
        "database": args.database,
        "corpus_scope": clone_metadata["scope"],
        "corpus_fingerprint": corpus_fingerprint,
        "machine_fingerprint": _machine_fingerprint(),
        "benchmark_tier": baseline.get(
            "benchmark_tier", "legacy_smoke_recent" if legacy_source else None
        ),
        "clone_metadata": clone_metadata,
        "source_artifact_sha256": source_sha256,
        "experiment": experiment,
        **variant,
        "cases": [],
    }
    if legacy_source:
        output["manifest_fingerprint"] = manifest["legacy_manifest_sha256"]
        output["legacy_manifest_sha256"] = manifest["legacy_manifest_sha256"]
    else:
        output["protocol_fingerprint"] = manifest["protocol_fingerprint"]
    for case in baseline["cases"]:
        output["cases"].append(replay_case(case, factory, experiment))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(args.out, output)
    output["complete"] = True
    _write_atomic(args.out, output)
    engine.dispose()


if __name__ == "__main__":
    main()
