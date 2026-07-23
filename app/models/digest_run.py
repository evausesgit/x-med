"""Générations de digest : une ligne par run, exécuté en arrière-plan.

Le digest « officiel » d'une journée est le dernier run `complete` de cette
`digest_date` : une régénération le remplace en le supplantant, sans effacer
les tentatives précédentes (error/stopped restent pour le diagnostic).

Cycle de vie d'un run : running → translating (payload disponible, traductions
FR en cours) → complete ; ou error / stopped. Un index unique partiel en base
garantit au plus UN run actif (running/translating) par médecin.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DigestRun(Base):
    __tablename__ = "digest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )
    # Journée du digest (fuseau Europe/Paris — le serveur est en UTC).
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    # Jalons de progression (mêmes événements que le SSE de la recherche v2),
    # appendus par UPDATE atomique `logs = logs || …` — jamais mutés côté ORM.
    logs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Réponse complète (forme DeepSearchResponse), posée dès la fin de la
    # recherche (status=translating) puis enrichie des traductions FR.
    payload: Mapped[dict | None] = mapped_column(JSONB)
    n_results: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()
