"""Construit un pool aveugle et borné pour évaluer la traduction en sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict, deque
from pathlib import Path


class TranslationPoolError(ValueError):
    """Artefact live ou pool de traduction incohérent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _item_id(pmid: int) -> str:
    return hashlib.sha256(f"translation:{pmid}".encode()).hexdigest()[:16]


def _load_live(path: Path) -> dict:
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationPoolError(f"artefact illisible: {path}") from exc
    if run.get("run_kind") != "live" or run.get("complete") is not True:
        raise TranslationPoolError(f"artefact live complet requis: {path}")
    cases = run.get("cases")
    if not isinstance(cases, list) or not cases:
        raise TranslationPoolError(f"cases absents: {path}")
    expected = [str(value) for value in run.get("expected_query_ids", [])]
    observed = [str(case.get("query_id")) for case in cases]
    if not expected or expected != observed or len(observed) != len(set(observed)):
        raise TranslationPoolError(f"couverture de requêtes incohérente: {path}")
    return run


def _length_bucket(abstract: str) -> str:
    length = len(abstract)
    if length < 600:
        return "short"
    if length < 1400:
        return "medium"
    return "long"


_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")
_PERCENT_RE = re.compile(r"(?:\d+(?:[.,]\d+)?\s*%|\bpercent\b)", re.IGNORECASE)
_CI_RE = re.compile(r"\b(?:\d{2}\s*%\s*)?(?:CI|IC|confidence interval)\b", re.IGNORECASE)
_UNIT_RE = re.compile(
    r"(?:\b(?:mg|kg|g|µg|mcg|mL|L|mmHg|cm|mm|µm|nm|mmol/L|mg/dL|mL/min)\b)",
    re.IGNORECASE,
)
_ACRONYM_RE = re.compile(r"\b(?=[A-Z0-9-]{2,}\b)(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]+\b")
_NEGATION_RE = re.compile(r"\b(?:no|not|without|neither|nor|non|absence|absent)\b", re.IGNORECASE)


def text_features(abstract: str, evidence_level: object) -> dict:
    return {
        "length": _length_bucket(abstract),
        "numbers": bool(_NUMBER_RE.search(abstract)),
        "percent": bool(_PERCENT_RE.search(abstract)),
        "confidence_interval": bool(_CI_RE.search(abstract)),
        "units": bool(_UNIT_RE.search(abstract)),
        "acronyms": bool(_ACRONYM_RE.search(abstract)),
        "negation": bool(_NEGATION_RE.search(abstract)),
        "evidence_level": evidence_level if evidence_level is not None else "missing",
    }


def _signature(item: dict) -> tuple:
    features = item["_features"]
    return (
        features["length"],
        features["numbers"],
        features["percent"],
        features["confidence_interval"],
        features["units"],
        features["acronyms"],
        features["negation"],
        str(features["evidence_level"]),
    )


def _select_stratified(items: list[dict], limit: int) -> list[dict]:
    groups: dict[tuple, deque[dict]] = defaultdict(deque)
    for item in sorted(items, key=lambda value: (value["item_id"], value["pmid"])):
        groups[_signature(item)].append(item)
    ordered_groups = sorted(groups, key=lambda key: (len(groups[key]), repr(key)))
    selected = []
    while len(selected) < limit:
        progressed = False
        for key in ordered_groups:
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].popleft())
                progressed = True
        if not progressed:
            break
    return selected


def build(paths: list[Path], *, limit: int = 60) -> tuple[list[dict], dict]:
    if not paths:
        raise TranslationPoolError("au moins un artefact live est requis")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise TranslationPoolError("limit doit être strictement positif")

    articles: dict[int, dict] = {}
    private: dict[int, dict] = {}
    source_artifacts = []
    for path in sorted(paths, key=lambda value: str(value.resolve())):
        run = _load_live(path)
        run_id = str(run.get("run_id") or path.stem)
        source_artifacts.append(
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
                "run_id": run_id,
                "protocol_fingerprint": run.get("protocol_fingerprint"),
                "variant_fingerprint": run.get("variant_fingerprint"),
                "corpus_fingerprint": run.get("corpus_fingerprint"),
            }
        )
        for case in run["cases"]:
            raw_query_id = case.get("query_id")
            if not isinstance(raw_query_id, str) or not raw_query_id.strip():
                raise TranslationPoolError(f"query_id invalide dans {path}")
            query_id = raw_query_id
            results = case.get("results")
            if not isinstance(results, list):
                raise TranslationPoolError(f"results invalide pour {query_id} dans {path}")
            for row in results:
                if not isinstance(row, dict):
                    raise TranslationPoolError(f"résultat non objet pour {query_id}")
                pmid = row.get("pmid")
                if isinstance(pmid, bool) or not isinstance(pmid, int) or pmid <= 0:
                    raise TranslationPoolError(f"PMID invalide pour {query_id}")
                title = row.get("title")
                abstract = row.get("abstract")
                if (
                    not isinstance(title, str)
                    or not isinstance(abstract, str)
                    or not abstract.strip()
                ):
                    raise TranslationPoolError(f"texte source absent pour PMID {pmid}")
                public_source = {"pmid": pmid, "title": title, "abstract": abstract}
                previous = articles.setdefault(pmid, public_source)
                if previous != public_source:
                    raise TranslationPoolError(f"textes sources incompatibles pour PMID {pmid}")
                state = private.setdefault(
                    pmid,
                    {
                        "query_ids": set(),
                        "retained_by": set(),
                        "evidence_levels": set(),
                        "baseline_translations": [],
                    },
                )
                state["query_ids"].add(query_id)
                state["retained_by"].add(run_id)
                evidence_level = row.get("evidence_level")
                if evidence_level is not None and (
                    isinstance(evidence_level, bool) or not isinstance(evidence_level, int)
                ):
                    raise TranslationPoolError(f"evidence_level invalide pour PMID {pmid}")
                if evidence_level is not None:
                    state["evidence_levels"].add(evidence_level)
                state["baseline_translations"].append(
                    {
                        "run_id": run_id,
                        "query_id": query_id,
                        "title_fr": row.get("title_fr"),
                        "abstract_fr": row.get("abstract_fr"),
                    }
                )

    candidates = []
    private_items = {}
    for pmid, source in articles.items():
        state = private[pmid]
        evidence_values = sorted(state["evidence_levels"], key=str)
        evidence = evidence_values[0] if len(evidence_values) == 1 else None
        query_ids = sorted(state["query_ids"])
        features = text_features(source["abstract"], evidence)
        item_id = _item_id(pmid)
        candidates.append(
            {
                "item_id": item_id,
                "query_id": query_ids[0],
                **source,
                "_features": features,
            }
        )
        translations = sorted(
            state["baseline_translations"],
            key=lambda value: (value["run_id"], value["query_id"]),
        )
        private_items[item_id] = {
            "pmid": pmid,
            "query_ids": query_ids,
            "retained_by": sorted(state["retained_by"]),
            "evidence_levels": evidence_values,
            "selection_features": features,
            "baseline_translations": translations,
        }

    selected_internal = _select_stratified(candidates, min(limit, len(candidates)))
    selected_ids = {item["item_id"] for item in selected_internal}
    selected = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in selected_internal
    ]
    key = {
        "schema_version": 1,
        "artifact_type": "translation_pool_private_key",
        "selection": {
            "method": "feature_signature_round_robin_v1",
            "limit": limit,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        },
        "source_artifacts": source_artifacts,
        "items": {item_id: private_items[item_id] for item_id in sorted(selected_ids)},
    }
    return selected, key


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
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
        raise TranslationPoolError("pool-out et key-out doivent être distincts")
    pool_value = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    key_value = json.dumps(key, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(pool_path, pool_value)
    _atomic_write(key_path, key_value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--pool-out", type=Path, required=True)
    parser.add_argument("--key-out", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        items, key = build(args.runs, limit=args.limit)
        write_outputs(args.pool_out, args.key_out, items, key)
    except TranslationPoolError as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    print(json.dumps(key["selection"], ensure_ascii=False))


if __name__ == "__main__":
    main()
