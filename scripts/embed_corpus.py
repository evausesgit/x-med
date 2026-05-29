"""Calcule les embeddings des articles et les écrit dans les tables emb_*.

Usage :
    uv run python -m scripts.embed_corpus --model bge_m3 --limit 5000
    uv run python -m scripts.embed_corpus --model medcpt --limit 5000
    uv run python -m scripts.embed_corpus --model all --limit 5000 --index

Stratégie : les articles sans embedding, les plus récents d'abord
(ORDER BY pub_year DESC). Le texte = titre + abstract (titre seul si pas d'abstract).
"""

from __future__ import annotations

import argparse
import time

import psycopg
from pgvector.psycopg import register_vector

from app.config import settings
from app.services.embeddings import REGISTRY, get_model


def _dsn() -> str:
    # psycopg.connect veut "postgresql://", pas "postgresql+psycopg://"
    return settings.database_url.replace("+psycopg", "")


def _doc_text(title: str | None, abstract: str | None) -> str:
    title = title or ""
    return f"{title}\n{abstract}" if abstract else title


def embed_model(model_name: str, limit: int, batch: int, make_index: bool) -> None:
    model = get_model(model_name)
    conn = psycopg.connect(_dsn())
    register_vector(conn)

    # Articles pas encore embeddés pour ce modèle, plus récents d'abord
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.pmid, a.title, a.abstract
            FROM articles a
            LEFT JOIN {model.table} e ON e.pmid = a.pmid
            WHERE e.pmid IS NULL
            ORDER BY a.pub_year DESC NULLS LAST, a.pmid DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"[{model_name}] rien à embedder.")
    else:
        print(f"[{model_name}] {len(rows)} articles à embedder…")
        t0 = time.time()
        done = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            texts = [_doc_text(t, a) for _, t, a in chunk]
            vecs = model.encode_doc(texts)
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {model.table} (pmid, v) VALUES (%s, %s) "
                    f"ON CONFLICT (pmid) DO UPDATE SET v = EXCLUDED.v",
                    [(pmid, vecs[j]) for j, (pmid, _, _) in enumerate(chunk)],
                )
            conn.commit()
            done += len(chunk)
            rate = done / (time.time() - t0)
            print(f"  [{model_name}] {done}/{len(rows)} ({rate:.0f}/s)", flush=True)

    if make_index:
        print(f"[{model_name}] création de l'index HNSW…")
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {model.table}_hnsw "
                f"ON {model.table} USING hnsw (v vector_cosine_ops) "
                f"WITH (m = 16, ef_construction = 64)"
            )
        conn.commit()
        print(f"[{model_name}] index OK.")

    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", help="medcpt | bge_m3 | all")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--index", action="store_true", help="créer l'index HNSW après")
    args = ap.parse_args()

    models = list(REGISTRY) if args.model == "all" else [args.model]
    for name in models:
        embed_model(name, args.limit, args.batch, args.index)


if __name__ == "__main__":
    main()
