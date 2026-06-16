"""Notifications Telegram/Hermes pour les recherches X-Med.

Objectif: prévenir Eva dès qu'une recherche PubMed/Codex est lancée via l'API,
sans bloquer la réponse HTTP si Telegram ou Hermes est indisponible.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import datetime
from threading import Thread
from typing import Any, Literal

from app.config import settings

SearchStatus = Literal["ok", "error"]


def _short(value: str | None, *, limit: int = 700) -> str:
    text = (value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m{rest:04.1f}s"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except Exception:
        return "n/a"


def _build_message(
    *,
    status: SearchStatus,
    query: str,
    duration_s: float | None,
    metrics: dict[str, Any],
    progress_events: Sequence[dict[str, Any]],
    error: str | None = None,
) -> str:
    status_label = "✅ terminée" if status == "ok" else "❌ en erreur"
    lines = [
        f"🔎 X-Med — recherche API {status_label}",
        f"Heure: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"Requête: {_short(query, limit=500)}",
        f"Durée totale: {_fmt_duration(duration_s)}",
    ]

    if metrics:
        lines.extend(
            [
                f"Résultats PubMed: {_fmt_int(metrics.get('pubmed_total_hits'))} total / {_fmt_int(metrics.get('pubmed_pmids'))} récupérés",
                f"Abstracts locaux analysés: {_fmt_int(metrics.get('local_abstracts'))}",
                f"Lots Codex: {_fmt_int(metrics.get('codex_batches'))}",
                f"Tokens estimés envoyés à Codex: {_fmt_int(metrics.get('estimated_codex_tokens'))}",
                f"Articles retenus: {_fmt_int(metrics.get('relevant_total'))}",
            ]
        )
        pubmed_query = metrics.get("pubmed_query")
        if pubmed_query:
            lines.append(f"Requête PubMed construite: {_short(str(pubmed_query), limit=700)}")

    if progress_events:
        lines.append("Déroulé:")
        for event in progress_events[-12:]:
            phase = event.get("phase", "?")
            elapsed = event.get("elapsed_s")
            msg = _short(str(event.get("msg", "")), limit=220)
            lines.append(f"- {phase} · {_fmt_duration(elapsed)} · {msg}")

    if error:
        lines.append(f"Erreur: {_short(error, limit=900)}")

    return "\n".join(lines)


def send_search_notification(
    *,
    status: SearchStatus,
    query: str,
    duration_s: float | None,
    metrics: dict[str, Any] | None = None,
    progress_events: Sequence[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    """Envoie une notification Hermes en arrière-plan, sans lever d'exception."""
    if not settings.search_notify_enabled:
        return

    message = _build_message(
        status=status,
        query=query,
        duration_s=duration_s,
        metrics=metrics or {},
        progress_events=progress_events or (),
        error=error,
    )

    def _send() -> None:
        try:
            subprocess.run(
                [
                    settings.search_notify_hermes_bin,
                    "send",
                    "--to",
                    settings.search_notify_target,
                    "--quiet",
                    "--file",
                    "-",
                ],
                input=message,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=settings.search_notify_timeout,
                check=False,
            )
        except Exception:
            # Notification best-effort: ne jamais casser l'API de recherche.
            return

    Thread(target=_send, daemon=True).start()
