"""Charge les fichiers PubMed .xml.gz locaux dans la base.

Usage :
    uv run python -m scripts.load_baseline                 # tous les fichiers non traités
    uv run python -m scripts.load_baseline --limit 25      # 25 premiers fichiers
    uv run python -m scripts.load_baseline --reparse       # réingère même si déjà fait
    uv run python -m scripts.load_baseline --no-verify     # saute la vérif MD5

Le suivi se fait dans la table ftp_state : un fichier déjà présent y est sauté.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FtpState
from app.services.pubmed_ftp import list_local_files, md5sum, verify_md5
from app.tasks.parse_articles import ingest_file


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="nombre max de fichiers à traiter")
    ap.add_argument("--reparse", action="store_true", help="réingère les fichiers déjà dans ftp_state")
    ap.add_argument("--no-verify", action="store_true", help="ne pas vérifier le MD5")
    args = ap.parse_args()

    files = list_local_files()
    if not files:
        print("Aucun fichier .xml.gz trouvé sous DATA_DIR.")
        return

    with SessionLocal() as session:
        done = set(session.scalars(select(FtpState.filename)).all())

    todo = [f for f in files if args.reparse or f.name not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(files)} fichier(s) au total, {len(todo)} à traiter.")
    grand_total = 0
    t0 = time.time()

    for i, path in enumerate(todo, 1):
        if path.stat().st_size < 1024:  # stub/téléchargement incomplet
            print(f"[{i}/{len(todo)}] vide, ignoré : {path.name}")
            continue
        if not args.no_verify and not verify_md5(path):
            print(f"[{i}/{len(todo)}] MD5 INVALIDE, ignoré : {path.name}")
            continue

        ts = time.time()
        with SessionLocal() as session:
            stats = ingest_file(session, path)
            session.merge(
                FtpState(
                    filename=path.name,
                    checksum=md5sum(path),
                    article_count=stats["articles"],
                )
            )
            session.commit()

        grand_total += stats["articles"]
        dt = time.time() - ts
        print(
            f"[{i}/{len(todo)}] {path.name} : "
            f"{stats['articles']} articles, {stats['deleted']} suppressions ({dt:.1f}s)"
        )

    print(f"\nTerminé : {grand_total} articles ingérés en {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
