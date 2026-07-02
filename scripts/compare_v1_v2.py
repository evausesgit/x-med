#!/usr/bin/env python3
"""Comparaison v1 vs v2 (fusion RRF) de la SÉLECTION des candidats à juger.

Pour chaque recherche sauvegardée (via sa `pubmed_query` stockée → aucun appel codex),
on reconstruit le lot que Codex jugerait sous les deux algos et on compte la part
d'articles LOCAUX-seuls qui y entrent :

- v1 : PubMed d'abord (k_pubmed=20) puis local, top `batch`.
- v2 : fusion RRF (rang réciproque) de PubMed (k_pubmed=100) et du local, top `batch`.

Le RRF vise à ne pas enterrer le local (~39 % des résultats pertinents en viennent).
Robuste au rate-limit NCBI (429 → backoff + retry). Lecture seule, sans codex.

Usage : python -m scripts.compare_v1_v2 [--batch 50] [--out /tmp/compare_v1_v2.out]
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.article import Article
from app.models.saved_search import SavedSearch
from app.services import pubmed_eutils as eut


def esearch_retry(pq, dfrom, dto, retmax=100, tries=12, wait=60):
    """esearch avec backoff sur 429 (rate-limit NCBI)."""
    for i in range(tries):
        try:
            return eut.esearch(pq, retmax=retmax, sort="relevance", mindate=dfrom, maxdate=dto)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 429:
                print(f"    429 NCBI, attente {wait}s ({i+1}/{tries})…", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("esearch : rate-limit persistant")


def local_pmids(s, kw, mesh, dfrom, dto, limit=200):
    ts = " OR ".join(kw) if kw else "medicine"
    tsq = func.websearch_to_tsquery("english", ts)
    cond = Article.fts.op("@@")(tsq)
    if mesh:
        cond = cond | Article.mesh_terms.overlap(mesh)
    cs = [cond]
    if dfrom:
        cs.append(Article.pub_year >= int(dfrom[:4]))
    if dto:
        cs.append(Article.pub_year <= int(dto[:4]))
    return list(
        s.scalars(
            select(Article.pmid).where(*cs).order_by(func.ts_rank(Article.fts, tsq).desc()).limit(limit)
        )
    )


def rrf(a, b, K=60):
    sc: dict[int, float] = {}
    for lst in (a, b):
        for r, p in enumerate(lst):
            sc[p] = sc.get(p, 0.0) + 1.0 / (K + r)
    return sorted(set(a) | set(b), key=lambda p: -sc[p])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--out", default="/tmp/compare_v1_v2.out")
    args = ap.parse_args()

    out = open(args.out, "w")

    def emit(line=""):
        print(line, flush=True)
        out.write(line + "\n")
        out.flush()

    emit(f"{'requête':<40}{'v1 loc':>7}{'v2 loc':>7}   Δ")
    emit("-" * 64)
    a1 = a2 = n = 0
    with SessionLocal() as s:
        rows = [x for x in s.scalars(select(SavedSearch)) if x.payload.get("pubmed_query")]
        for x in rows:
            p, pr = x.payload, (x.params or {})
            try:
                _, a100 = esearch_retry(p["pubmed_query"], pr.get("date_from"), pr.get("date_to"))
            except Exception as e:
                emit(f"{x.query[:38]:<40}  esearch KO ({type(e).__name__})")
                continue
            a20, a100s = a100[:20], set(a100)
            a20s = set(a20)
            B = local_pmids(s, p.get("keywords_en", []), p.get("mesh_terms", []),
                            pr.get("date_from"), pr.get("date_to"))
            v1 = list(dict.fromkeys([*a20, *B]))[: args.batch]
            v1l = sum(1 for q in v1 if q not in a20s)
            v2 = rrf(a100, B)[: args.batch]
            v2l = sum(1 for q in v2 if q not in a100s)
            a1 += v1l
            a2 += v2l
            n += 1
            emit(f"{x.query[:38]:<40}{v1l:>7}{v2l:>7}   {v2l - v1l:+d}")
            time.sleep(1.0)
    emit("-" * 64)
    emit(f"{'TOTAL locaux jugés (' + str(n) + ' req.)':<40}{a1:>7}{a2:>7}   {a2 - a1:+d}")
    out.close()


if __name__ == "__main__":
    sys.exit(main())
