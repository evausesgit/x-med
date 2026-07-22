"""Journal d'usage : quel compte (login Google) fait quelle recherche, quand.

Une ligne par action utilisateur significative (recherche, lot « analyser plus »,
comparaison…). L'email vient du header `X-User-Email`, posé par le proxy Next
après vérification cryptographique de l'ID token Firebase — le navigateur ne
peut pas le forger sur le chemin public. NULL = appel direct à l'API (dev, cron).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(Text)
    # Nom d'action stable, ex. « search.deep », « search.mesh », « analyze.compare ».
    action: Mapped[str] = mapped_column(Text, nullable=False)
    # Texte de la recherche tel que saisi (quand l'action en a un).
    query: Mapped[str | None] = mapped_column(Text)
    # Paramètres annexes (dates, limites, pmids…) pour rejouer/comprendre l'action.
    params: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
