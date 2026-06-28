"""Post LinkedIn X-Med du jour : génère un brouillon bilingue à partir d'une vraie
recherche X-Med et l'envoie sur Telegram (Hermes) pour validation.

Conçu pour tourner une fois par jour (cron local : l'API :8800, codex et Hermes
sont locaux à cette machine). Rotation déterministe sujet + format selon la date.

Usage :
    python -m scripts.linkedin_daily              # sujet/format du jour → Telegram
    python -m scripts.linkedin_daily --dry-run    # affiche sans envoyer
    python -m scripts.linkedin_daily --topic ozempic-depression --format myth
    python -m scripts.linkedin_daily --index 5    # force la position dans la rotation
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.services.linkedin_post import (
    FORMATS,
    LinkedInPostError,
    generate_post,
    render_draft,
    send_to_hermes,
)

_TOPICS_PATH = Path(__file__).parent / "linkedin" / "topics.json"


def load_topics() -> list[dict]:
    return json.loads(_TOPICS_PATH.read_text())["topics"]


def pick(topics: list[dict], *, topic_id: str | None, index: int | None):
    """Retourne (topic, format) selon l'override ou la rotation du jour."""
    if topic_id:
        match = next((t for t in topics if t["id"] == topic_id), None)
        if match is None:
            sys.exit(f"Sujet inconnu : {topic_id}")
        i = topics.index(match)
    else:
        i = index if index is not None else date.today().toordinal()
    topic = topics[i % len(topics)]
    fmt = FORMATS[i % len(FORMATS)]
    return topic, fmt


def main() -> int:
    ap = argparse.ArgumentParser(description="Brouillon LinkedIn X-Med du jour.")
    ap.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    ap.add_argument("--topic", help="forcer un id de sujet (cf. topics.json)")
    ap.add_argument("--format", choices=FORMATS, help="forcer un format")
    ap.add_argument("--index", type=int, help="position dans la rotation")
    ap.add_argument("--base-url", help="URL de l'API X-Med (défaut: locale)")
    args = ap.parse_args()

    topics = load_topics()
    topic, fmt = pick(topics, topic_id=args.topic, index=args.index)
    if args.format:
        fmt = args.format

    print(f"Sujet : {topic['id']} · format : {fmt}", file=sys.stderr)
    try:
        post = generate_post(topic=topic, fmt=fmt, base_url=args.base_url)
    except LinkedInPostError as e:
        print(f"Échec : {e}", file=sys.stderr)
        return 1

    draft = render_draft(post)
    if args.dry_run:
        print(draft)
        return 0

    if send_to_hermes(draft):
        print("Brouillon envoyé sur Telegram (Hermes).", file=sys.stderr)
        return 0
    print("Envoi Hermes échoué.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
