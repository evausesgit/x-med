"""Enregistrement best-effort des actions utilisateur (table usage_events).

Session dédiée, commit immédiat : le journal survit à un échec de la recherche
(on veut aussi voir les tentatives), et un problème d'écriture du journal ne
doit jamais faire échouer la requête de l'utilisateur — il est loggé en warning.
"""

from __future__ import annotations

import logging

from fastapi import Request

from app.db import SessionLocal
from app.models.usage_event import UsageEvent

log = logging.getLogger(__name__)


def record_usage(
    request: Request,
    action: str,
    query: str | None = None,
    params: dict | None = None,
) -> None:
    email = request.headers.get("x-user-email")
    try:
        with SessionLocal() as session:
            session.add(
                UsageEvent(email=email, action=action, query=query, params=params)
            )
            session.commit()
    except Exception:
        log.warning("usage_events : échec d'enregistrement de %r", action, exc_info=True)
