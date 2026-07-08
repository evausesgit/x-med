"""Modèles ORM : articles PubMed + tables de support.

Les tables d'embeddings (`emb_*`, une par modèle) et les index spéciaux
(GIN, HNSW, tsvector généré) sont créés dans la migration Alembic écrite à la
main — pgvector et les colonnes générées ne sont pas gérés par l'autogenerate.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Computed, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Article(Base):
    __tablename__ = "articles"

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list | None] = mapped_column(JSONB)
    journal: Mapped[str | None] = mapped_column(Text)
    issn: Mapped[str | None] = mapped_column(Text)
    pub_date: Mapped[date | None] = mapped_column()
    pub_year: Mapped[int | None] = mapped_column(Integer)
    mesh_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    doi: Mapped[str | None] = mapped_column(Text)
    pmc_id: Mapped[str | None] = mapped_column(Text)
    publication_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    evidence_level: Mapped[int | None] = mapped_column(Integer)
    # Colonne générée : recherche plein-texte (titre + abstract)
    fts: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))",
            persisted=True,
        ),
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleSearch(Base):
    """Miroir étroit et récent de `articles` (pmid, pub_year, fts) pour le
    pré-filtre plein-texte du pipeline « PubMed d'abord ».

    Motivation : sur les 25 M de lignes / 63 Go de `articles`, le tri `ts_rank`
    doit relire le `tsvector` de dizaines de milliers de candidats depuis le heap
    → jusqu'à ~150 s **à froid** (les pages récentes se font évincer du cache, la
    table ne tient pas en RAM). Cette table ne garde qu'une **fenêtre glissante**
    des dernières années (~3,4 M lignes / ~7 Go), assez petite pour rester chaude
    en permanence → même requête en ~0,4 s, 100 % servie depuis la RAM, avec un
    classement `ts_rank` **strictement identique**.

    Maintenue automatiquement (voir migration 0006_article_search) :
    - **entrée** : trigger `trg_article_search_sync` sur `articles` (upsert des
      articles dont `pub_year >= article_search_min_year()`) ;
    - **sortie** : `article_search_prune()` supprime la queue quand la fenêtre
      avance (tâche planifiée) — sans quoi la table grossirait indéfiniment.

    Le routage `articles` vs `article_search` est décidé dans `_run_deep_search`
    selon la borne basse de la recherche (`settings.use_narrow_search`).
    """

    __tablename__ = "article_search"

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pub_year: Mapped[int | None] = mapped_column(Integer)
    # Copie (non générée) du `fts` de `articles`, alimentée par le trigger.
    fts: Mapped[str | None] = mapped_column(TSVECTOR)


class MeshDescriptor(Base):
    """Descripteurs MeSH rencontrés à l'ingestion (autocomplétion)."""

    __tablename__ = "mesh_descriptors"

    ui: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class FtpState(Base):
    """Suivi des fichiers .xml.gz déjà ingérés."""

    __tablename__ = "ftp_state"

    filename: Mapped[str] = mapped_column(Text, primary_key=True)
    checksum: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int | None] = mapped_column(Integer)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
