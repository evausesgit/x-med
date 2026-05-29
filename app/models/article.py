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
