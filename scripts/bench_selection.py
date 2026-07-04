#!/usr/bin/env python3
"""Passage CONTRÔLÉ v1 vs v2 au niveau de la SÉLECTION (sans Codex-juge).

Complète `scripts.bench_v1_v2` (qui mesure le bout-en-bout réel, garde-fou 8 s compris).
Ici on isole la SEULE différence de conception entre v1 et v2 — quels candidats entrent
dans le lot de 50 que Codex jugera — en neutralisant deux bruits du run production :

  1. la variance de Codex à la construction de requête  → on RÉUTILISE la requête déjà
     construite (keywords_en / mesh_terms) lue dans bench/v1_v2/results.json (aucun appel
     Codex ici) ;
  2. le garde-fou local 8 s qui coupe le vivier local sur les termes courants → on relance
     la requête locale avec un timeout GÉNÉREUX (120 s), pour voir v1/v2 « comme prévues ».

Pour chaque requête on compare, dans le lot des 50 candidats jugés :
  - « prod (8 s) »  : local vide s'il a été coupé → v1 juge A[:12], v2 juge A[:50] ;
  - « désigné »     : local complet (120 s) → combien d'articles LOCAUX-seuls entrent
                       dans les 50, pour v1 (PubMed d'abord) et pour v2 (fusion RRF).

C'est la mesure qui dit si la fusion RRF de v2 apporte réellement du rappel local, et
combien le garde-fou 8 s en fait perdre aujourd'hui.

Sortie : bench/v1_v2/selection.md (+ selection.json). Lecture seule, robuste au 429 NCBI.

Usage : uv run python -m scripts.bench_selection [--in bench/v1_v2/results.json]
                                                 [--local-timeout-ms 120000] [--batch 50]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.models.article import Article
from app.services import pubmed_eutils as eut


def esearch_retry(term, dfrom, dto, retmax=100, tries=10, wait=60):
    for i in range(tries):
        try:
            return eut.esearch(term, retmax=retmax, sort="relevance", mindate=dfrom, maxdate=dto)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 429:
                print(f"      429 NCBI, attente {wait}s ({i+1}/{tries})…", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("esearch : rate-limit persistant")


def local_full(s, keywords, dfrom, dto, limit, timeout_ms):
    """Vivier local FTS-seul (comme la prod) mais avec timeout généreux. → (pmids, secs, timed_out)."""
    ts = " OR ".join(keywords) if keywords else "medicine"
    tsq = func.websearch_to_tsquery("english", ts)
    conds = [Article.fts.op("@@")(tsq)]
    if dfrom:
        conds.append(Article.pub_year >= int(dfrom[:4]))
    if dto:
        conds.append(Article.pub_year <= int(dto[:4]))
    t0 = time.monotonic()
    try:
        with s.begin_nested():
            s.execute(sql_text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
            pmids = list(s.scalars(
                select(Article.pmid).where(*conds)
                .order_by(func.ts_rank(Article.fts, tsq).desc()).limit(limit)
            ))
        return pmids, round(time.monotonic() - t0, 1), False
    except OperationalError:
        return [], round(time.monotonic() - t0, 1), True


def rrf(a, b, K=60):
    sc: dict[int, float] = {}
    for lst in (a, b):
        for r, p in enumerate(lst):
            sc[p] = sc.get(p, 0.0) + 1.0 / (K + r)
    return sorted(set(a) | set(b), key=lambda p: -sc[p])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="bench/v1_v2/results.json")
    ap.add_argument("--local-timeout-ms", type=int, default=120000)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--out-dir", default="bench/v1_v2")
    args = ap.parse_args()

    data = json.loads(Path(args.infile).read_text())
    w = data["window"]
    dfrom, dto = w["from"], w["to"]
    out = []

    with SessionLocal() as s:
        for q in data["queries"]:
            e = q.get("v1") or q.get("v2")
            if not e or "error" in e:
                continue
            query = q["query"]
            kws = e.get("keywords_en") or []
            pubmed_query = e.get("pubmed_query") or query
            print(f"\n• {query}", flush=True)
            try:
                _, a100 = esearch_retry(pubmed_query, dfrom, dto, retmax=100)
            except Exception as exc:  # noqa: BLE001
                print(f"    esearch KO: {exc}", flush=True)
                continue
            a12, a100s, a12s = a100[:12], set(a100), set(a100[:12])
            B, secs, timed = local_full(s, kws, dfrom, dto, 200, args.local_timeout_ms)
            print(f"    local (généreux {args.local_timeout_ms/1000:.0f}s): "
                  f"{len(B)} candidats en {secs}s{' — ENCORE trop long' if timed else ''}",
                  flush=True)

            # Lot de 50 « comme désigné » (local complet)
            v1_batch = list(dict.fromkeys([*a12, *B]))[: args.batch]
            v2_batch = rrf(a100, B)[: args.batch]
            v1_local = sum(1 for p in v1_batch if p not in a12s)
            v2_local = sum(1 for p in v2_batch if p not in a100s)

            out.append({
                "query": query, "esearch_n": len(a100),
                "local_full": len(B), "local_secs": secs, "local_timed_out": timed,
                "v1_local_in_batch": v1_local, "v2_local_in_batch": v2_local,
            })
            time.sleep(1.0)

    # ---- Rapport ----
    L = ["# Passage contrôlé — sélection des candidats (v1 vs v2, sans Codex-juge)\n"]
    L.append(f"_Fenêtre {dfrom} → {dto} · local timeout généreux "
             f"{args.local_timeout_ms/1000:.0f}s · lot de {args.batch}._\n")
    L.append("« local-seul dans le lot » = articles de NOTRE base (absents de la fenêtre "
             "PubMed) qui entrent dans les 50 candidats jugés. C'est le rappel local que "
             "chaque méthode apporte **quand le local n'est pas coupé**.\n")
    L.append("| Requête | PubMed | Local (complet) | temps local | v1 local-seul /50 | v2 local-seul /50 |")
    L.append("|---|--:|--:|--:|--:|--:|")
    t1 = t2 = 0
    for r in out:
        t1 += r["v1_local_in_batch"]; t2 += r["v2_local_in_batch"]
        flag = " ⚠️>timeout" if r["local_timed_out"] else ""
        L.append(f"| {r['query'][:38]} | {r['esearch_n']} | {r['local_full']}{flag} | "
                 f"{r['local_secs']}s | {r['v1_local_in_batch']} | {r['v2_local_in_batch']} |")
    n = len(out) or 1
    L.append(f"\n**Total local-seul dans le lot ({n} req.) : v1 = {t1} · v2 = {t2} "
             f"(Δ = {t2 - t1:+d}).**\n")
    L.append("Rappel : en **production (garde-fou 8 s)**, le local est coupé sur la quasi-"
             "totalité de ces requêtes → local-seul jugé = **0** des deux côtés. Ce tableau "
             "montre donc à la fois (a) l'écart de conception v1↔v2 et (b) ce que le garde-fou "
             "8 s fait perdre aujourd'hui.")

    Path(args.out_dir, "selection.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    Path(args.out_dir, "selection.md").write_text("\n".join(L) + "\n")
    print(f"\n✅ → {args.out_dir}/selection.md")


if __name__ == "__main__":
    main()
