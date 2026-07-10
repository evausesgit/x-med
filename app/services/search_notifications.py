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

import httpx

from app.config import settings

SearchStatus = Literal["ok", "error", "stopped"]

# Limite dure de l'API Telegram sendMessage (4096 caractères), avec une marge.
_TELEGRAM_MAX_LEN = 4000


def _send_via_telegram_api(message: str) -> bool:
    """Envoi direct via l'API Telegram Bot (pas de CLI hermes requis)."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message[:_TELEGRAM_MAX_LEN],
                "disable_web_page_preview": True,
            },
            timeout=settings.search_notify_timeout,
        )
        return response.is_success
    except Exception:
        return False


def _send_via_hermes(message: str) -> bool:
    """Envoi via le CLI hermes (poste de dev, où le gateway tourne)."""
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
        return True
    except Exception:
        return False


def deliver_notification(message: str) -> bool:
    """Achemine un message vers Telegram : API Bot si configurée, sinon hermes."""
    if _send_via_telegram_api(message):
        return True
    return _send_via_hermes(message)


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
    status_label = {
        "ok": "✅ terminée",
        "error": "❌ en erreur",
        "stopped": "⏹️ arrêtée par l'utilisateur",
    }[status]
    lines = [
        f"🔎 X-Med — recherche API {status_label}",
        f"Heure: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"Requête: {_short(query, limit=500)}",
        f"Durée totale: {_fmt_duration(duration_s)}",
    ]

    if metrics:
        method = metrics.get("method")
        if method:
            lines.append(f"Méthode: {method}")

        def add(label: str, *keys: str) -> None:
            # Premier key présent (non None) gagne — permet de partager le rendu
            # entre v1 (`estimated_codex_tokens`) et v2 (`codex_tokens`).
            for key in keys:
                value = metrics.get(key)
                if value is not None:
                    lines.append(f"{label}: {_fmt_int(value)}")
                    return

        add("Résultats PubMed (total)", "pubmed_total_hits")
        add("PMIDs récupérés / fusionnés", "pubmed_pmids", "merged_candidates")
        add("Abstracts locaux analysés", "local_abstracts")
        add("Abstracts jugés par Codex", "judged")
        add("Lots Codex", "codex_batches")
        add("Tokens Codex", "codex_tokens", "estimated_codex_tokens")
        add("Articles retenus", "relevant_total")

        if metrics.get("codex_limit"):
            lines.append("⚠️ Limite d'usage GPT-5.4 atteinte (résultats dégradés)")
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
        # Notification best-effort: ne jamais casser l'API de recherche.
        deliver_notification(message)

    Thread(target=_send, daemon=True).start()
