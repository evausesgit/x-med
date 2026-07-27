"""Connexions SQLAlchemy + base déclarative — DEUX moteurs, une frontière.

Le projet sépare deux mondes qui ne se joignent jamais en SQL (aucune FK ni
jointure ne traverse, cf. PLAN_BASES_SEPAREES.md) :

- **app** (`DATABASE_URL`) — les données produit, petites et précieuses :
  doctors, doctor_profiles, saved_searches, search_runs, digest_runs,
  usage_events, article_fr. Lecture/écriture par l'API.
- **corpus** (`CORPUS_DATABASE_URL`) — le miroir PubMed, énorme et
  reconstructible : articles, article_search, mesh_descriptors, ftp_state.
  L'API n'y fait QUE des lectures ; seule l'ingestion y écrit.

Tant que `CORPUS_DATABASE_URL` n'est pas renseignée, les deux moteurs pointent
sur la même base : le code routé tourne tel quel sur l'infra monolithique.
Là où les deux mondes se croisent (recherche corpus + cache de traduction),
on passe DEUX sessions — jamais une session pour l'autre monde.
"""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings
from app.runtime_env import check_api_db_identity, resolve_db_url

# Garde d'identité de déploiement (incident du 2026-07-27) : en contexte
# Coolify, l'API refuse de démarrer si api et db n'appartiennent pas au même
# déploiement (api ↔ db, api-pr-N ↔ db-pr-N), et l'hôte `db` de l'URL app est
# résolu AU RUNTIME via SERVICE_NAME_DB (db-pr-N en preview). En Python et pas
# dans le CMD : `docker compose exec` / Scheduled Tasks passent aussi par ici.
# Hors Coolify (dev local, tests, prod monolithique) : strict no-op.
check_api_db_identity()

# --- Monde app (backoffice) ---
engine = create_engine(
    resolve_db_url(settings.database_url), pool_pre_ping=True, future=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

# --- Monde corpus (miroir PubMed, lecture seule côté API) ---
if settings.corpus_database_url is None:
    # Attendu en dev monolithique ; en prod/preview composée, une variable
    # oubliée ferait chercher les 25 M d'articles dans la petite base app.
    logging.getLogger(__name__).warning(
        "CORPUS_DATABASE_URL absente — corpus routé sur DATABASE_URL (mode monolithique)"
    )
# Le repli passe par la même résolution runtime que l'engine app (l'URL
# corpus explicite, elle, porte son propre hôte — corpus-db — et n'est pas
# concernée par SERVICE_NAME_DB).
corpus_engine = create_engine(
    settings.corpus_database_url or resolve_db_url(settings.database_url),
    pool_pre_ping=True,
    future=True,
)
CorpusSessionLocal = sessionmaker(
    bind=corpus_engine, autoflush=False, expire_on_commit=False, future=True
)


class Base(DeclarativeBase):
    pass


def get_session():
    """Dépendance FastAPI : session APP (backoffice), fermée en fin de requête."""
    with SessionLocal() as session:
        yield session


def get_corpus_session():
    """Dépendance FastAPI : session CORPUS (miroir PubMed), fermée en fin de requête."""
    with CorpusSessionLocal() as session:
        yield session
