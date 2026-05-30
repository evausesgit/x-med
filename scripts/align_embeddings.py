"""Aligne deux tables d'embeddings : vectorise dans le modèle `--into` les
articles présents dans le modèle `--from` mais absents de `--into`.

But : que les deux tables emb_* couvrent le même ensemble de PMID, pour une
comparaison équitable des modèles (benchmark). Ne recalcule rien d'existant.

Usage :
    uv run python -m scripts.align_embeddings --from medcpt --into bge_m3
"""

from __future__ import annotations

import argparse
import time

import psycopg
from pgvector.psycopg import register_vector

from app.config import settings
from app.services.embeddings import get_model


def _dsn() -> str:
    return settings.database_url.replace("+psycopg", "")


def _doc_text(title: str | None, abstract: str | None) -> str:
    title = title or ""
    return f"{title}\n{abstract}" if abstract else title


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="modèle de référence (PMID à couvrir)")
    ap.add_argument("--into", dest="dst", required=True, help="modèle à compléter")
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    src = get_model(args.src)
    dst = get_model(args.dst)

    conn = psycopg.connect(_dsn())
    register_vector(conn)

    # PMID dans src mais pas dans dst
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.pmid, a.title, a.abstract
            FROM {src.table} s
            JOIN articles a ON a.pmid = s.pmid
            LEFT JOIN {dst.table} d ON d.pmid = s.pmid
            WHERE d.pmid IS NULL
            ORDER BY a.pub_year DESC NULLS LAST, a.pmid DESC
            """
        )
        rows = cur.fetchall()

    if not rows:
        print(f"Déjà aligné : aucun PMID de {args.src} ne manque dans {args.dst}.")
        conn.close()
        return

    print(f"{len(rows)} article(s) de {args.src} à vectoriser dans {args.dst}…")
    t0 = time.time()
    done = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i : i + args.batch]
        texts = [_doc_text(t, a) for _, t, a in chunk]
        vecs = dst.encode_doc(texts)
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {dst.table} (pmid, v) VALUES (%s, %s) "
                f"ON CONFLICT (pmid) DO UPDATE SET v = EXCLUDED.v",
                [(pmid, vecs[j]) for j, (pmid, _, _) in enumerate(chunk)],
            )
        conn.commit()
        done += len(chunk)
        print(f"  {done}/{len(rows)} ({done / (time.time() - t0):.0f}/s)", flush=True)

    print(f"Aligné : {done} article(s) ajouté(s) à {args.dst} en {time.time() - t0:.0f}s.")
    conn.close()


if __name__ == "__main__":
    main()
