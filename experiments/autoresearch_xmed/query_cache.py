"""Cache fichier versionné du query-builder, exclusivement pour les expériences.

La clé inclut tous les éléments capables de changer la sortie. Aucune normalisation
sémantique n'est faite : deux formulations différentes ne partagent jamais une entrée.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from app.config import settings
from app.services.codex_cli import CodexUsage
from app.services.query_builder import _PROMPT, _SCHEMA, build_pubmed_query

Builder = Callable[[str], tuple[dict, CodexUsage]]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def cache_key(question: str) -> str:
    return _canonical_hash(
        {
            "question": question,
            "prompt_sha256": hashlib.sha256(_PROMPT.encode()).hexdigest(),
            "schema_sha256": _canonical_hash(_SCHEMA),
            "model": settings.codex_model,
            "reasoning": settings.codex_reasoning,
        }
    )


def _usage_from_json(value: dict) -> CodexUsage:
    fields = {name: int(value.get(name, 0)) for name in asdict(CodexUsage())}
    return CodexUsage(**fields)


def build_cached(
    question: str,
    cache_dir: Path,
    builder: Builder = build_pubmed_query,
) -> tuple[dict, CodexUsage, bool]:
    """Retourne `(sortie, usage_origine, cache_hit)`.

    L'usage d'origine reste dans l'artefact pour l'audit ; un runner de coûts doit
    compter zéro token facturé lorsque `cache_hit` vaut vrai.
    """
    key = cache_key(question)
    path = cache_dir / f"{key}.json"
    if path.exists():
        payload = json.loads(path.read_text())
        if payload.get("key") != key:
            raise ValueError(f"entrée de cache corrompue: {path}")
        return payload["data"], _usage_from_json(payload.get("usage", {})), True

    data, usage = builder(question)
    payload = {"schema_version": 1, "key": key, "data": data, "usage": usage.as_dict()}
    cache_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=cache_dir)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data, usage, False
