"""Mesure cold/hit du cache query-builder sans base ni endpoint de production."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from experiments.autoresearch_xmed.query_cache import build_cached


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    observations = []
    outputs = []
    for _ in range(2):
        started = time.monotonic()
        data, usage, hit = build_cached(args.question, args.cache_dir)
        observations.append(
            {
                "elapsed_s": time.monotonic() - started,
                "cache_hit": hit,
                "billed_tokens": 0 if hit else usage.total_tokens,
                "origin_usage": usage.as_dict(),
            }
        )
        outputs.append(data)
    if outputs[0] != outputs[1]:
        raise RuntimeError("le cache n'a pas restitué une sortie identique")
    result = {
        "schema_version": 1,
        "experiment": "versioned exact query-builder cache",
        "question": args.question,
        "observations": observations,
        "exact_output": True,
        "output": outputs[0],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for row in observations:
        print(
            f"hit={row['cache_hit']} elapsed={row['elapsed_s']:.4f}s "
            f"billed_tokens={row['billed_tokens']}"
        )


if __name__ == "__main__":
    main()
