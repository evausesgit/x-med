"""Construit un pool aveugle commun à partir de plusieurs artefacts de runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


def build(paths: list[Path], top_k: int, seed: int) -> tuple[list[dict], dict]:
    pooled: dict[tuple[str, int], dict] = {}
    provenance: dict[str, list[str]] = {}
    for path in paths:
        run = json.loads(path.read_text())
        run_id = str(run.get("run_id") or path.stem)
        for case in run["cases"]:
            query_id = str(case["query_id"])
            for result in case.get("results", [])[:top_k]:
                pmid = int(result["pmid"])
                key = (query_id, pmid)
                item_id = hashlib.sha256(f"{query_id}:{pmid}".encode()).hexdigest()[:16]
                pooled.setdefault(
                    key,
                    {
                        "item_id": item_id,
                        "query_id": query_id,
                        "query": case["query"],
                        "pmid": pmid,
                        "title": result.get("title"),
                        "abstract": result.get("abstract"),
                        "journal": result.get("journal"),
                        "pub_year": result.get("pub_year"),
                        "evidence_level": result.get("evidence_level"),
                    },
                )
                provenance.setdefault(item_id, []).append(run_id)
    items = list(pooled.values())
    random.Random(seed).shuffle(items)
    key = {
        "schema_version": 1,
        "systems": {item_id: sorted(set(values)) for item_id, values in provenance.items()},
        "items": {
            item["item_id"]: {"query_id": item["query_id"], "pmid": item["pmid"]} for item in items
        },
    }
    return items, key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--pool-out", type=Path, required=True)
    parser.add_argument("--key-out", type=Path, required=True)
    args = parser.parse_args()
    items, key = build(args.runs, args.top_k, args.seed)
    args.pool_out.parent.mkdir(parents=True, exist_ok=True)
    with args.pool_out.open("w") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    args.key_out.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n")
    print(f"pool_items={len(items)}")


if __name__ == "__main__":
    main()
