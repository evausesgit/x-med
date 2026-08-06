"""Coût mesuré du juge selon modèle × effort, sur le pool du diagnostic du 06/08.

Deux lectures du coût, volontairement séparées :

- `total` = ce que remonte l'usage brut. Il gonfle dès que le modèle enchaîne des
  tours de raisonnement, car le contexte relu est recompté à chaque tour.
- `frais` = entrée NON mise en cache + sortie. C'est la part réellement recalculée ;
  l'entrée en cache est facturée à une fraction du tarif chez tous les fournisseurs.
  C'est la lecture honnête d'un écart de coût.

x-med passe par le CLI `codex` (quota d'abonnement), pas par l'API facturée : ces
tokens sont un proxy de consommation, pas une facture.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from analyse_bras import verdicts

NOMS = {
    "A_baseline": ("gpt-5.6-terra", "medium", "production"),
    "E_54_medium": ("gpt-5.4", "medium", "modèle seul"),
    "F_terra_high": ("gpt-5.6-terra", "high", "effort seul"),
    "B_pr73": ("gpt-5.4", "high", "PR #73 — les deux"),
}


def par_repetition(nom: str) -> list[dict]:
    art = json.loads(Path(f"artifacts/judge_{nom}.json").read_text())
    lignes = []
    for r in art["cases"][0]["repetitions"]:
        t = r["tokens"]
        frais = (t["input_tokens"] - t["cached_input_tokens"]) + t["output_tokens"]
        lignes.append(
            {
                "latence": r["latency_s"],
                "total": t["total_tokens"],
                "cache": t["cached_input_tokens"],
                "frais": frais,
                "retenus": sum(
                    1 for j in verdicts(r).values() if int(j.get("score", 0)) >= 2
                ),
            }
        )
    return lignes


def main() -> None:
    print(
        f"{'modèle':<16} {'effort':<7} {'rôle':<18} {'lat. méd':>9} "
        f"{'total méd':>10} {'frais méd':>10} {'retenus':>9}"
    )
    print("-" * 88)
    ref = None
    for nom, (modele, effort, role) in NOMS.items():
        lignes = par_repetition(nom)
        med = {k: statistics.median(x[k] for x in lignes) for k in ("latence", "total", "frais")}
        retenus = [x["retenus"] for x in lignes]
        if ref is None:
            ref = med
        print(
            f"{modele:<16} {effort:<7} {role:<18} {med['latence']:>8.0f}s "
            f"{med['total']:>10.0f} {med['frais']:>10.0f} {str(retenus):>9}"
        )

    print("\nDétail par répétition (le total est instable, pas le coût frais) :")
    for nom, (modele, effort, _) in NOMS.items():
        lignes = par_repetition(nom)
        tot = [f"{x['total']:>7,.0f}".replace(",", " ") for x in lignes]
        fra = [f"{x['frais']:>7,.0f}".replace(",", " ") for x in lignes]
        print(f"  {modele} / {effort:<7} total {' '.join(tot)}   frais {' '.join(fra)}")


if __name__ == "__main__":
    main()
