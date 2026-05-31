"""Exécution du benchmark : embed → classe → métriques IR → stockage.

Métriques retenues (décision plan §2) : Recall@100 + nDCG@10, plus MRR et P@10.
- Corpus auto-contenu (NFCorpus) : tout en mémoire, cosinus brute-force.
- Corpus = base PubMed (gold set FR) : recherche via pgvector sur emb_*.
"""

from __future__ import annotations

import json

import numpy as np
from sqlalchemy import text as sql_text

from app.db import SessionLocal
from app.services.embeddings import get_model

METRICS = ["ndcg@10", "recall@100", "mrr", "precision@10"]


def _evaluate(qrels: dict, run: dict) -> dict:
    from ranx import Qrels, Run, evaluate

    return evaluate(Qrels(qrels), Run(run), METRICS)


def _store(model_name: str, dataset: str, scores: dict, params: dict) -> int:
    with SessionLocal() as s:
        run_id = s.execute(
            sql_text(
                "INSERT INTO bench_runs (model_name, dataset, params) "
                "VALUES (:m, :d, (:p)::jsonb) RETURNING id"
            ),
            {"m": model_name, "d": dataset, "p": json.dumps(params)},
        ).scalar()
        for metric, value in scores.items():
            s.execute(
                sql_text(
                    "INSERT INTO bench_results (run_id, metric, value) VALUES (:r, :me, :v)"
                ),
                {"r": run_id, "me": metric, "v": float(value)},
            )
        s.commit()
    return int(run_id)


def run_selfcontained(model_name: str, dataset: str, docs: dict, queries: dict, qrels: dict) -> dict:
    """Corpus fourni en mémoire (ex. NFCorpus)."""
    model = get_model(model_name)
    doc_ids = list(docs)
    print(f"[{model_name}/{dataset}] embed {len(doc_ids)} docs…", flush=True)
    doc_vecs = model.encode_doc([docs[d] for d in doc_ids])
    q_ids = list(queries)
    print(f"[{model_name}/{dataset}] embed {len(q_ids)} requêtes…", flush=True)
    q_vecs = model.encode_query([queries[q] for q in q_ids])

    sims = q_vecs @ doc_vecs.T  # vecteurs normalisés → cosinus
    run: dict[str, dict[str, float]] = {}
    for i, qid in enumerate(q_ids):
        top = np.argsort(-sims[i])[:100]
        run[qid] = {doc_ids[j]: float(sims[i, j]) for j in top}

    scores = _evaluate(qrels, run)
    _store(model_name, dataset, scores, {"docs": len(doc_ids), "queries": len(q_ids)})
    return scores


def run_db_corpus(model_name: str, dataset: str, queries: dict, qrels: dict) -> dict:
    """Corpus = base PubMed (gold set FR). Recherche via pgvector sur emb_*."""
    model = get_model(model_name)
    table = model.table
    run: dict[str, dict[str, float]] = {}
    with SessionLocal() as s:
        for qid, qtext in queries.items():
            qv = model.encode_query([qtext])[0]
            vec = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
            rows = s.execute(
                sql_text(
                    f"SELECT pmid, 1 - (v <=> (:qv)::vector) AS sim FROM {table} "
                    f"ORDER BY v <=> (:qv)::vector LIMIT 100"
                ),
                {"qv": vec},
            ).all()
            run[qid] = {str(pmid): float(sim) for pmid, sim in rows}

    scores = _evaluate(qrels, run)
    _store(model_name, dataset, scores, {"queries": len(queries), "corpus": "pubmed"})
    return scores


def run_db_fulltext(dataset: str, queries: dict, qrels: dict) -> dict:
    """Baseline plein-texte (ts_rank), restreinte au corpus vectorisé (emb_bge_m3)."""
    run: dict[str, dict[str, float]] = {}
    with SessionLocal() as s:
        for qid, qtext in queries.items():
            rows = s.execute(
                sql_text(
                    """
                    SELECT a.pmid,
                           ts_rank(a.fts, websearch_to_tsquery('english', :q)) AS r
                    FROM articles a
                    JOIN emb_bge_m3 e ON e.pmid = a.pmid
                    WHERE a.fts @@ websearch_to_tsquery('english', :q)
                    ORDER BY r DESC
                    LIMIT 100
                    """
                ),
                {"q": qtext},
            ).all()
            run[qid] = {str(pmid): float(r) for pmid, r in rows}
    scores = _evaluate(qrels, run)
    _store("fulltext", dataset, scores, {"queries": len(queries), "corpus": "pubmed"})
    return scores


def run_db_hybrid(model_name: str, dataset: str, queries: dict, qrels: dict, pool: int = 50) -> dict:
    """Hybride RRF (plein-texte + sémantique) — ce que le site sert réellement."""
    model = get_model(model_name)
    table = model.table
    run: dict[str, dict[str, float]] = {}
    with SessionLocal() as s:
        for qid, qtext in queries.items():
            ft_ids = [
                r[0]
                for r in s.execute(
                    sql_text(
                        f"""
                        SELECT a.pmid FROM articles a
                        JOIN {table} e ON e.pmid = a.pmid
                        WHERE a.fts @@ websearch_to_tsquery('english', :q)
                        ORDER BY ts_rank(a.fts, websearch_to_tsquery('english', :q)) DESC
                        LIMIT :pool
                        """
                    ),
                    {"q": qtext, "pool": pool},
                ).all()
            ]
            qv = model.encode_query([qtext])[0]
            vec = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
            sem_ids = [
                r[0]
                for r in s.execute(
                    sql_text(f"SELECT pmid FROM {table} ORDER BY v <=> (:qv)::vector LIMIT :pool"),
                    {"qv": vec, "pool": pool},
                ).all()
            ]
            # fusion RRF (k=60), identique à app/api/search.py
            rrf: dict[int, float] = {}
            for ranking in (ft_ids, sem_ids):
                for rank, pmid in enumerate(ranking):
                    rrf[pmid] = rrf.get(pmid, 0.0) + 1.0 / (60 + rank + 1)
            ordered = sorted(rrf, key=lambda p: rrf[p], reverse=True)[:100]
            run[qid] = {str(p): float(rrf[p]) for p in ordered}
    scores = _evaluate(qrels, run)
    _store(f"hybrid:{model_name}", dataset, scores, {"queries": len(queries), "pool": pool})
    return scores
