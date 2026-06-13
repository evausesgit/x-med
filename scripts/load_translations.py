"""Charge les traductions FR (bench/translations/*.json) dans la table article_fr.

Les fichiers JSON sont l'artefact durable et versionné ; la table `article_fr`
n'est qu'un cache pour l'affichage sur /annotate (alimenté par ce script).

Format de chaque fichier (clé = pmid en chaîne) :
    {"40299082": {"title_fr": "...", "abstract_fr": "..."}, ...}

Usage :
    uv run python -m scripts.load_translations            # charge tout bench/translations/*.json
    uv run python -m scripts.load_translations --status    # couverture du pool
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text as sql_text

from app.db import SessionLocal

TRANS_DIR = Path(__file__).parent.parent / "bench" / "translations"


def do_load() -> None:
    files = sorted(TRANS_DIR.glob("*.json"))
    if not files:
        print(f"Aucun fichier dans {TRANS_DIR}")
        return
    n = 0
    with SessionLocal() as s:
        for f in files:
            data = json.loads(f.read_text())
            for pmid, tr in data.items():
                s.execute(
                    sql_text(
                        """
                        INSERT INTO article_fr (pmid, title_fr, abstract_fr, updated_at)
                        VALUES (:pmid, :t, :a, now())
                        ON CONFLICT (pmid) DO UPDATE
                          SET title_fr = EXCLUDED.title_fr,
                              abstract_fr = EXCLUDED.abstract_fr,
                              updated_at = now()
                        """
                    ),
                    {"pmid": int(pmid), "t": tr.get("title_fr"), "a": tr.get("abstract_fr")},
                )
                n += 1
            print(f"  {f.name}: {len(data)} traductions")
        s.commit()
    print(f"→ {n} traductions chargées dans article_fr.")


def do_status() -> None:
    with SessionLocal() as s:
        tot, done = s.execute(
            sql_text(
                """
                SELECT count(DISTINCT p.pmid),
                       count(DISTINCT p.pmid) FILTER (WHERE fr.abstract_fr IS NOT NULL)
                FROM eval_pool p
                LEFT JOIN article_fr fr ON fr.pmid = p.pmid
                """
            )
        ).one()
    print(f"Pool : {done}/{tot} articles avec traduction FR ({done / max(tot, 1):.0%})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="afficher la couverture de traduction")
    args = ap.parse_args()
    if args.status:
        do_status()
    else:
        do_load()


if __name__ == "__main__":
    main()
