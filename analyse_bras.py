"""Lecture des artefacts judge_screen : que devient le seuil de rétention selon le bras ?

Les deux PMID « pont » sont les articles que la question appelle explicitement —
floppy eyelid ↔ apnée du sommeil, et apnée ↔ glaucome à pression normale. Ils ont
été notés 1 (sous le seuil de 2) par la production le 05/08, laissant la page vide.
Ce n'est PAS une vérité-terrain médicale : c'est un repère de lecture, à confirmer
par un médecin. Le tableau donne donc aussi la distribution complète des scores.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

PONTS = {
    39930146: "NTG ↔ apnée (STOP-Bang)",
    42454079: "FES ↔ apnée (umbrella review)",
}
SEUIL = 2

LIBELLES = {
    "A_baseline": "A · production (terra/medium)",
    "B_pr73": "B · PR #73 (gpt-5.4/high)",
    "C_no_evidence": "C · sans niveau de preuve",
    "D_neutral": "D · exemples neutres",
}


def verdicts(repetition: dict) -> dict[int, dict]:
    """Retourne {pmid: jugement} quelle que soit la forme exacte de l'artefact."""

    brut = repetition.get("judgements")
    if isinstance(brut, dict):
        return {int(k): v for k, v in brut.items()}
    if isinstance(brut, list):
        return {int(j["pmid"]): j for j in brut if "pmid" in j}
    return {}


def main() -> None:
    lignes = []
    for chemin in sorted(Path("artifacts").glob("judge_*.json")):
        art = json.loads(chemin.read_text())
        nom = chemin.stem.removeprefix("judge_")
        if not art.get("cases"):
            print(f"{LIBELLES.get(nom, nom)} : aucun cas terminé, bras ignoré")
            continue
        retenus, distributions, ponts = [], Counter(), {p: [] for p in PONTS}
        for cas in art["cases"]:
            for rep in cas.get("repetitions", []):
                v = verdicts(rep)
                if not v:
                    continue
                scores = [int(j.get("score", 0)) for j in v.values()]
                retenus.append(sum(1 for s in scores if s >= SEUIL))
                distributions.update(scores)
                for pmid in PONTS:
                    if pmid in v:
                        ponts[pmid].append(int(v[pmid].get("score", 0)))
        if not retenus:
            continue
        lignes.append((nom, retenus, distributions, ponts))

    print(f"\n{'bras':<32} {'retenus/50 (3 rép.)':<22} {'moy.':>6}   distribution des scores")
    print("-" * 100)
    for nom, retenus, dist, _ in lignes:
        d = " ".join(f"{s}:{dist[s]}" for s in range(4) if dist[s])
        print(
            f"{LIBELLES.get(nom, nom):<32} {str(retenus):<22} "
            f"{statistics.mean(retenus):>6.1f}   {d}"
        )

    print(f"\nScores des deux articles « pont » (seuil de rétention = {SEUIL}) :")
    for pmid, etiquette in PONTS.items():
        print(f"\n  PMID {pmid} — {etiquette}")
        for nom, _, _, ponts in lignes:
            s = ponts[pmid]
            marque = "  ← franchit le seuil" if s and statistics.mean(s) >= SEUIL else ""
            print(f"    {LIBELLES.get(nom, nom):<32} {s}{marque}")


if __name__ == "__main__":
    main()
