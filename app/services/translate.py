"""Traduction FR d'abstracts par le CLI codex (GPT-5.4), avec cache article_fr.

Étape 4 du plan « PubMed + codex » : on traduit en français les abstracts des
articles retenus, pour les médecins. Les traductions sont mises en cache dans la
table `article_fr` (pmid, title_fr, abstract_fr) → instantanées aux recherches
suivantes ; le cache se construit au fil des recherches.

Même mécanique que `codex_judge` / `query_builder` : `codex exec --output-schema`
pour une sortie JSON structurée, repli `TranslateError` si codex indisponible.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.config import settings

# On borne pour qu'un lot tienne dans un seul appel codex (argv + contexte).
MAX_ABSTRACT_CHARS = 2000

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pmid": {"type": "integer"},
                    "title_fr": {"type": "string"},
                    "abstract_fr": {"type": "string"},
                },
                "required": ["pmid", "title_fr", "abstract_fr"],
            },
        }
    },
    "required": ["translations"],
}

_PROMPT_HEAD = (
    "Tu es traducteur médical. Traduis fidèlement en français le titre et le "
    "résumé de chaque article ci-dessous, en respectant la terminologie médicale "
    "et sans rien ajouter ni omettre. Garde un registre clinique clair. Réponds "
    "UNIQUEMENT via le schéma JSON imposé, un objet par PMID fourni.\n\n"
    "Articles :\n"
)


@dataclass
class Translation:
    title_fr: str
    abstract_fr: str


class TranslateError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def get_cached(session: Session, pmids: list[int]) -> dict[int, Translation]:
    """Traductions déjà en cache (article_fr) pour ces PMID."""
    if not pmids:
        return {}
    rows = session.execute(
        sql_text(
            "SELECT pmid, title_fr, abstract_fr FROM article_fr "
            "WHERE pmid = ANY(:ids) AND abstract_fr IS NOT NULL"
        ),
        {"ids": pmids},
    ).all()
    return {int(p): Translation(title_fr=t or "", abstract_fr=a) for p, t, a in rows}


def _upsert(session: Session, out: dict[int, Translation]) -> None:
    for pmid, tr in out.items():
        session.execute(
            sql_text(
                """
                INSERT INTO article_fr (pmid, title_fr, abstract_fr, updated_at)
                VALUES (:pmid, :t, :a, now())
                ON CONFLICT (pmid) DO UPDATE
                  SET title_fr = EXCLUDED.title_fr,
                      abstract_fr = EXCLUDED.abstract_fr,
                      updated_at = now()
                """
            ),
            {"pmid": pmid, "t": tr.title_fr, "a": tr.abstract_fr},
        )
    session.commit()


def _render(items: list[dict]) -> str:
    blocks = []
    for a in items:
        abstract = (a.get("abstract") or "").strip()
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
        blocks.append(
            f"- PMID {a['pmid']}\n"
            f"  Titre : {a.get('title') or ''}\n"
            f"  Résumé : {abstract}"
        )
    return "\n".join(blocks)


def translate_abstracts(
    items: list[dict], session: Session | None = None, timeout: int = 600
) -> dict[int, Translation]:
    """Traduit (et met en cache si `session`) une liste d'articles {pmid, title,
    abstract}. Retourne {pmid: Translation}. Lève `TranslateError` si codex échoue."""
    items = [a for a in items if (a.get("abstract") or "").strip()]
    if not items:
        return {}

    prompt = _PROMPT_HEAD + _render(items)
    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        out_path = Path(td) / "out.json"
        schema_path.write_text(json.dumps(_SCHEMA))
        cmd = [
            settings.codex_bin, "exec", "--skip-git-repo-check", "--ephemeral",
            "-s", "read-only", "--color", "never",
            "--output-schema", str(schema_path), "-o", str(out_path),
        ]
        if settings.codex_model:
            cmd += ["-m", settings.codex_model]
        cmd.append(prompt)
        try:
            subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout, check=True,
            )
        except FileNotFoundError as e:
            raise TranslateError(f"codex introuvable ({settings.codex_bin})") from e
        except subprocess.TimeoutExpired as e:
            raise TranslateError(f"codex timeout ({timeout}s)") from e
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or b"").decode(errors="replace")[-300:]
            raise TranslateError(f"codex a échoué : {tail}") from e
        try:
            data = json.loads(out_path.read_text())
        except Exception as e:
            raise TranslateError(f"sortie codex illisible : {e}") from e

    out: dict[int, Translation] = {}
    for t in data.get("translations", []):
        try:
            pmid = int(t["pmid"])
        except (KeyError, TypeError, ValueError):
            continue
        abstract_fr = str(t.get("abstract_fr", "")).strip()
        if not abstract_fr:
            continue
        out[pmid] = Translation(
            title_fr=str(t.get("title_fr", "")).strip(), abstract_fr=abstract_fr
        )

    if session is not None and out:
        _upsert(session, out)
    return out
