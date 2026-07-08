"""Remplissage initial de `article_search` depuis `articles` (une seule fois).

Cette table étroite (fenêtre glissante des dernières années) rend le pré-filtre FTS
du pipeline PubMed rapide en permanence (voir migration 0006 et le modèle
`ArticleSearch`). Le schéma + la maintenance auto (trigger + prune) sont posés par la
migration ; le premier remplissage est ici car il lit ~3,4 M lignes / ~7 Go de
`articles` (~20 min) — trop lourd pour une migration jouée à chaque déploiement.

Séquence de mise en service :
    1. déployer (migration 0006 applique le schéma + le trigger) ;
    2. `uv run python -m scripts.backfill_article_search`  (ce script) ;
    3. activer `USE_NARROW_SEARCH=true` et redémarrer l'API.

Idempotent : `ON CONFLICT DO UPDATE`, et sûr à relancer. Le trigger tient déjà la
table à jour en continu ; ce backfill ne sert qu'à charger l'existant.
"""

from __future__ import annotations

import time

from sqlalchemy import text

from app.db import engine


def main() -> None:
    t0 = time.monotonic()
    with engine.begin() as conn:
        min_year = conn.execute(text("SELECT article_search_min_year()")).scalar_one()
        print(f"Fenêtre : pub_year >= {min_year}. Remplissage de article_search…")
        # INSERT … SELECT en une passe. ON CONFLICT pour l'idempotence (et pour
        # absorber les lignes déjà posées par le trigger pendant le backfill).
        conn.execute(
            text(
                """
                INSERT INTO article_search (pmid, pub_year, fts)
                SELECT pmid, pub_year, fts
                FROM articles
                WHERE pub_year >= article_search_min_year()
                ON CONFLICT (pmid) DO UPDATE
                    SET pub_year = EXCLUDED.pub_year, fts = EXCLUDED.fts
                """
            )
        )
        n = conn.execute(text("SELECT count(*) FROM article_search")).scalar_one()
    dt = time.monotonic() - t0
    print(f"OK — {n:,} lignes dans article_search en {dt:.0f}s.")
    print("Pense à : USE_NARROW_SEARCH=true puis redémarrage de l'API.")


if __name__ == "__main__":
    main()
