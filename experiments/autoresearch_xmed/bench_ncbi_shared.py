"""Round 9 : coût TLS d'un client NCBI neuf contre un client partagé."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

from app.services.pubmed_eutils import BASE, _TIMEOUT, _common_params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    params = {
        **_common_params(),
        "db": "pubmed",
        "term": "SGLT2 inhibitors HFpEF",
        "retmax": "5",
        "retmode": "json",
        "sort": "relevance",
    }
    samples = {"new_client": [], "shared_client": []}
    errors = {"new_client": 0, "shared_client": 0}
    retries = {"new_client": 0, "shared_client": 0}
    signatures = set()
    last_started = 0.0

    def pace() -> None:
        nonlocal last_started
        delay = 0.35 - (time.monotonic() - last_started)
        if delay > 0:
            time.sleep(delay)

    def request(client: httpx.Client) -> int:
        for attempt in range(3):
            try:
                response = client.get(f"{BASE}/esearch.fcgi", params=params)
                response.raise_for_status()
                data = response.json()["esearchresult"]
                signatures.add((data.get("count"), tuple(data.get("idlist", []))))
                return attempt
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise AssertionError("boucle retry inaccessible")

    with httpx.Client(timeout=_TIMEOUT) as shared:
        for repeat in range(args.repeats):
            order = ("new_client", "shared_client")
            if repeat % 2:
                order = tuple(reversed(order))
            for mode in order:
                pace()
                started = time.monotonic()
                last_started = started
                try:
                    if mode == "shared_client":
                        attempt = request(shared)
                    else:
                        with httpx.Client(timeout=_TIMEOUT) as fresh:
                            attempt = request(fresh)
                except httpx.HTTPError:
                    errors[mode] += 1
                else:
                    retries[mode] += attempt
                    samples[mode].append(time.monotonic() - started)
    output = {
        "schema_version": 1,
        "repeats": args.repeats,
        "exact_response": len(signatures) == 1,
        "errors": errors,
        "retries": retries,
        "samples_s": samples,
        "median_s": {
            key: statistics.median(values) if values else None for key, values in samples.items()
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                "exact_response": output["exact_response"],
                "errors": errors,
                "retries": retries,
                **output["median_s"],
            }
        )
    )


if __name__ == "__main__":
    main()
