"""Construit un pool aveugle enrichi pour évaluer le juge hors ligne.

Le pool est l'union, par requête, des résultats retenus dans le top-k et de tous
les PMID effectivement envoyés au juge. Ces derniers apportent les hard
negatives que ``build_annotation_pool`` perdait en ne lisant que ``results``.

Les métadonnées sont hydratées sans réseau, dans cet ordre : résultats des
artefacts, captures ``esummary``/``efetch``, puis clone PostgreSQL autoresearch
préparé et ouvert en lecture seule. La provenance et le statut retenu/rejeté ne
figurent que dans la clé privée, jamais dans le JSONL présenté à l'annotateur.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings

Metadata = dict[str, object]
CloneFetcher = Callable[[set[int]], dict[int, Metadata]]

PUBLIC_FIELDS = ("title", "abstract", "journal", "pub_year", "evidence_level", "doi")


class JudgePoolError(RuntimeError):
    """Artefact incohérent ou clone impropre à une évaluation isolée."""


def _item_id(query_id: str, pmid: int) -> str:
    return hashlib.sha256(f"{query_id}:{pmid}".encode()).hexdigest()[:16]


def _values(capture: object) -> dict[str, object]:
    """Normalise les anciens dictionnaires et les captures récentes avec ``values``."""
    if not isinstance(capture, dict):
        return {}
    value = capture.get("values", capture)
    return value if isinstance(value, dict) else {}


def _external_metadata(case: dict) -> dict[int, Metadata]:
    external = case.get("external")
    if not isinstance(external, dict):
        return {}
    out: dict[int, Metadata] = {}
    for raw_pmid, value in _values(external.get("esummary")).items():
        if isinstance(value, dict):
            out[int(raw_pmid)] = {field: value.get(field) for field in PUBLIC_FIELDS}
    for raw_pmid, abstract in _values(external.get("efetch")).items():
        if abstract:
            out.setdefault(int(raw_pmid), {})["abstract"] = abstract
    return out


def _merge_missing(target: Metadata, source: Metadata | None) -> None:
    if not source:
        return
    for field in PUBLIC_FIELDS:
        if target.get(field) in (None, "") and source.get(field) not in (None, ""):
            target[field] = source[field]


def _load_run(path: Path) -> dict:
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JudgePoolError(f"artefact illisible: {path}: {exc}") from exc
    if not isinstance(run.get("cases"), list):
        raise JudgePoolError(f"artefact sans liste cases: {path}")
    return run


def build(
    paths: list[Path],
    *,
    top_k: int,
    seed: int,
    fetch_from_clone: CloneFetcher | None = None,
) -> tuple[list[dict], dict, dict[str, dict[str, int]]]:
    """Retourne ``(pool_aveugle, clé_privée, comptes_par_requête)``.

    ``fetch_from_clone`` n'est appelé qu'après épuisement des métadonnées des
    artefacts, et seulement pour les PMID dont le titre ou l'abstract manque.
    """
    if top_k < 1:
        raise JudgePoolError("top_k doit être positif")

    pooled: dict[tuple[str, int], dict] = {}
    queries: dict[str, str] = {}
    systems: dict[str, set[str]] = defaultdict(set)
    retained_by: dict[str, set[str]] = defaultdict(set)
    top_k_by: dict[str, set[str]] = defaultdict(set)
    judge_input_by: dict[str, set[str]] = defaultdict(set)

    for path in paths:
        run = _load_run(path)
        run_id = str(run.get("run_id") or path.stem)
        for case in run["cases"]:
            query_id = str(case["query_id"])
            query = str(case.get("query") or "").strip()
            if not query:
                raise JudgePoolError(f"question vide pour {query_id} dans {path}")
            previous = queries.setdefault(query_id, query)
            if previous != query:
                raise JudgePoolError(f"questions incompatibles pour {query_id}")

            results = case.get("results") or []
            if not isinstance(results, list):
                raise JudgePoolError(f"results invalide pour {query_id} dans {path}")
            result_rows = {int(row["pmid"]): row for row in results}
            # Les artefacts de screening s'arrêtent avant le juge et n'ont donc
            # pas de ``results``. Ils embarquent néanmoins les métadonnées
            # hydratées du lot dans ``selected_metadata`` : on peut les utiliser
            # sans assimiler ces articles à des résultats retenus.
            selected_metadata = case.get("selected_metadata") or []
            if not isinstance(selected_metadata, list):
                raise JudgePoolError(f"selected_metadata invalide pour {query_id} dans {path}")
            metadata_rows = {
                int(row["pmid"]): row
                for row in selected_metadata
                if isinstance(row, dict) and row.get("pmid") is not None
            }
            selected_results = [int(row["pmid"]) for row in results[:top_k]]
            judge_pmids = [int(pmid) for pmid in (case.get("judge_pmids") or [])]
            external = _external_metadata(case)

            # dict.fromkeys conserve l'ordre de sélection tout en dédupliquant.
            selected = list(dict.fromkeys([*selected_results, *judge_pmids]))
            for pmid in selected:
                pair = (query_id, pmid)
                item_id = _item_id(query_id, pmid)
                state = pooled.setdefault(
                    pair,
                    {
                        "item_id": item_id,
                        "query_id": query_id,
                        "query": query,
                        "pmid": pmid,
                        **{field: None for field in PUBLIC_FIELDS},
                    },
                )
                # Un résultat est bien « retenu » même s'il est au-delà de top_k
                # mais entre dans l'union parce qu'il faisait partie du lot jugé.
                if pmid in result_rows:
                    retained_by[item_id].add(run_id)
                    _merge_missing(state, result_rows[pmid])
                _merge_missing(state, metadata_rows.get(pmid))
                _merge_missing(state, external.get(pmid))

                systems[item_id].add(run_id)
                if pmid in selected_results:
                    top_k_by[item_id].add(run_id)
                if pmid in judge_pmids:
                    judge_input_by[item_id].add(run_id)

    needs_clone = {
        pmid
        for (_, pmid), item in pooled.items()
        if not item.get("title") or not item.get("abstract")
    }
    if needs_clone and fetch_from_clone is not None:
        clone_rows = fetch_from_clone(needs_clone)
        for (_, pmid), item in pooled.items():
            if pmid in needs_clone:
                _merge_missing(item, clone_rows.get(pmid))

    items = list(pooled.values())
    random.Random(seed).shuffle(items)
    private_items = {}
    counts: dict[str, dict[str, int]] = {}
    by_query: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_query[item["query_id"]].append(item)
        item_id = item["item_id"]
        private_items[item_id] = {
            "query_id": item["query_id"],
            "pmid": item["pmid"],
            "retained_by": sorted(retained_by[item_id]),
            "top_k_by": sorted(top_k_by[item_id]),
            "judge_input_by": sorted(judge_input_by[item_id]),
        }
    for query_id in sorted(by_query):
        query_items = by_query[query_id]
        retained = sum(bool(retained_by[item["item_id"]]) for item in query_items)
        hard_negative = sum(
            bool(judge_input_by[item["item_id"]]) and not retained_by[item["item_id"]]
            for item in query_items
        )
        counts[query_id] = {
            "total": len(query_items),
            "retained": retained,
            "hard_negative": hard_negative,
            "missing_abstract": sum(not bool(item.get("abstract")) for item in query_items),
        }

    key = {
        "schema_version": 1,
        "systems": {item_id: sorted(run_ids) for item_id, run_ids in systems.items()},
        "items": private_items,
        "counts": counts,
    }
    return items, key, counts


def _database_url(database: str) -> str:
    return (
        make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)
    )


def _validate_clone(connection, database: str) -> dict[str, str]:
    if "autoresearch" not in database.lower():
        raise JudgePoolError("REFUS: la base doit contenir 'autoresearch'")
    if connection.scalar(text("SHOW default_transaction_read_only")) != "on":
        raise JudgePoolError("REFUS: connexion clone non read-only")
    if connection.scalar(text("SELECT current_database()")) != database:
        raise JudgePoolError("REFUS: identité DB inattendue")
    if connection.scalar(text("SELECT to_regclass('public.articles')")) is None:
        raise JudgePoolError("REFUS: table articles absente")
    if connection.scalar(text("SELECT to_regclass('public.autoresearch_meta')")) is None:
        raise JudgePoolError("REFUS: métadonnées autoresearch absentes")
    metadata = dict(
        connection.execute(text("SELECT key, value FROM autoresearch_meta")).tuples().all()
    )
    if metadata.get("prepared") != "true":
        raise JudgePoolError("REFUS: clone autoresearch non préparé")
    return metadata


def _fetch_clone(connection, pmids: Iterable[int], batch_size: int = 1000) -> dict[int, Metadata]:
    ordered = sorted(set(pmids))
    out: dict[int, Metadata] = {}
    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset : offset + batch_size]
        rows = connection.execute(
            text(
                "SELECT pmid, title, abstract, journal, pub_year, evidence_level, doi "
                "FROM articles WHERE pmid = ANY(:pmids)"
            ),
            {"pmids": batch},
        ).mappings()
        for row in rows:
            value = dict(row)
            out[int(value.pop("pmid"))] = value
    return out


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_outputs(pool_path: Path, key_path: Path, items: list[dict], key: dict) -> None:
    if pool_path.resolve() == key_path.resolve():
        raise JudgePoolError("pool-out et key-out doivent être distincts")
    pool_value = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    key_value = json.dumps(key, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(pool_path, pool_value)
    _atomic_write_text(key_path, key_value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--pool-out", type=Path, required=True)
    parser.add_argument("--key-out", type=Path, required=True)
    args = parser.parse_args()

    if "autoresearch" not in args.database.lower():
        raise SystemExit("REFUS: la base doit contenir 'autoresearch'")
    engine = create_engine(
        _database_url(args.database),
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            _validate_clone(connection, args.database)
            items, key, counts = build(
                args.runs,
                top_k=args.top_k,
                seed=args.seed,
                fetch_from_clone=lambda pmids: _fetch_clone(connection, pmids),
            )
        write_outputs(args.pool_out, args.key_out, items, key)
    except JudgePoolError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        engine.dispose()
    print(json.dumps({"pool_items": len(items), "queries": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
