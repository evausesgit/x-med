"""Nettoie l'historique des recherches (`saved_searches`).

Depuis la sauvegarde automatique, chaque recherche aboutie laisse une ligne —
et chaque ligne porte le snapshot complet du résultat (jusqu'à quelques
centaines de Ko d'abstracts). Sans élagage, la table grossit indéfiniment.

Deux limites, appliquées ensemble (0 = limite désactivée) :

- **âge** : `SAVED_SEARCH_RETENTION_DAYS` (défaut 90 jours) ;
- **nombre** : `SAVED_SEARCH_MAX_ROWS` (défaut 500), les plus anciennes partent
  en premier.

Relancer une recherche supprimée ne perd rien d'irremplaçable : elle est
simplement rejouée (nouvel appel codex). À brancher en tâche planifiée Coolify
sur le worker, comme `prune_article_search` :

    uv run python -m scripts.cleanup_saved_searches            # cron: 0 4 * * *
    uv run python -m scripts.cleanup_saved_searches --dry-run  # ce qui partirait
    uv run python -m scripts.cleanup_saved_searches --days 30 --max 200
"""

from __future__ import annotations

import argparse

from app.config import settings
from app.services import saved_search_store


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--days", type=int, default=settings.saved_search_retention_days,
        help="âge maximum en jours (0 = pas de limite d'âge)",
    )
    p.add_argument(
        "--max", type=int, default=settings.saved_search_max_rows,
        dest="max_rows", help="nombre maximum de recherches gardées (0 = illimité)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="compte les recherches visées sans rien supprimer",
    )
    args = p.parse_args()

    n = saved_search_store.purge(
        days=args.days, max_rows=args.max_rows, dry_run=args.dry_run
    )
    limits = f"> {args.days} j" if args.days else "pas de limite d'âge"
    limits += f", au-delà de {args.max_rows} lignes" if args.max_rows else ", sans plafond"
    verb = "à supprimer" if args.dry_run else "supprimées"
    print(f"Nettoyage saved_searches ({limits}) : {n} recherche(s) {verb}.")


if __name__ == "__main__":
    main()
