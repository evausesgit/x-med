"""Recherches lancées en arrière-plan : une ligne par run, pollée par le front.

Même modèle que `DigestRun` (cycle de vie running → translating → complete /
error / stopped, heartbeat `updated_at`, index unique partiel « un run actif
par médecin ») — mais pour la recherche libre de la page d'accueil : la query
est la question saisie par l'utilisateur, et chaque run `complete` devient une
entrée de son historique de recherche.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )
    # La question clinique telle que tapée (c'est la clé de l'historique).
    query: Mapped[str] = mapped_column(Text, nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    # Réglages de la recherche (k_pubmed, rrf, judge_batch, local_floor…) tels
    # que reçus du front — pour rejouer/afficher la recherche à l'identique.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    # Jalons de progression, appendus par UPDATE atomique `logs = logs || …`.
    logs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Réponse complète (forme DeepSearchResponse), posée dès la fin de la
    # recherche (status=translating) puis enrichie des traductions FR.
    payload: Mapped[dict | None] = mapped_column(JSONB)
    n_results: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Heartbeat : touché à chaque jalon — base de la détection des runs zombis.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()
