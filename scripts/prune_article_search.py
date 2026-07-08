"""Élague `article_search` : supprime les articles sortis de la fenêtre glissante.

La table ne garde que les dernières années (voir migration 0006). Le trigger
ajoute les nouveaux articles (entrée) ; ce script appelle `article_search_prune()`
qui supprime ceux dont l'année est passée sous la borne (sortie). Sans lui, la table
grossirait indéfiniment.

La borne ne bouge qu'au changement d'année civile — un passage **mensuel** suffit
largement. À brancher en tâche planifiée Coolify sur le worker (comme pubmed_daily) :

    uv run python -m scripts.prune_article_search        # cron: 0 3 1 * * (le 1er du mois)
"""

from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def main() -> None:
    with engine.begin() as conn:
        min_year = conn.execute(text("SELECT article_search_min_year()")).scalar_one()
        n = conn.execute(text("SELECT article_search_prune()")).scalar_one()
    print(f"Prune article_search (< {min_year}) : {n:,} lignes supprimées.")


if __name__ == "__main__":
    main()
