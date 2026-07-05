#!/usr/bin/env python3
"""Benchmark A/B des deux méthodes de recherche PubMed + codex.

- A = méthode « lots d'abstracts » (branche feat/pubmed-codex-abstract-batches)
      endpoint POST /search/pubmed  (lit TOUS les abstracts locaux de la fenêtre)
- B = méthode « filtre lexical+MeSH → codex juge » (PR #13, branche …-v2)
      endpoint POST /search/pubmed/deep

Mesure, pour chaque requête et une même fenêtre `st→ed`, deux axes :
  • pertinence  : top-k de chaque méthode + recouvrement (Jaccard des PMID) ;
  • efficacité  : latence, nb d'abstracts lus par codex / nb de lots (méthode A)
                  vs candidats filtrés / jugés (méthode B).

Stdlib uniquement (urllib) → tourne avec n'importe quel python3, sans venv.

Usage :
    python3 bench/pubmed_ab.py \
        --a http://127.0.0.1:8800 --b http://127.0.0.1:8810 \
        --from 2019-01-01 --to 2019-12-31 --k 12 \
        --queries "metformine et risque cardiovasculaire dans le diabète de type 2"
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _post(base: str, path: str, payload: dict, timeout: float) -> tuple[dict | None, float, str | None]:
    """POST JSON → (json, elapsed_seconds, error). error=None si OK."""
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
        return body, time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.monotonic() - t0, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:  # timeout, connexion, JSON…
        return None, time.monotonic() - t0, f"{type(e).__name__}: {e}"


def _norm(method: str, body: dict) -> list[dict]:
    """Ramène les deux formats à [{pmid, title, score01, source}]. (top → bas)"""
    out = []
    if method == "A":  # /search/pubmed → champ `ranked`, score 0-1
        for r in body.get("ranked", []):
            out.append({
                "pmid": r["pmid"], "title": r.get("title") or "",
                "score01": float(r.get("score") or 0.0),
                "source": "+".join(r.get("sources") or []),
            })
    else:  # /search/pubmed/deep → champ `results`, score 0-3
        for r in body.get("results", []):
            s = r.get("score")
            out.append({
                "pmid": r["pmid"], "title": r.get("title") or "",
                "score01": (float(s) / 3.0) if s is not None else 0.0,
                "source": r.get("source") or "",
            })
    return out


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def run(args) -> dict:
    report = {"window": {"from": args.date_from, "to": args.date_to}, "k": args.k,
              "endpoints": {"A": args.a, "B": args.b},
              "generated_at": datetime.now(timezone.utc).isoformat(), "queries": []}

    for q in args.queries:
        print(f"\n=== {q} ===", flush=True)
        # B (la mienne) d'abord : rapide
        b_body, b_t, b_err = _post(args.b, "/search/pubmed/deep",
                                   {"query": q, "date_from": args.date_from,
                                    "date_to": args.date_to, "k_pubmed": args.k,
                                    "max_local": args.max_local}, args.timeout_b)
        print(f"  B (deep)   : {b_t:6.1f}s  err={b_err}", flush=True)
        # A (codex) : potentiellement très long
        a_body, a_t, a_err = _post(args.a, "/search/pubmed",
                                   {"query": q, "date_from": args.date_from,
                                    "date_to": args.date_to, "k": args.k}, args.timeout_a)
        print(f"  A (batches): {a_t:6.1f}s  err={a_err}", flush=True)

        a_hits = _norm("A", a_body) if a_body else []
        b_hits = _norm("B", b_body) if b_body else []
        a_top = [h["pmid"] for h in a_hits[: args.k]]
        b_top = [h["pmid"] for h in b_hits[: args.k]]

        entry = {
            "query": q,
            "A": {
                "latency_s": round(a_t, 1), "error": a_err,
                "abstracts_read": (a_body or {}).get("local_abstracts"),
                "codex_batches": (a_body or {}).get("codex_batches"),
                "relevant_total": (a_body or {}).get("relevant_total"),
                "returned": len(a_hits), "top": a_hits[: args.k],
            },
            "B": {
                "latency_s": round(b_t, 1), "error": b_err,
                "counts": (b_body or {}).get("counts"),
                "returned": len(b_hits), "top": b_hits[: args.k],
            },
            "overlap": {
                "shared_topk": sorted(set(a_top) & set(b_top)),
                "jaccard_topk": round(_jaccard(set(a_top), set(b_top)), 3),
            },
        }
        report["queries"].append(entry)
    return report


def _print_md(report: dict) -> None:
    print("\n\n# Benchmark A/B — recherche PubMed + codex\n")
    w = report["window"]
    print(f"Fenêtre : **{w['from']} → {w['to']}** · k={report['k']}\n")
    print("| Requête | Méthode | Latence | Abstracts lus / candidats | Lots codex | Retenus | Jaccard top-k |")
    print("|---|---|--:|--:|--:|--:|--:|")
    for e in report["queries"]:
        a, b = e["A"], e["B"]
        bc = (b["counts"] or {})
        b_cand = f"{bc.get('merged','?')} (jugés {bc.get('judged','?')})"
        print(f"| {e['query'][:40]} | A batches | {a['latency_s']}s | {a['abstracts_read']} | {a['codex_batches']} | {a['relevant_total']} | {e['overlap']['jaccard_topk']} |")
        print(f"| | B deep | {b['latency_s']}s | {b_cand} | 1 | {bc.get('kept','?')} | |")
    print()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", default="http://127.0.0.1:8800", help="base URL méthode A (codex batches)")
    p.add_argument("--b", default="http://127.0.0.1:8810", help="base URL méthode B (deep, PR#13)")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--max-local", type=int, default=50)
    p.add_argument("--timeout-a", type=float, default=3600, help="A peut lire des milliers d'abstracts")
    p.add_argument("--timeout-b", type=float, default=600)
    p.add_argument("--queries", nargs="+", required=True)
    p.add_argument("--out", default="bench/pubmed_ab_result.json")
    args = p.parse_args()

    report = run(args)
    with open(args.out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    _print_md(report)
    print(f"\nJSON complet → {args.out}")


if __name__ == "__main__":
    main()
