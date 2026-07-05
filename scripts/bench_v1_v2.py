#!/usr/bin/env python3
"""Benchmark franc v1 vs v2 de la recherche PubMed + IA.

Rejoue une liste de requêtes cliniques FR à travers les DEUX versions du sélecteur
« TRI » de la recherche PubMed + IA, en appelant la MÊME fonction que la production
(`app.api.search._run_deep_search`), donc sans notification Hermes ni endpoint HTTP.

Paramètres reproduisant EXACTEMENT ce que l'UI envoie :
  - v1 « score IA » (défaut) : k_pubmed=20, rrf=False, judge_batch=50, local_floor=0
  - v2 « fusion RRF »         : k_pubmed=50, rrf=True,  judge_batch=50, local_floor=0
  (max_local=200, min_score=2, fenêtre de dates communes aux deux)

Capture, par (requête, version) :
  - nombres d'articles à chaque étape (counts : pubmed/local/merged/judgeable/judged/kept
    + provenance des retenus kept_pubmed/kept_local/kept_both) ;
  - temps total ET par phase (via le callback de progression) ;
  - garde-fou local déclenché ou non (filter_timeout) ;
  - tokens codex (requête + jugement) ;
  - articles retenus (pmid, score, %, source, année, niveau de preuve, titre).

Et, par requête, la COMPARAISON v1↔v2 : recouvrement des PMID retenus (Jaccard),
tête de liste partagée, part de « local seul », distribution des scores, écart de temps.

Sorties : bench/v1_v2/results.json (brut) + bench/v1_v2/report.md (lisible/partageable).

Usage :
    uv run python -m scripts.bench_v1_v2 \
        [--date-from 2025-01-01] [--date-to 2026-07-04] [--out-dir bench/v1_v2]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from app.api.search import DeepSearchRequest, _run_deep_search
from app.db import SessionLocal

# Requêtes cliniques FR réalistes, réparties sur plusieurs spécialités et types
# (traitement, dépistage, diagnostic, comparaison de molécules) + une volontairement
# LARGE (« fibrillation atriale / hémorragie ») pour exercer le garde-fou local.
DEFAULT_QUERIES = [
    "Inhibiteurs du SGLT2 dans l'insuffisance cardiaque à fraction d'éjection préservée",
    "Efficacité du sémaglutide oral dans le diabète de type 2",
    "Dépistage du cancer du col de l'utérus par test HPV",
    "Prise en charge de la dégénérescence maculaire liée à l'âge néovasculaire",
    "Antibiothérapie de la pneumonie aiguë communautaire de l'adulte",
    "Anticoagulation et risque hémorragique dans la fibrillation atriale",
    "Corticoïdes dans le traitement de la COVID-19 sévère",
    "Immunothérapie adjuvante dans le mélanome de stade III",
]

VERSIONS = {
    "v1": dict(k_pubmed=20, rrf=False, judge_batch=50, local_floor=0, max_local=200),
    "v2": dict(k_pubmed=50, rrf=True, judge_batch=50, local_floor=0, max_local=200),
}


def run_one(query: str, version: str, params: dict, date_from: str, date_to: str) -> dict:
    """Exécute une recherche et renvoie un dict sérialisable avec toutes les mesures."""
    phases: list[dict] = []
    t0 = time.monotonic()

    def progress(phase: str, msg: str, data: dict) -> None:
        phases.append({"phase": phase, "elapsed_s": round(time.monotonic() - t0, 2), "msg": msg})

    req = DeepSearchRequest(
        query=query, date_from=date_from, date_to=date_to,
        k_pubmed=params["k_pubmed"], max_local=params["max_local"],
        rrf=params["rrf"], judge_batch=params["judge_batch"],
        local_floor=params["local_floor"], min_score=2,
    )
    with SessionLocal() as session:
        res = _run_deep_search(req, session, progress)

    total_s = round(time.monotonic() - t0, 2)
    local_timed_out = any(p["phase"] == "filter_timeout" for p in phases)

    results = [
        {
            "pmid": h.pmid, "score": h.score, "relevance_pct": h.relevance_pct,
            "source": h.source, "pub_year": h.pub_year,
            "evidence_level": h.evidence_level, "title": h.title,
        }
        for h in res.results
    ]
    return {
        "version": version, "params": params, "total_s": total_s,
        "local_timed_out": local_timed_out,
        "builder": res.query_builder, "judge": res.judge,
        "pubmed_query": res.pubmed_query, "mesh_terms": res.mesh_terms,
        "keywords_en": res.keywords_en,
        "counts": res.counts, "codex_tokens": res.codex_tokens,
        "phases": phases, "results": results,
    }


def _pmids(entry: dict) -> set[int]:
    return {r["pmid"] for r in entry["results"]}


def _kept_by_source(entry: dict) -> dict:
    c = entry["counts"]
    return {"pubmed": c.get("kept_pubmed", 0), "local": c.get("kept_local", 0),
            "both": c.get("kept_both", 0)}


def _score_dist(entry: dict) -> dict:
    d = {3: 0, 2: 0}
    for r in entry["results"]:
        if r["score"] in d:
            d[r["score"]] += 1
    return {"s3": d[3], "s2": d[2]}


def jaccard(a: set, b: set) -> float:
    return round(len(a & b) / len(a | b), 3) if (a or b) else 0.0


def build_report(data: dict) -> str:
    L: list[str] = []
    w = data["window"]
    L.append("# Benchmark franc — Recherche PubMed + IA : v1 vs v2\n")
    L.append(f"_Généré le {data['generated_at']} · fenêtre **{w['from']} → {w['to']}** · "
             f"{len(data['queries'])} requêtes cliniques._\n")
    L.append("## Méthode\n")
    L.append("Chaque requête est rejouée dans les deux versions via la **même fonction que "
             "la production** (`_run_deep_search`). Paramètres identiques à l'UI :\n")
    L.append("- **v1 · score IA** (défaut) : `k_pubmed=20`, fusion « PubMed d'abord », lot 50.")
    L.append("- **v2 · fusion RRF** : `k_pubmed=50`, fusion RRF (local non enterré), lot 50.")
    L.append("- Communs : `max_local=200`, `min_score=2`, même fenêtre de dates.\n")
    L.append("Le **tri final est toujours le score Codex** dans les deux cas ; v1/v2 ne "
             "changent que **quels candidats sont jugés**.\n")

    # ---- Tableau récapitulatif par requête ----
    L.append("## Résultats par requête\n")
    L.append("| Requête | Ver. | Temps | PubMed | Local | Fusion | Jugés | **Retenus** | dont local-seul | Score 3/2 | Local coupé (8s) |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|")
    agg = {"v1": [], "v2": []}
    for q in data["queries"]:
        for v in ("v1", "v2"):
            e = q.get(v)
            if not e or "error" in e:
                L.append(f"| {q['query'][:34]} | {v} | — | — | — | — | — | ERREUR | — | — | — |")
                continue
            c = e["counts"]; ks = _kept_by_source(e); sd = _score_dist(e)
            agg[v].append(e)
            L.append(
                f"| {q['query'][:34] if v=='v1' else ''} | {v} | {e['total_s']:.0f}s | "
                f"{c.get('pubmed','?')} | {c.get('local','?')} | {c.get('merged','?')} | "
                f"{c.get('judged','?')} | **{c.get('kept','?')}** | {ks['local']} | "
                f"{sd['s3']}/{sd['s2']} | {'⏱️ oui' if e['local_timed_out'] else '—'} |"
            )

    # ---- Comparaison v1↔v2 par requête ----
    L.append("\n## Recouvrement v1 ↔ v2 (articles retenus)\n")
    L.append("| Requête | Retenus v1 | Retenus v2 | Communs | Jaccard | Temps v1→v2 |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for q in data["queries"]:
        e1, e2 = q.get("v1"), q.get("v2")
        if not (e1 and e2 and "error" not in e1 and "error" not in e2):
            L.append(f"| {q['query'][:40]} | — | — | — | — | — |")
            continue
        s1, s2 = _pmids(e1), _pmids(e2)
        L.append(
            f"| {q['query'][:40]} | {len(s1)} | {len(s2)} | {len(s1 & s2)} | "
            f"{jaccard(s1, s2)} | {e1['total_s']:.0f}s → {e2['total_s']:.0f}s |"
        )

    # ---- Agrégats ----
    def _avg(lst, key):
        vals = [x[key] for x in lst]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    def _avg_count(lst, key):
        vals = [x["counts"].get(key, 0) for x in lst]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    L.append("\n## Agrégats (moyennes)\n")
    L.append("| Mesure | v1 | v2 |")
    L.append("|---|--:|--:|")
    L.append(f"| Temps moyen | {_avg(agg['v1'],'total_s')}s | {_avg(agg['v2'],'total_s')}s |")
    L.append(f"| PubMed récupérés (moy.) | {_avg_count(agg['v1'],'pubmed')} | {_avg_count(agg['v2'],'pubmed')} |")
    L.append(f"| Candidats fusionnés (moy.) | {_avg_count(agg['v1'],'merged')} | {_avg_count(agg['v2'],'merged')} |")
    L.append(f"| Retenus (moy.) | {_avg_count(agg['v1'],'kept')} | {_avg_count(agg['v2'],'kept')} |")
    L.append(f"| dont local-seul (moy.) | {_avg_count(agg['v1'],'kept_local')} | {_avg_count(agg['v2'],'kept_local')} |")
    L.append(f"| Tokens codex (moy.) | {_avg([{'total_s':x['codex_tokens'].get('total',0)} for x in agg['v1']],'total_s')} "
             f"| {_avg([{'total_s':x['codex_tokens'].get('total',0)} for x in agg['v2']],'total_s')} |")

    L.append("\n## Lecture (à valider par des médecins)\n")
    L.append("- **Temps** : mesuré ci-dessus, dominé par les 2 appels Codex (requête + jugement).")
    L.append("- **Rappel du local** : `dont local-seul` = articles retenus présents UNIQUEMENT "
             "dans notre base (invisibles de la fenêtre PubMed). C'est l'axe où v2 est censée "
             "battre v1.")
    L.append("- **Jaccard v1↔v2** : proche de 1 = les deux versions renvoient la même chose ; "
             "bas = elles divergent (et il faut un médecin pour dire laquelle a raison).")
    L.append("\n> ⚠️ Ce benchmark chiffre le COMPORTEMENT (vitesse, volumes, recouvrement, "
             "provenance). Il **ne juge pas la pertinence clinique** : seul un médecin, en "
             "aveugle, peut dire si les articles retenus sont les bons. C'est l'étape suivante.")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-from", default="2025-01-01")
    ap.add_argument("--date-to", default=date.today().isoformat())
    ap.add_argument("--out-dir", default="bench/v1_v2")
    ap.add_argument("--queries", nargs="*", default=None)
    args = ap.parse_args()

    queries = args.queries or DEFAULT_QUERIES
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "window": {"from": args.date_from, "to": args.date_to},
        "versions": VERSIONS, "queries": [],
    }

    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] {query}", flush=True)
        entry = {"query": query}
        for v, params in VERSIONS.items():
            print(f"    → {v} …", end="", flush=True)
            try:
                e = run_one(query, v, params, args.date_from, args.date_to)
                entry[v] = e
                c = e["counts"]
                print(f" {e['total_s']:.0f}s · retenus {c.get('kept','?')} "
                      f"(local-seul {c.get('kept_local','?')})"
                      f"{' · LOCAL COUPÉ 8s' if e['local_timed_out'] else ''}", flush=True)
            except Exception as exc:  # noqa: BLE001 — un échec ne doit pas tuer le run
                entry[v] = {"error": f"{type(exc).__name__}: {exc}"}
                print(f" ERREUR {type(exc).__name__}: {exc}", flush=True)
            time.sleep(1.0)  # courtoisie NCBI
        data["queries"].append(entry)
        # écriture incrémentale (on ne perd rien si ça coupe)
        (out_dir / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        (out_dir / "report.md").write_text(build_report(data))

    print(f"\n✅ Terminé → {out_dir}/results.json et {out_dir}/report.md")


if __name__ == "__main__":
    main()
