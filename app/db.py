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

# --- Monde app (backoffice) ---
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

# --- Monde corpus (miroir PubMed, lecture seule côté API) ---
if settings.corpus_database_url is None:
    # Attendu en dev monolithique ; en prod/preview composée, une variable
    # oubliée ferait chercher les 25 M d'articles dans la petite base app.
    logging.getLogger(__name__).warning(
        "CORPUS_DATABASE_URL absente — corpus routé sur DATABASE_URL (mode monolithique)"
    )
corpus_engine = create_engine(
    settings.corpus_database_url or settings.database_url,
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
