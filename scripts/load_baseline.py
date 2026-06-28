"""Charge les fichiers PubMed .xml.gz locaux dans la base.

Usage :
    uv run python -m scripts.load_baseline                    # tous les fichiers non traités
    uv run python -m scripts.load_baseline --limit 25         # 25 premiers fichiers non traités
    uv run python -m scripts.load_baseline --from-num 1335 --limit 25   # updatefiles récents d'abord
    uv run python -m scripts.load_baseline --from-num 1335 --to-num 1459
    uv run python -m scripts.load_baseline --reparse          # réingère même si déjà fait
    uv run python -m scripts.load_baseline --no-verify        # saute la vérif MD5

Le suivi se fait dans la table ftp_state : un fichier déjà présent y est sauté.
"""

from __future__ import annotations

import argparse
import re
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FtpState
from app.services.pubmed_ftp import list_local_files, md5sum, verify_md5
from app.tasks.parse_articles import ingest_file

_FILE_NUM_RE = re.compile(r"pubmed\d+n(\d+)\.xml\.gz$")


def _file_num(name: str) -> int | None:
    m = _FILE_NUM_RE.search(name)
    return int(m.group(1)) if m else None


def ingest_local_files(
    *,
    limit: int | None = None,
    from_num: int | None = None,
    to_num: int | None = None,
    reparse: bool = False,
    no_verify: bool = False,
) -> int:
    """Ingère les .xml.gz locaux non encore traités. Renvoie le nb d'articles ingérés.

    `from_num`/`to_num` bornent par numéro de fichier (ex. from_num=1335 = updatefiles
    seuls, ne touche jamais la baseline). Le suivi `ftp_state` évite les doublons.
    """
    files = list_local_files()
    if not files:
        print("Aucun fichier .xml.gz trouvé sous DATA_DIR.")
        return 0

    if from_num is not None or to_num is not None:
        lo = from_num if from_num is not None else 0
        hi = to_num if to_num is not None else 10**9
        files = [f for f in files if (n := _file_num(f.name)) is not None and lo <= n <= hi]

    with SessionLocal() as session:
        done = set(session.scalars(select(FtpState.filename)).all())

    todo = [f for f in files if reparse or f.name not in done]
    if limit:
        todo = todo[:limit]

    print(f"{len(files)} fichier(s) au total, {len(todo)} à traiter.")
    grand_total = 0
    t0 = time.time()

    for i, path in enumerate(todo, 1):
        if path.stat().st_size < 1024:  # stub/téléchargement incomplet
            print(f"[{i}/{len(todo)}] vide, ignoré : {path.name}")
            continue
        if not no_verify and not verify_md5(path):
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
    return grand_total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="nombre max de fichiers à traiter")
    ap.add_argument("--from-num", type=int, default=None, help="ne traiter que les fichiers n° >= N (ex. 1335 = updatefiles)")
    ap.add_argument("--to-num", type=int, default=None, help="ne traiter que les fichiers n° <= N")
    ap.add_argument("--reparse", action="store_true", help="réingère les fichiers déjà dans ftp_state")
    ap.add_argument("--no-verify", action="store_true", help="ne pas vérifier le MD5")
    args = ap.parse_args()

    ingest_local_files(
        limit=args.limit,
        from_num=args.from_num,
        to_num=args.to_num,
        reparse=args.reparse,
        no_verify=args.no_verify,
    )


if __name__ == "__main__":
    main()
