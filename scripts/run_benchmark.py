"""Lance le benchmark des modèles d'embedding et affiche le leaderboard.

Usage :
    uv run python -m scripts.run_benchmark                      # tous modèles, NFCorpus (+ gold FR si présent)
    uv run python -m scripts.run_benchmark --models bge_m3      # un seul modèle
    uv run python -m scripts.run_benchmark --max-docs 1500      # limite le corpus NFCorpus (plus rapide)
"""

from __future__ import annotations

import argparse

from bench.datasets import load_gold_fr, load_nfcorpus
from bench.runner import run_db_corpus, run_db_fulltext, run_db_hybrid, run_selfcontained
from app.services.embeddings import REGISTRY


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=list(REGISTRY))
    ap.add_argument("--max-docs", type=int, default=None, help="limite NFCorpus")
    ap.add_argument("--skip-nfcorpus", action="store_true")
    args = ap.parse_args()

    board: list[tuple[str, str, dict]] = []

    if not args.skip_nfcorpus:
        docs, queries, qrels = load_nfcorpus(max_docs=args.max_docs)
        print(f"NFCorpus : {len(docs)} docs, {len(queries)} requêtes")
        for m in args.models:
            scores = run_selfcontained(m, "nfcorpus", docs, queries, qrels)
            board.append((m, "nfcorpus", scores))

    gold = load_gold_fr()
    if gold is not None:
        _, queries, qrels = gold
        print(f"Gold FR : {len(queries)} requêtes")
        # Baseline plein-texte (une seule fois, indépendante du modèle d'embedding)
        board.append(("fulltext", "gold_fr", run_db_fulltext("gold_fr", queries, qrels)))
        for m in args.models:
            # sémantique pur + hybride RRF (ce que le site sert)
            board.append((m, "gold_fr", run_db_corpus(m, "gold_fr", queries, qrels)))
            board.append((f"hybrid:{m}", "gold_fr", run_db_hybrid(m, "gold_fr", queries, qrels)))
    else:
        print("(pas de gold set FR — bench/gold_fr.json absent, étape ultérieure)")

    # Leaderboard
    print("\n=== LEADERBOARD ===")
    hdr = f"{'modèle':10} {'dataset':10} " + " ".join(f"{k:>12}" for k in ("ndcg@10", "recall@100", "mrr", "precision@10"))
    print(hdr)
    print("-" * len(hdr))
    for m, ds, sc in board:
        vals = " ".join(f"{sc.get(k, 0):>12.4f}" for k in ("ndcg@10", "recall@100", "mrr", "precision@10"))
        print(f"{m:10} {ds:10} {vals}")


if __name__ == "__main__":
    main()
