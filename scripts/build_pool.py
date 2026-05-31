"""Pooling des candidats à juger pour le gold set FR, puis compilation.

Deux modes (voir PLAN_EVAL.md §4) :

  POOLING (défaut) : pour chaque requête de bench/queries_fr.json, on prend le
  top-K de plusieurs méthodes (plein-texte, bge_m3, medcpt), on fait l'UNION, et
  on écrit une feuille d'annotation bench/pool_fr.csv (colonne `grade` à remplir
  par les médecins : 0 = non pertinent, 1 = pertinent, 2 = très pertinent).
      uv run python -m scripts.build_pool [--k 20]

  COMPILE : relit bench/pool_fr.csv une fois annoté et écrit bench/gold_fr.json
  (jugements gradués) consommé par le benchmark.
      uv run python -m scripts.build_pool --compile

Le corpus d'évaluation = les articles vectorisés (table emb_bge_m3) : toutes les
méthodes (y compris le plein-texte) y sont restreintes pour rester comparables.

Entrée bench/queries_fr.json :
    [{"id": 1, "theme": "gyneco", "query": "saignements après la ménopause"}, ...]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import text as sql_text

from app.db import SessionLocal
from app.services.embeddings import REGISTRY, get_model

BENCH = Path(__file__).parent.parent / "bench"
QUERIES = BENCH / "queries_fr.json"
POOL_CSV = BENCH / "pool_fr.csv"
GOLD = BENCH / "gold_fr.json"

# Méthodes sémantiques poolées (les modèles présents dans le registre).
SEM_MODELS = list(REGISTRY)


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _fulltext_topk(session, query: str, k: int) -> list[int]:
    """Top-K plein-texte (ts_rank), restreint au corpus vectorisé (emb_bge_m3)."""
    rows = session.execute(
        sql_text(
            """
            SELECT a.pmid
            FROM articles a
            JOIN emb_bge_m3 e ON e.pmid = a.pmid
            WHERE a.fts @@ websearch_to_tsquery('english', :q)
            ORDER BY ts_rank(a.fts, websearch_to_tsquery('english', :q)) DESC
            LIMIT :k
            """
        ),
        {"q": query, "k": k},
    ).all()
    return [r[0] for r in rows]


def _semantic_topk(session, model_name: str, query: str, k: int) -> list[int]:
    """Top-K sémantique (plus proches voisins pgvector) pour un modèle."""
    model = get_model(model_name)
    qv = _vec_literal(model.encode_query([query])[0])
    rows = session.execute(
        sql_text(
            f"SELECT pmid FROM {model.table} ORDER BY v <=> (:qv)::vector LIMIT :k"
        ),
        {"qv": qv, "k": k},
    ).all()
    return [r[0] for r in rows]


def _load_queries() -> list[dict]:
    if not QUERIES.exists():
        raise SystemExit(
            f"{QUERIES} manquant. Crée-le : "
            '[{"id":1,"theme":"gyneco","query":"…"}, …]'
        )
    return json.loads(QUERIES.read_text())


def do_pool(k: int) -> None:
    queries = _load_queries()
    rows_out: list[dict] = []
    with SessionLocal() as s:
        for q in queries:
            qid, qtext = q["id"], q["query"]
            found: dict[int, set[str]] = {}
            for pmid in _fulltext_topk(s, qtext, k):
                found.setdefault(pmid, set()).add("ft")
            for m in SEM_MODELS:
                for pmid in _semantic_topk(s, m, qtext, k):
                    found.setdefault(pmid, set()).add(m)

            # métadonnées pour l'annotation
            pmids = list(found)
            meta = {}
            if pmids:
                for pmid, title, journal, year in s.execute(
                    sql_text(
                        "SELECT pmid, title, journal, pub_year FROM articles "
                        "WHERE pmid = ANY(:ids)"
                    ),
                    {"ids": pmids},
                ).all():
                    meta[pmid] = (title, journal, year)
            for pmid in pmids:
                title, journal, year = meta.get(pmid, ("", "", None))
                rows_out.append(
                    {
                        "query_id": qid,
                        "theme": q.get("theme", ""),
                        "query": qtext,
                        "pmid": pmid,
                        "title": title,
                        "journal": journal or "",
                        "pub_year": year or "",
                        "found_by": ",".join(sorted(found[pmid])),
                        "grade": "",  # à remplir : 0 / 1 / 2
                    }
                )
            print(f"  requête {qid} : {len(pmids)} candidats", flush=True)

    POOL_CSV.parent.mkdir(exist_ok=True)
    with POOL_CSV.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "query_id", "theme", "query", "pmid", "title",
                "journal", "pub_year", "found_by", "grade",
            ],
        )
        w.writeheader()
        w.writerows(rows_out)
    print(f"\n→ {POOL_CSV} : {len(rows_out)} lignes à annoter "
          f"({len(queries)} requêtes). Remplir la colonne `grade` (0/1/2).")


def do_compile() -> None:
    if not POOL_CSV.exists():
        raise SystemExit(f"{POOL_CSV} manquant — lance d'abord le pooling.")
    queries = {str(q["id"]): q for q in _load_queries()}
    judged: dict[str, dict[str, int]] = {}
    n_graded = 0
    with POOL_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            grade = (row.get("grade") or "").strip()
            if grade == "":
                continue
            try:
                g = int(grade)
            except ValueError:
                print(f"  ⚠ grade invalide '{grade}' (requête {row['query_id']}, pmid {row['pmid']}) — ignoré")
                continue
            judged.setdefault(str(row["query_id"]), {})[str(row["pmid"])] = g
            n_graded += 1

    gold = []
    for qid, q in queries.items():
        if qid not in judged:
            continue
        gold.append(
            {"id": int(qid), "theme": q.get("theme", ""), "query": q["query"],
             "judgments": judged[qid]}
        )
    GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=2))
    print(f"→ {GOLD} : {len(gold)} requêtes, {n_graded} jugements gradués.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=20, help="top-K par méthode pour le pool")
    ap.add_argument("--compile", action="store_true", help="compiler pool_fr.csv (annoté) -> gold_fr.json")
    args = ap.parse_args()
    if args.compile:
        do_compile()
    else:
        do_pool(args.k)


if __name__ == "__main__":
    main()
