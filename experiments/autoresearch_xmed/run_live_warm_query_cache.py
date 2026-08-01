"""Runner live sidecar avec cache exact du query-builder.

Le runner commun et le protocole gelé restent inchangés. Ce module applique
l'adaptateur uniquement pendant le processus expérimental et ajoute son audit à
l'artefact. ``--require-warm`` refuse tout miss avant d'ouvrir la base ou d'appeler
un LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.services import query_builder
from experiments.autoresearch_xmed.run_live_baseline import (
    _parser,
    _queries,
    _write_atomic,
    collect_live,
)
from experiments.autoresearch_xmed.warm_query_cache import ExactQueryBuilderCache


def main() -> None:
    parser = _parser()
    parser.description = "Capture live sidecar avec cache exact du query-builder"
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--require-warm", action="store_true")
    args = parser.parse_args()

    adapter = ExactQueryBuilderCache(args.cache_dir)
    selected = set(args.ids) if args.ids else None
    rows = _queries(args.queries, selected)
    if args.require_warm:
        misses = [row["id"] for row in rows if not adapter.contains(row["query"])]
        if misses:
            raise SystemExit("REFUS: cache non warm pour " + ", ".join(misses))

    with patch.object(query_builder, "build_pubmed_query", adapter):
        collect_live(args, run_role="variant")

    artifact = json.loads(args.out.read_text())
    artifact["poststudy_optimization"] = {
        "kind": "exact_query_builder_cache",
        "cache_dir": str(args.cache_dir.resolve()),
        "require_warm": args.require_warm,
        "hits": sum(event.hit for event in adapter.events),
        "misses": sum(not event.hit for event in adapter.events),
        "billed_tokens": sum(event.billed_tokens for event in adapter.events),
        "events": [
            {
                "question_key": event.question_key,
                "hit": event.hit,
                "billed_tokens": event.billed_tokens,
                "origin_tokens": event.origin_tokens,
            }
            for event in adapter.events
        ],
    }
    _write_atomic(args.out, artifact)


if __name__ == "__main__":
    main()
