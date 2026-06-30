#!/usr/bin/env python3
"""Mesure de couverture pour l'« algo 2 » (PubMed-first, classé Best Match).

Question posée : si, au lieu de plafonner PubMed à 20 (algo v1), on récupérait
un GRAND lot de PMID dans l'ordre de pertinence PubMed (Best Match), combien
en aurait-on DÉJÀ en base locale (avec un abstract exploitable) — et donc
combien faudrait-il TÉLÉCHARGER pour pouvoir analyser le top PubMed ?

Pour chaque recherche sauvegardée (table saved_searches), on réutilise la
`pubmed_query` déjà stockée dans son snapshot (donc AUCUN appel IA), on relance
un esearch large, puis on confronte les PMID à la table `articles`.

Lecture seule. N'appelle pas codex. Ne touche pas au pipeline v1.

Usage :
    python -m scripts.pubmed_coverage                 # défauts : retmax 200, top 50
    python -m scripts.pubmed_coverage --retmax 500 --top 50
    python -m scripts.pubmed_coverage --limit 5       # 5 premières recherches
    python -m scripts.pubmed_coverage --csv /tmp/cov.csv
"""

from __future__ import annotations

import argparse
import csv
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models.article import Article
from app.models.saved_search import SavedSearch
from app.services import pubmed_eutils as eut


def _abstract_ok(a: str | None) -> bool:
    return bool(a and a.strip())


def _trunc(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def coverage_for(session, pubmed_query: str, date_from, date_to, retmax: int, top: int) -> dict:
    """Métriques de couverture d'UNE requête. `a_pmids` est dans l'ordre PubMed."""
    total, a_pmids = eut.esearch(
        pubmed_query, retmax=retmax, sort="relevance",
        mindate=date_from, maxdate=date_to,
    )
    # Quels PMID sont en base, et lesquels ont un abstract exploitable ?
    have_abs: dict[int, bool] = {}
    if a_pmids:
        rows = session.execute(
            select(Article.pmid, Article.abstract).where(Article.pmid.in_(a_pmids))
        ).all()
        have_abs = {p: _abstract_ok(ab) for p, ab in rows}

    in_base = sum(1 for p in a_pmids if p in have_abs)
    in_base_abs = sum(1 for p in a_pmids if have_abs.get(p))

    # Le chiffre clé : pour juger le top-`top` de PubMed, combien sont déjà
    # exploitables localement (abstract en base) vs combien à télécharger ?
    top_pmids = a_pmids[:top]
    top_have_abs = sum(1 for p in top_pmids if have_abs.get(p))
    top_to_dl = len(top_pmids) - top_have_abs

    return {
        "total": total,                 # ce que PubMed trouve au total (≥ retrieved)
        "retrieved": len(a_pmids),      # ce qu'on a vraiment ramené (≤ retmax)
        "in_base": in_base,             # déjà chez nous (peu importe l'abstract)
        "in_base_abs": in_base_abs,     # déjà chez nous AVEC abstract
        "to_download": len(a_pmids) - in_base,  # absents de la base
        "top": len(top_pmids),
        "top_have_abs": top_have_abs,   # jugeables SANS téléchargement dans le top
        "top_to_dl": top_to_dl,         # à télécharger pour juger TOUT le top
        "a_pmids": a_pmids,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--retmax", type=int, default=200, help="taille du lot PubMed (sans cap à 20)")
    ap.add_argument("--top", type=int, default=50, help="taille du lot jugé (comparable à judge_batch)")
    ap.add_argument("--limit", type=int, default=None, help="ne traiter que les N premières recherches")
    ap.add_argument("--sleep", type=float, default=0.35, help="pause entre esearch (politesse NCBI)")
    ap.add_argument("--csv", type=str, default=None, help="écrire le détail dans ce fichier CSV")
    args = ap.parse_args()

    with SessionLocal() as session:
        searches = list(
            session.scalars(
                select(SavedSearch).order_by(SavedSearch.created_at.desc())
            ).all()
        )
        if args.limit:
            searches = searches[: args.limit]

        print(f"\n{len(searches)} recherches · retmax={args.retmax} · top={args.top}\n")
        header = (
            f"{'requête':<34} {'totPM':>6} {'ret':>4} {'base':>4} "
            f"{'b+abs':>5} {'DL':>4} │ top{args.top}: {'noDL':>4} {'àDL':>4}  v1∩top"
        )
        print(header)
        print("─" * len(header))

        rows_csv = []
        agg = {"top_have_abs": 0, "top_to_dl": 0, "top": 0, "v1_in_top": 0, "v1_kept": 0}
        for s in searches:
            payload = s.payload or {}
            pq = payload.get("pubmed_query") or s.query  # repli : question brute
            params = s.params or {}
            cov = coverage_for(
                session, pq, params.get("date_from"), params.get("date_to"),
                args.retmax, args.top,
            )

            # Recouvrement avec les résultats RETENUS par le v1 (payload.results) :
            # combien des « bons » du v1 réapparaissent dans le top PubMed ?
            v1_kept = {r["pmid"] for r in payload.get("results", []) if "pmid" in r}
            top_set = set(cov["a_pmids"][: args.top])
            v1_in_top = len(v1_kept & top_set)

            print(
                f"{_trunc(s.query, 34):<34} {cov['total']:>6} {cov['retrieved']:>4} "
                f"{cov['in_base']:>4} {cov['in_base_abs']:>5} {cov['to_download']:>4} │ "
                f"      {cov['top_have_abs']:>4} {cov['top_to_dl']:>4}  "
                f"{v1_in_top:>3}/{len(v1_kept):<3}"
            )

            agg["top_have_abs"] += cov["top_have_abs"]
            agg["top_to_dl"] += cov["top_to_dl"]
            agg["top"] += cov["top"]
            agg["v1_in_top"] += v1_in_top
            agg["v1_kept"] += len(v1_kept)
            rows_csv.append({
                "query": s.query, "pubmed_query": pq,
                "date_from": params.get("date_from"), "date_to": params.get("date_to"),
                **{k: v for k, v in cov.items() if k != "a_pmids"},
                "v1_kept": len(v1_kept), "v1_in_top": v1_in_top,
            })
            time.sleep(args.sleep)

        print("─" * len(header))
        if agg["top"]:
            pct_nodl = 100 * agg["top_have_abs"] / agg["top"]
            print(
                f"\nBILAN (sur le top-{args.top}) :\n"
                f"  • jugeables SANS téléchargement : {agg['top_have_abs']}/{agg['top']} "
                f"({pct_nodl:.0f} %)\n"
                f"  • à télécharger pour le top complet : {agg['top_to_dl']}/{agg['top']} "
                f"({100 - pct_nodl:.0f} %)\n"
                f"  • résultats v1 retrouvés dans le top PubMed : "
                f"{agg['v1_in_top']}/{agg['v1_kept']}"
            )

        if args.csv:
            with open(args.csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows_csv[0].keys()))
                w.writeheader()
                w.writerows(rows_csv)
            print(f"\nDétail CSV → {args.csv}")


if __name__ == "__main__":
    main()
