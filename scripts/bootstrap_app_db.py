"""Bootstrap de la base APP (backoffice) — service `init` du compose app.

One-shot lancé avant api/web (`depends_on: service_completed_successfully`) :
son code de sortie EST le contrat — 0 = base prête, non-zéro = la stack ne
démarre pas. Contrat acté dans PLAN_EXECUTION_COMPOSE.md (journal 2026-07-27),
durci en revue Codex (rôle runtime, matrice manifeste↔base, advisory lock).

Environnement requis :
- ``DATABASE_URL``          — base app cible, credentials ADMIN (le
  POSTGRES_USER du service db : propriétaire, migrations, drop/recreate) ;
- ``XMED_DEPLOYMENT_MODE``  — ``production`` ou ``preview``, rien d'autre ;
- ``SEED_DIR``              — répertoire (monté :ro) contenant ``latest.json``
  et les dumps produits par scripts/backup_backoffice.py ;
- ``APP_RUNTIME_PASSWORD``  — mot de passe du rôle ``xmed_app_runtime`` que
  l'init crée/réaligne à chaque exécution : c'est LUI que l'API utilise
  (DML sur les 7 tables + séquence usage_events, AUCUN DDL). L'API ne voit
  jamais les credentials admin.

Tout le bootstrap se déroule sous ``pg_advisory_lock`` (session de
maintenance) : deux déploiements qui se chevauchent se sérialisent au lieu de
restaurer/migrer en concurrence.

Deux modes :

- **preview** — base jetable, re-seed à CHAQUE exécution :
  ``DROP DATABASE ... WITH (FORCE)`` + ``CREATE ... TEMPLATE template0``,
  restore, garde-stamp, ``upgrade head``, rôle runtime, marqueur.
- **production** — marqueur présent → ``upgrade head`` + réalignement du rôle
  runtime (jamais de re-restore). Marqueur absent → la base doit être VIERGE
  de tables métier (sinon abort : on ne stampe JAMAIS une base à l'état
  inconnu), puis restore, garde-stamp, ``upgrade head``, rôle, marqueur.

Le marqueur (``xmed_ops.bootstrap_state``) n'est posé qu'APRÈS un
``upgrade head`` réussi — « la base contient des tables » n'est jamais un
critère de complétude, un bootstrap interrompu doit se voir.

Garde-stamp — matrice STRICTE manifeste ↔ base restaurée :

===========================  ======================  ==========================
``alembic_version_app``      manifeste               action
===========================  ======================  ==========================
absente                      ``null``                fingerprint 7 tables puis
                                                     ``stamp app0001``
présente                     révision non-nulle      la valeur EN BASE doit être
                                                     exactement celle du
                                                     manifeste, et connue de ce
                                                     checkout (sinon rebase)
absente                      révision non-nulle      erreur (dump incohérent)
présente                     ``null``                erreur (dump incohérent)
===========================  ======================  ==========================
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.backup_backoffice import (
    BACKOFFICE_TABLES,
    MANIFEST_NAME,
    VERSION_TABLE,
    _libpq_url,
    _sha256,
    _sqlalchemy_url,
)

BASELINE_REVISION = "app0001"
OPS_SCHEMA = "xmed_ops"
STATE_TABLE = "bootstrap_state"
VALID_MODES = ("production", "preview")

# Rôle applicatif : DML seulement, créé/réaligné par l'init à chaque run
# (le restore --no-owner + drop/recreate des previews fait sauter les grants).
# ⚠️ Une future migration qui ajoute une table doit soit l'ajouter à
# BACKOFFICE_TABLES (backup + grants suivent), soit porter son GRANT.
RUNTIME_ROLE = "xmed_app_runtime"

# Clé (constante, dédiée) du verrou consultatif de bootstrap — "xmed" en ASCII.
ADVISORY_LOCK_KEY = 0x786D6564

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BootstrapError(RuntimeError):
    """Échec de bootstrap — message actionnable, la stack ne démarre pas."""


def _log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


# ---------------------------------------------------------------------------
# Environnement
# ---------------------------------------------------------------------------

def _read_env() -> tuple[str, str, Path, str]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise BootstrapError("DATABASE_URL manquante (base app cible, admin).")

    mode = os.environ.get("XMED_DEPLOYMENT_MODE")
    if mode not in VALID_MODES:
        raise BootstrapError(
            f"XMED_DEPLOYMENT_MODE={mode!r} invalide : attendu "
            f"{' ou '.join(repr(m) for m in VALID_MODES)}."
        )

    # FAIL-SAFE preview : le parser Coolify résout les ${VAR} du bloc
    # `environment` avec les valeurs du scope PRODUCTION et les fige dans le
    # compose généré — y compris pour les previews (constaté sur cette
    # instance : XMED_DEPLOYMENT_MODE=production écrit en dur dans
    # docker-compose-pr-N.yaml). On détecte donc le contexte PR par les
    # variables que Coolify pose correctement PAR déploiement, et on force le
    # mode preview : une preview ne doit JAMAIS tourner en mode production
    # (elle marquerait sa base persistante comme bootstrapée définitive).
    pr_markers = (
        "-pr-" in os.environ.get("SERVICE_NAME_INIT", ""),
        "pull/" in os.environ.get("COOLIFY_BRANCH", ""),
    )
    if mode == "production" and any(pr_markers):
        log(
            "contexte PR détecté (SERVICE_NAME_INIT/COOLIFY_BRANCH) alors que "
            "XMED_DEPLOYMENT_MODE=production — mode FORCÉ à preview (fail-safe)"
        )
        mode = "preview"

    seed_dir = os.environ.get("SEED_DIR")
    if not seed_dir:
        raise BootstrapError("SEED_DIR manquante (répertoire du seed, monté :ro).")

    runtime_password = os.environ.get("APP_RUNTIME_PASSWORD")
    if not runtime_password:
        raise BootstrapError(
            f"APP_RUNTIME_PASSWORD manquante (mot de passe du rôle {RUNTIME_ROLE}, "
            "celui que l'API utilise)."
        )

    return _sqlalchemy_url(url), mode, Path(seed_dir), runtime_password


# ---------------------------------------------------------------------------
# Manifeste + dump
# ---------------------------------------------------------------------------

def _load_seed(seed_dir: Path) -> tuple[Path, str | None]:
    """Lit ``latest.json``, vérifie le sha256 du dump désigné.

    Retourne (chemin du dump, révision alembic du dump — None si la source
    était la base monolithique, non versionnée côté app).
    """
    manifest_path = seed_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BootstrapError(
            f"manifeste {manifest_path} introuvable. Le seed est produit par "
            "scripts/backup_backoffice.py ; vérifier le montage de SEED_DIR."
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"manifeste {manifest_path} illisible : {exc}") from exc

    file_name = manifest.get("file")
    expected_sha = manifest.get("sha256")
    if not file_name or not expected_sha:
        raise BootstrapError(
            f"manifeste {manifest_path} incomplet (clés `file`/`sha256` requises)."
        )

    dump_path = seed_dir / file_name
    if not dump_path.is_file():
        raise BootstrapError(
            f"dump {dump_path} absent alors que le manifeste le désigne."
        )
    actual_sha = _sha256(dump_path)
    if actual_sha != expected_sha:
        raise BootstrapError(
            f"checksum invalide pour {dump_path} : attendu {expected_sha}, "
            f"obtenu {actual_sha}. Dump corrompu ou manifeste désynchronisé — "
            "relancer scripts/backup_backoffice.py côté source."
        )

    revision = manifest.get("alembic_revision")
    _log(f"seed vérifié : {dump_path.name} (révision {revision or 'aucune'})")
    return dump_path, revision


# ---------------------------------------------------------------------------
# SQL — inspection et gestion de la base cible
# ---------------------------------------------------------------------------

def _connect(url: str, autocommit: bool = False):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # NullPool : une connexion fermée est VRAIMENT fermée — indispensable en
    # preview, où une connexion en pool sur la base cible bloquerait le DROP.
    engine = create_engine(url, poolclass=NullPool)
    if autocommit:
        return engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    return engine.connect()


def _maintenance_url(url: str) -> str:
    """URL vers la base de maintenance `postgres` du même serveur.

    `render_as_string(hide_password=False)` et pas `str()` : ce dernier
    masque le mot de passe (`***`) — l'URL deviendrait inutilisable.
    """
    from sqlalchemy.engine import make_url

    return (
        make_url(url).set(database="postgres").render_as_string(hide_password=False)
    )


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(conn, qualified: str) -> bool:
    from sqlalchemy import text

    return (
        conn.execute(
            text("SELECT to_regclass(:name)"), {"name": qualified}
        ).scalar()
        is not None
    )


def _present_business_tables(conn) -> list[str]:
    return [
        t
        for t in (*BACKOFFICE_TABLES, VERSION_TABLE)
        if _table_exists(conn, f"public.{t}")
    ]


def _has_marker(conn) -> bool:
    from sqlalchemy import text

    if not _table_exists(conn, f"{OPS_SCHEMA}.{STATE_TABLE}"):
        return False
    return bool(
        conn.execute(
            text(f"SELECT count(*) FROM {OPS_SCHEMA}.{STATE_TABLE}")
        ).scalar()
    )


def _set_marker(conn, mode: str, dump_name: str) -> None:
    """Marqueur de bootstrap complet — posé APRÈS `upgrade head` réussi."""
    from sqlalchemy import text

    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {OPS_SCHEMA}"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {OPS_SCHEMA}.{STATE_TABLE} (
                id           BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
                mode         TEXT NOT NULL,
                seed_file    TEXT NOT NULL,
                completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            INSERT INTO {OPS_SCHEMA}.{STATE_TABLE} (id, mode, seed_file)
            VALUES (TRUE, :mode, :seed_file)
            ON CONFLICT (id) DO UPDATE
            SET mode = EXCLUDED.mode,
                seed_file = EXCLUDED.seed_file,
                completed_at = now()
            """
        ),
        {"mode": mode, "seed_file": dump_name},
    )
    conn.commit()


def _ensure_runtime_role(url: str, password: str) -> None:
    """Crée/réaligne le rôle applicatif — l'identité de l'API.

    DML (SELECT/INSERT/UPDATE/DELETE) sur les 7 tables métier + USAGE sur la
    séquence de usage_events et sur le schéma public. AUCUN DDL, aucun
    attribut de cluster. Rejoué à CHAQUE bootstrap : le drop/recreate des
    previews et le restore --no-owner laissent les objets à l'admin, les
    grants doivent être reposés ; en production, les migrations peuvent créer
    des objets à (re)couvrir.
    """
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    dbname = make_url(url).database
    escaped_password = password.replace("'", "''")
    with _connect(url) as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
            {"role": RUNTIME_ROLE},
        ).scalar()
        if not exists:
            conn.execute(text(f"CREATE ROLE {RUNTIME_ROLE} NOLOGIN"))
        conn.execute(
            text(
                f"ALTER ROLE {RUNTIME_ROLE} LOGIN PASSWORD '{escaped_password}' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
        )
        conn.execute(
            text(
                f"GRANT CONNECT ON DATABASE {_quote_ident(dbname)} TO {RUNTIME_ROLE}"
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}"))
        tables = ", ".join(f"public.{t}" for t in BACKOFFICE_TABLES)
        conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {RUNTIME_ROLE}")
        )
        # BIGSERIAL de usage_events : INSERT → nextval() → USAGE requis.
        conn.execute(
            text(
                f"GRANT USAGE ON SEQUENCE public.usage_events_id_seq TO {RUNTIME_ROLE}"
            )
        )
        conn.commit()
    _log(f"rôle {RUNTIME_ROLE} réaligné (DML sur les 7 tables, aucun DDL)")


def _drop_and_recreate(maintenance_conn, url: str) -> None:
    """Preview : base jetable — DROP + CREATE sur la session de maintenance.

    ``WITH (FORCE)`` (PG13+) termine lui-même les connexions restantes : pas
    de fenêtre entre un pg_terminate_backend séparé et le DROP.
    """
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    dbname, owner = parsed.database, parsed.username
    maintenance_conn.execute(
        text(f"DROP DATABASE IF EXISTS {_quote_ident(dbname)} WITH (FORCE)")
    )
    maintenance_conn.execute(
        text(
            f"CREATE DATABASE {_quote_ident(dbname)} "
            f"OWNER {_quote_ident(owner)} TEMPLATE template0"
        )
    )
    _log(f"base {dbname} recréée depuis template0 (mode preview)")


def _restore(dump_path: Path, url: str) -> None:
    """pg_restore tout-ou-rien (transaction unique, échec au premier accroc)."""
    cmd = [
        "pg_restore",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        f"--dbname={_libpq_url(url)}",
        str(dump_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise BootstrapError(
            f"pg_restore a échoué (code {proc.returncode}) : {stderr}"
        )
    _log(f"restore de {dump_path.name} terminé")


# ---------------------------------------------------------------------------
# Alembic
# ---------------------------------------------------------------------------

def _alembic_config(url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic_app.ini"))
    # Les attributes échappent à l'interpolation ConfigParser : aucun
    # échappement de `%` à notre charge (cf. alembic/app/env.py).
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


def _require_known_revision(cfg: Config, revision: str) -> None:
    try:
        ScriptDirectory.from_config(cfg).get_revision(revision)
    except Exception as exc:
        raise BootstrapError(
            f"révision {revision!r} du manifeste inconnue de cet historique "
            "alembic : la branche est en retard sur main — rebase sur main "
            "requis avant de redéployer."
        ) from exc


def _guard_stamp(cfg: Config, url: str, revision: str | None) -> None:
    """Matrice stricte manifeste ↔ base restaurée (cf. docstring du module).

    Le stamp n'existe QUE pour le cas « dump monolithique vérifié » ; toute
    incohérence entre ce que dit le manifeste et ce que contient la base
    restaurée est une erreur, jamais une réparation silencieuse.
    """
    from sqlalchemy import text

    with _connect(url) as conn:
        has_version = _table_exists(conn, f"public.{VERSION_TABLE}")
        db_revision = None
        if has_version:
            db_revision = conn.execute(
                text(f"SELECT version_num FROM public.{VERSION_TABLE}")
            ).scalar()
        missing = [
            t for t in BACKOFFICE_TABLES if not _table_exists(conn, f"public.{t}")
        ]

    if revision is None and not has_version:
        # Dump de la base monolithique : fingerprint minimal avant de stamper.
        if missing:
            raise BootstrapError(
                "fingerprint du schéma restauré invalide (tables absentes : "
                f"{', '.join(missing)}) — stamp refusé."
            )
        command.stamp(cfg, BASELINE_REVISION)
        _log(f"base stampée {BASELINE_REVISION} (dump non versionné vérifié)")
        return

    if revision is not None and has_version:
        # Dump versionné : il apporte sa table de version, aucun stamp. La
        # valeur EN BASE doit recouper exactement le manifeste, et être
        # connue de ce checkout.
        if db_revision != revision:
            raise BootstrapError(
                f"incohérence manifeste ↔ base restaurée : le manifeste dit "
                f"{revision!r} mais {VERSION_TABLE} contient {db_revision!r}. "
                "Dump et manifeste désynchronisés — relancer "
                "scripts/backup_backoffice.py côté source."
            )
        _require_known_revision(cfg, revision)
        return

    if revision is not None:  # et table absente
        raise BootstrapError(
            f"incohérence manifeste ↔ base restaurée : le manifeste porte la "
            f"révision {revision!r} mais {VERSION_TABLE} est absente du dump "
            "restauré. Dump et manifeste désynchronisés — relancer "
            "scripts/backup_backoffice.py côté source."
        )

    raise BootstrapError(  # revision None et table présente
        f"incohérence manifeste ↔ base restaurée : {VERSION_TABLE} présente "
        "alors que le manifeste dit `alembic_revision: null`. Dump et "
        "manifeste désynchronisés — relancer scripts/backup_backoffice.py "
        "côté source."
    )


def _upgrade_head(cfg: Config) -> None:
    from alembic.util import CommandError
    from sqlalchemy.exc import SQLAlchemyError

    try:
        command.upgrade(cfg, "head")
    except (CommandError, SQLAlchemyError) as exc:
        raise BootstrapError(
            f"alembic upgrade head a échoué : {exc}. Si la révision courante "
            "de la base est inconnue de cette branche, rebase sur main requis."
        ) from exc
    _log("alembic upgrade head : OK")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _seed_and_migrate(
    maintenance_conn, url: str, mode: str, seed_dir: Path, runtime_password: str
) -> None:
    """Tronc commun restore → garde-stamp → upgrade → rôle → marqueur."""
    dump_path, revision = _load_seed(seed_dir)
    if mode == "preview":
        _drop_and_recreate(maintenance_conn, url)
    _restore(dump_path, url)
    cfg = _alembic_config(url)
    _guard_stamp(cfg, url, revision)
    _upgrade_head(cfg)
    _ensure_runtime_role(url, runtime_password)
    with _connect(url) as conn:
        _set_marker(conn, mode, dump_path.name)
    _log(f"bootstrap {mode} complet (marqueur posé)")


def _run_production(
    maintenance_conn, url: str, seed_dir: Path, runtime_password: str
) -> None:
    with _connect(url) as conn:
        bootstrapped = _has_marker(conn)
        present = _present_business_tables(conn)

    if bootstrapped:
        _log("marqueur présent : migrations seules (pas de re-restore)")
        _upgrade_head(_alembic_config(url))
        _ensure_runtime_role(url, runtime_password)
        return

    if present:
        raise BootstrapError(
            "marqueur de bootstrap absent mais la base contient déjà des "
            f"tables métier ({', '.join(present)}) : état inconnu (bootstrap "
            "interrompu ?). Jamais de stamp opportuniste — réparer en "
            "recréant la base à la main puis relancer l'init :\n"
            "  1. terminer les connexions puis "
            "`DROP DATABASE <base>; CREATE DATABASE <base> TEMPLATE template0;`\n"
            "  2. relancer le service init (docker compose up init)."
        )

    _log("mode production, base vierge : premier bootstrap (restore + migrations)")
    _seed_and_migrate(maintenance_conn, url, "production", seed_dir, runtime_password)


def _run_preview(
    maintenance_conn, url: str, seed_dir: Path, runtime_password: str
) -> None:
    _log("mode preview : re-seed complet (base jetable)")
    _seed_and_migrate(maintenance_conn, url, "preview", seed_dir, runtime_password)


def main() -> int:
    from sqlalchemy import text

    try:
        url, mode, seed_dir, runtime_password = _read_env()
        # Session de maintenance : porte le verrou de bootstrap pendant TOUTE
        # l'exécution (deux déploiements qui se chevauchent se sérialisent),
        # et sert au DROP/CREATE des previews (AUTOCOMMIT requis).
        maintenance_conn = _connect(_maintenance_url(url), autocommit=True)
        try:
            _log("acquisition du verrou de bootstrap (pg_advisory_lock)…")
            maintenance_conn.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
            )
            _log("verrou de bootstrap obtenu")
            if mode == "preview":
                _run_preview(maintenance_conn, url, seed_dir, runtime_password)
            else:
                _run_production(maintenance_conn, url, seed_dir, runtime_password)
        finally:
            # Fermer la session libère le verrou consultatif.
            maintenance_conn.close()
    except BootstrapError as exc:
        print(f"[bootstrap] ERREUR : {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
