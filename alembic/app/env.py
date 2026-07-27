"""Environnement Alembic de la base APP (backoffice) — historique dédié.

Distinct de l'historique monolithique (`alembic/env.py`) sur deux points :

- **table de version `alembic_version_app`** : pendant la transition, les deux
  historiques peuvent viser la même base physique ; ils ne doivent JAMAIS
  partager la table de version, sinon chacun croirait avoir joué les révisions
  de l'autre.
- **URL** : priorité à `config.attributes["sqlalchemy_url"]` (appelants
  programmatiques : tests → base jetable), puis à `sqlalchemy.url` (CLI/ini),
  sinon `settings.database_url` (.env).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Table de version dédiée — ne JAMAIS retomber sur `alembic_version` (elle
# appartient à l'historique monolithique). Schéma épinglé sur `public` : une
# URL portant des options de search_path ne doit pas déplacer la table.
VERSION_TABLE = "alembic_version_app"
VERSION_TABLE_SCHEMA = "public"


def _resolve_url() -> str:
    """URL de la base app, par priorité décroissante.

    Les appelants programmatiques (tests) passent par
    `config.attributes["sqlalchemy_url"]` : les attributes échappent à
    l'interpolation ConfigParser, aucun échappement à leur charge.
    """
    url = config.attributes.get("sqlalchemy_url")
    if not url:
        url = config.get_main_option("sqlalchemy.url")
    if not url:
        from app.config import settings

        url = settings.database_url
    return url


# Point UNIQUE d'échappement ConfigParser : `set_main_option` interpole les `%`
# (un mot de passe percent-encodé casserait sans le doublage). Les lectures
# ultérieures (`get_main_option`, `get_section`) restituent la valeur exacte.
config.set_main_option("sqlalchemy.url", _resolve_url().replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate volontairement INDISPONIBLE : la Base déclarative n'est pas
# encore scindée — `Base.metadata` porte aussi les tables corpus (articles,
# article_search, …) et un autogenerate les créerait dans la base app. Les
# révisions de cet historique s'écrivent à la main tant que la scission n'est
# pas faite.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
