#!/usr/bin/env python3
"""Sauvegarde de la base backoffice — cron quotidien (prod) et lancement manuel.

Dump `pg_dump -Fc` des 7 tables métier + `alembic_version_app`, avec
publication ATOMIQUE : rien n'apparaît sous son nom final tant que le dump n'a
pas été vérifié. Ces dumps servent de backup prod ET de seed des previews
(voir PLAN_EXECUTION_COMPOSE.md § étape 4).

Déroulé (sous verrou exclusif — deux backups simultanés sont interdits) :
1. sonde de la base : `alembic_version_app` doit exister (son absence n'est
   tolérée qu'avec `--allow-unversioned`, cas de la base monolithique
   actuelle — une fois la nouvelle prod active, c'est un symptôme) ;
2. `pg_dump -Fc` vers `backoffice_<horodatage UTC>.dump.tmp` (stdout capturé —
   le binaire n'a pas besoin de voir le système de fichiers de sortie) ;
3. vérification : code retour, puis `pg_restore --list` qui doit citer chaque
   table demandée ;
4. sha256 écrit à côté (`<nom>.dump.sha256`), fsync, rename `.tmp` → `.dump` ;
5. manifeste `latest.json` mis à jour EN DERNIER (tmp + rename atomique) —
   c'est LA source de vérité : `{"file", "sha256", "alembic_revision"}`. Les
   dumps horodatés sont immuables ; l'init des previews lit le manifeste puis
   vérifie le fichier désigné ;
6. rétention : on garde les `--keep` générations les plus récentes (le dump
   référencé par `latest.json` n'est jamais supprimé).

Tout échec → exit non-zéro avec message clair, et le `.tmp` de ce run est
supprimé (un `.tmp` orphelin ne doit jamais masquer un vieux dump valide).

Prérequis : `pg_dump` / `pg_restore` 16 dans le PATH (en prod : conteneur avec
postgresql-client-16 ; sur le poste de dev, ils vivent dans x-med-db-1).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Les 7 tables métier — la frontière figée du chantier bases séparées.
BACKOFFICE_TABLES = (
    "doctors",
    "doctor_profiles",
    "saved_searches",
    "search_runs",
    "digest_runs",
    "usage_events",
    "article_fr",
)
VERSION_TABLE = "alembic_version_app"
MANIFEST_NAME = "latest.json"
LOCK_NAME = ".backup.lock"


class BackupError(RuntimeError):
    """Échec de sauvegarde — message destiné à l'opérateur (ou au cron)."""


def _default_database_url() -> str:
    from app.config import settings

    return settings.database_url


def _libpq_url(url: str) -> str:
    """URL SQLAlchemy → URL libpq (pg_dump ne connaît pas `+psycopg`)."""
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _sqlalchemy_url(url: str) -> str:
    """URL libpq → URL SQLAlchemy pilotée par psycopg 3 (le driver du projet)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _fsync(path: Path) -> None:
    """fsync d'un fichier ou d'un répertoire (rend les renames durables)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _probe_database(
    database_url: str, allow_unversioned: bool
) -> tuple[tuple[str, ...], str | None]:
    """Tables à dumper + révision Alembic de la base (None si non versionnée).

    La base monolithique actuelle n'a pas `alembic_version_app` : un `-t`
    inconditionnel ferait échouer pg_dump, et un dump non versionné doit être
    demandé explicitement (`--allow-unversioned`).
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    engine = create_engine(_sqlalchemy_url(database_url))
    try:
        with engine.connect() as conn:
            has_version = conn.execute(
                text("SELECT to_regclass(:name)"),
                {"name": f"public.{VERSION_TABLE}"},
            ).scalar()
            revision = None
            if has_version:
                revision = conn.execute(
                    text(f"SELECT version_num FROM public.{VERSION_TABLE}")
                ).scalar()
    except SQLAlchemyError as exc:
        cause = str(getattr(exc, "orig", None) or exc).strip().splitlines()[-1]
        raise BackupError(f"base injoignable ({cause})") from exc
    finally:
        engine.dispose()

    if not has_version:
        if not allow_unversioned:
            raise BackupError(
                f"la base n'a pas de table {VERSION_TABLE} : dump non versionné. "
                "Si c'est voulu (base monolithique actuelle), relancer avec "
                "--allow-unversioned."
            )
        return BACKOFFICE_TABLES, None
    return (*BACKOFFICE_TABLES, VERSION_TABLE), revision


def _run_pg_dump(database_url: str, tables: tuple[str, ...], tmp_path: Path) -> None:
    cmd = ["pg_dump", "--format=custom", f"--dbname={_libpq_url(database_url)}"]
    for table in tables:
        cmd += ["--table", f"public.{table}"]
    with tmp_path.open("wb") as out:
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise BackupError(f"pg_dump a échoué (code {proc.returncode}) : {stderr}")


def _verify_dump(tmp_path: Path, tables: tuple[str, ...]) -> None:
    """`pg_restore --list` doit lire le dump ET citer chaque table demandée."""
    with tmp_path.open("rb") as dump:
        proc = subprocess.run(
            ["pg_restore", "--list"],
            stdin=dump,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise BackupError(f"dump illisible par pg_restore --list : {stderr}")
    listing = proc.stdout.decode(errors="replace")
    missing = [t for t in tables if f" {t} " not in listing]
    if missing:
        raise BackupError(f"tables absentes du dump : {', '.join(missing)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish(tmp_path: Path, final_path: Path) -> str:
    """sha256 à côté, fsync, puis rename atomique `.tmp` → `.dump`."""
    sha = _sha256(tmp_path)
    _fsync(tmp_path)
    sha_path = final_path.with_name(final_path.name + ".sha256")
    sha_path.write_text(f"{sha}  {final_path.name}\n")
    _fsync(sha_path)
    tmp_path.rename(final_path)
    _fsync(final_path.parent)
    return sha


def _write_manifest(
    out_dir: Path, final_path: Path, sha: str, revision: str | None
) -> None:
    """`latest.json`, mis à jour en dernier par tmp + rename atomique."""
    manifest = {
        "file": final_path.name,
        "sha256": sha,
        "alembic_revision": revision,
    }
    staging = out_dir / f"{MANIFEST_NAME}.tmp"
    try:
        staging.write_text(json.dumps(manifest, indent=2) + "\n")
        _fsync(staging)
        staging.replace(out_dir / MANIFEST_NAME)
    finally:
        staging.unlink(missing_ok=True)
    _fsync(out_dir)


def _apply_retention(out_dir: Path, keep: int) -> list[Path]:
    """Supprime les générations au-delà de `keep`.

    Le dump désigné par `latest.json` (la source de vérité du seed) n'est
    jamais supprimé, quel que soit son âge.
    """
    manifest_path = out_dir / MANIFEST_NAME
    protected = None
    if manifest_path.exists():
        protected = json.loads(manifest_path.read_text()).get("file")

    dumps = sorted(out_dir.glob("backoffice_*.dump"), reverse=True)
    removed: list[Path] = []
    for old in dumps[keep:]:
        if old.name == protected:
            continue
        old.unlink()
        old.with_name(old.name + ".sha256").unlink(missing_ok=True)
        removed.append(old)
    return removed


def _locked_backup(
    out_dir: Path, keep: int, database_url: str, allow_unversioned: bool
) -> Path:
    tables, revision = _probe_database(database_url, allow_unversioned)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_%f")
    final_path = out_dir / f"backoffice_{stamp}.dump"
    tmp_path = out_dir / f"backoffice_{stamp}.dump.tmp"

    try:
        _run_pg_dump(database_url, tables, tmp_path)
        _verify_dump(tmp_path, tables)
        sha = _publish(tmp_path, final_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    _write_manifest(out_dir, final_path, sha, revision)
    removed = _apply_retention(out_dir, keep)

    print(f"OK : {final_path} ({final_path.stat().st_size} octets, "
          f"{len(tables)} tables, révision {revision or 'aucune'}, "
          f"{len(removed)} ancienne(s) génération(s) purgée(s))")
    return final_path


def run_backup(
    out_dir: Path, keep: int, database_url: str, allow_unversioned: bool = False
) -> Path:
    """Backup complet sous verrou exclusif (échec immédiat si déjà pris)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / LOCK_NAME
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError(
                f"un autre backup est déjà en cours (verrou {lock_path})"
            ) from exc
        return _locked_backup(out_dir, keep, database_url, allow_unversioned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / "backups" / "xmed",
        help="dossier des dumps (défaut : ~/backups/xmed)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="générations conservées (défaut : 14)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="URL de la base (défaut : settings.database_url)",
    )
    parser.add_argument(
        "--allow-unversioned",
        action="store_true",
        help=f"accepter une base sans {VERSION_TABLE} (base monolithique actuelle)",
    )
    args = parser.parse_args(argv)
    if args.keep < 1:
        parser.error("--keep doit être >= 1")

    database_url = args.database_url or _default_database_url()
    try:
        run_backup(args.out_dir, args.keep, database_url, args.allow_unversioned)
    except BackupError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
