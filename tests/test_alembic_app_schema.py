"""L'historique Alembic app crée EXACTEMENT le schéma backoffice — rien d'autre.

Test d'intégration sur base JETABLE : on crée `xmed_test_alembic_app` sur le
serveur de dev, on y joue `alembic -c alembic_app.ini upgrade head`, et on
vérifie que le schéma obtenu est la frontière figée du chantier bases séparées
(PLAN_EXECUTION_COMPOSE.md § étape 3) : les 7 tables métier + la table de
version `alembic_version_app`, et rien d'autre. C'est l'assertion d'exactitude
qui prouve qu'aucune table corpus/vector ne fuit dans la base app.

**Nécessite Postgres** — le module entier est ignoré (`skip`) si le serveur
n'est pas joignable, même mécanique que tests/test_deep_search_smoke.py.
La base `xmed` elle-même n'est JAMAIS touchée : tout se passe dans la base de
test, créée puis supprimée ici.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent

# Serveur Postgres de dev — on s'y connecte sur la base d'administration
# `postgres` (autocommit) uniquement pour créer/supprimer la base jetable.
# Suffixe pid : deux suites peuvent tourner en parallèle sans se marcher dessus.
ADMIN_URL = "postgresql+psycopg://xmed:xmed@localhost:5432/postgres"
TEST_DB = f"xmed_test_alembic_app_{os.getpid()}"
TEST_URL = f"postgresql+psycopg://xmed:xmed@localhost:5432/{TEST_DB}"

# La frontière figée : les 7 tables métier.
BACKOFFICE_TABLES = {
    "doctors",
    "doctor_profiles",
    "saved_searches",
    "search_runs",
    "digest_runs",
    "usage_events",
    "article_fr",
}
VERSION_TABLE = "alembic_version_app"

try:
    _admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with _admin.connect() as _c:
        _c.execute(text("SELECT 1"))
    _admin.dispose()
    _DB_OK = True
except Exception:  # pragma: no cover - dépend de l'environnement
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="Postgres indisponible")


def _alembic_config(url: str = TEST_URL, **kwargs):
    """Config alembic_app.ini pointée sur la base jetable — jamais sur xmed.

    L'URL passe par `config.attributes` (pas `set_main_option`) : les
    attributes échappent à l'interpolation ConfigParser, un mot de passe
    percent-encodé ne peut pas casser (voir alembic/app/env.py)."""
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic_app.ini"), **kwargs)
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


@pytest.fixture(scope="module")
def upgraded():
    """Base jetable fraîche + `upgrade head` de l'historique app, détruite après."""
    from alembic import command

    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    try:
        command.upgrade(_alembic_config(), "head")
        engine = create_engine(TEST_URL)
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        admin.dispose()


def test_upgrade_creates_exactly_the_backoffice_schema(upgraded):
    """Rien de plus, rien de moins : toute table corpus qui fuirait ici casse."""
    tables = set(inspect(upgraded).get_table_names())
    assert tables == BACKOFFICE_TABLES | {VERSION_TABLE}


def test_version_table_is_the_dedicated_one(upgraded):
    """`alembic_version_app`, stampée sur la baseline — et surtout PAS
    `alembic_version`, qui appartient à l'historique monolithique."""
    with upgraded.connect() as conn:
        version = conn.execute(
            text(f"SELECT version_num FROM {VERSION_TABLE}")
        ).scalar_one()
    assert version == "app0001"


def test_active_run_unique_partial_indexes(upgraded):
    """Les index « un seul run actif par médecin » : uniques ET partiels,
    conformes au DDL de prod."""
    with upgraded.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND indexname IN ('uq_search_runs_active', 'uq_digest_runs_active')"
            )
        ).all()
    defs = {name: indexdef for name, indexdef in rows}
    assert set(defs) == {"uq_search_runs_active", "uq_digest_runs_active"}
    for indexdef in defs.values():
        assert "UNIQUE" in indexdef
        assert "(doctor_id)" in indexdef
        assert "WHERE" in indexdef
        assert "running" in indexdef and "translating" in indexdef


def test_doctor_id_foreign_keys(upgraded):
    """FK vers doctors(id), avec la bonne règle de suppression par table :
    CASCADE pour profil et runs, SET NULL pour les recherches sauvegardées
    (la sauvegarde survit à la suppression du compte)."""
    expected_ondelete = {
        "doctor_profiles": "CASCADE",
        "search_runs": "CASCADE",
        "digest_runs": "CASCADE",
        "saved_searches": "SET NULL",
    }
    inspector = inspect(upgraded)
    for table, ondelete in expected_ondelete.items():
        fks = inspector.get_foreign_keys(table)
        assert len(fks) == 1, f"{table} : une seule FK attendue"
        fk = fks[0]
        assert fk["constrained_columns"] == ["doctor_id"]
        assert fk["referred_table"] == "doctors"
        assert fk["options"].get("ondelete") == ondelete


def test_downgrade_base_removes_every_business_table(upgraded):
    """`downgrade base` → plus aucune table métier (seule la table de version,
    vidée, peut subsister). Dernier test du module : il démonte le schéma."""
    from alembic import command

    command.downgrade(_alembic_config(), "base")
    tables = set(inspect(upgraded).get_table_names())
    assert not (tables & BACKOFFICE_TABLES)
    assert tables <= {VERSION_TABLE}


def test_offline_mode_emits_sql_without_touching_any_database():
    """`upgrade head --sql` (mode offline) : le SQL complet est émis sans
    ouvrir la moindre connexion — l'URL pointe sur un hôte inexistant pour le
    prouver. La sortie doit contenir les CREATE TABLE des 7 tables et le stamp
    de la baseline dans `alembic_version_app`."""
    import io

    from alembic import command

    buf = io.StringIO()
    cfg = _alembic_config(
        url="postgresql+psycopg://nul:nul@hote-inexistant:5432/nulle",
        output_buffer=buf,
    )
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()

    for table in BACKOFFICE_TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "alembic_version_app" in sql
    assert "app0001" in sql
    assert "alembic_version " not in sql, (
        "le SQL offline ne doit jamais citer la table de version monolithique"
    )
