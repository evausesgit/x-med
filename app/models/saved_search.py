"""Recherches sauvegardées : snapshot d'un résultat de recherche, associé à un
médecin, pour y revenir, le relire et le réutiliser SANS relancer la recherche
(donc sans nouvel appel codex, qui coûte des tokens).

`payload` stocke la réponse complète de la recherche (forme `DeepSearchResponse`)
telle qu'affichée à l'écran. Pour l'instant il n'y a pas de contrôle d'accès :
tout le monde voit toutes les recherches sauvegardées (le `doctor_id` n'est qu'un
classement par profil, pas une restriction).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.doctor import Doctor


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Profil rattaché. ON DELETE SET NULL : supprimer un médecin ne doit pas
    # effacer les recherches sauvegardées (elles restent visibles de tous).
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="SET NULL")
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default="v2")
    params: Mapped[dict | None] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    n_results: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    doctor: Mapped["Doctor | None"] = relationship()
