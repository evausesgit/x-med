"""Modèles ORM du benchmark multi-modèles d'embedding."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BenchQuery(Base):
    __tablename__ = "bench_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)  # 'nfcorpus' | 'gold_interne'
    text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(Text)  # 'en' | 'fr'


class BenchQrel(Base):
    """Vérité-terrain : pertinence d'un (query, pmid)."""

    __tablename__ = "bench_qrels"

    query_id: Mapped[int] = mapped_column(ForeignKey("bench_queries.id"), primary_key=True)
    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = non pertinent, >=1 = pertinent


class BenchRun(Base):
    __tablename__ = "bench_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BenchResult(Base):
    __tablename__ = "bench_results"

    run_id: Mapped[int] = mapped_column(ForeignKey("bench_runs.id"), primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)  # 'ndcg@10' | 'recall@100' | ...
    value: Mapped[float] = mapped_column(Float, nullable=False)
