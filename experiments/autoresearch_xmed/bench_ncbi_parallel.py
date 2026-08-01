"""Round 4 : compare hydratation NCBI séquentielle et parallèle."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from app.services import pubmed_eutils


def hydrate_sequential(pmids: list[int]) -> tuple[dict, dict]:
    return pubmed_eutils.esummary(pmids), pubmed_eutils.efetch_abstracts(pmids)


def hydrate_parallel(pmids: list[int]) -> tuple[dict, dict]:
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ncbi-hydrate") as executor:
        summary_future = executor.submit(pubmed_eutils.esummary, pmids)
        abstract_future = executor.submit(pubmed_eutils.efetch_abstracts, pmids)
        return summary_future.result(), abstract_future.result()


def normalized(value: tuple[dict, dict]) -> dict:
    summaries, abstracts = value
    return {
        "summaries": {str(pmid): asdict(summary) for pmid, summary in summaries.items()},
        "abstracts": {str(pmid): abstract for pmid, abstract in abstracts.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmids", nargs="+", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rng = random.Random(20260731)
    observations = []
    reference = None
    for repetition in range(args.repetitions):
        modes = ["sequential", "parallel"]
        rng.shuffle(modes)
        for mode in modes:
            started = time.monotonic()
            value = (
                hydrate_sequential(args.pmids)
                if mode == "sequential"
                else hydrate_parallel(args.pmids)
            )
            elapsed = time.monotonic() - started
            output = normalized(value)
            reference = output if reference is None else reference
            observations.append(
                {
                    "repetition": repetition + 1,
                    "mode": mode,
                    "elapsed_s": elapsed,
                    "exact_reference": output == reference,
                }
            )
            time.sleep(1.1)  # courtoisie NCBI entre les paires de mesures
    by_mode = {
        mode: [row["elapsed_s"] for row in observations if row["mode"] == mode]
        for mode in ("sequential", "parallel")
    }
    result = {
        "schema_version": 1,
        "experiment": "parallel NCBI esummary + efetch",
        "pmids": args.pmids,
        "observations": observations,
        "all_outputs_exact": all(row["exact_reference"] for row in observations),
        "median_s": {mode: statistics.median(values) for mode, values in by_mode.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["median_s"], indent=2))
    print(f"all_outputs_exact={result['all_outputs_exact']}")


if __name__ == "__main__":
    main()
