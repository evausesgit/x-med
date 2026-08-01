"""Round 3 : mesure cold/hit du cache TTL esearch."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from experiments.autoresearch_xmed.esearch_cache import search_cached


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--term", required=True)
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    observations = []
    outputs = []
    for _ in range(2):
        started = time.monotonic()
        total, pmids, hit = search_cached(
            args.term,
            args.cache_dir,
            mindate=args.date_from,
            maxdate=args.date_to,
        )
        observations.append(
            {
                "elapsed_s": time.monotonic() - started,
                "cache_hit": hit,
                "api_calls": 0 if hit else 1,
            }
        )
        outputs.append({"total": total, "pmids": pmids})
    result = {
        "schema_version": 1,
        "experiment": "exact esearch TTL cache",
        "observations": observations,
        "exact_output": outputs[0] == outputs[1],
        "output": outputs[0],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for row in observations:
        print(
            f"hit={row['cache_hit']} elapsed={row['elapsed_s']:.4f}s api_calls={row['api_calls']}"
        )


if __name__ == "__main__":
    main()
