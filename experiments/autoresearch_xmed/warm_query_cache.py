"""Adaptateur sidecar du cache exact du query-builder.

Ce module ne modifie pas l'application. Un appelant expérimental injecte l'objet
``ExactQueryBuilderCache`` à la place de ``build_pubmed_query``. Un miss exécute le
builder normal et persiste sa sortie ; un hit restitue exactement cette sortie et
rapporte zéro token facturé pour la requête courante.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.codex_cli import CodexUsage
from app.services.query_builder import build_pubmed_query
from experiments.autoresearch_xmed.query_cache import build_cached, cache_key

Builder = Callable[..., tuple[dict, CodexUsage]]


@dataclass(frozen=True)
class CacheEvent:
    question_key: str
    hit: bool
    billed_tokens: int
    origin_tokens: int


class ExactQueryBuilderCache:
    """Callable compatible avec ``build_pubmed_query`` et observable pour l'audit."""

    def __init__(self, cache_dir: Path, builder: Builder | None = None) -> None:
        self.cache_dir = cache_dir
        self.builder = builder or build_pubmed_query
        self._accepts_timeout = "timeout" in inspect.signature(self.builder).parameters
        self.events: list[CacheEvent] = []

    def contains(self, question: str) -> bool:
        """Vérifie un hit sans lire la valeur ni déclencher le builder."""
        return (self.cache_dir / f"{cache_key(question)}.json").is_file()

    def __call__(self, question: str, timeout: int = 180) -> tuple[dict, CodexUsage]:
        def call_builder(value: str) -> tuple[dict, CodexUsage]:
            if self._accepts_timeout:
                return self.builder(value, timeout=timeout)
            return self.builder(value)

        data, origin_usage, hit = build_cached(question, self.cache_dir, call_builder)
        billed_usage = CodexUsage() if hit else origin_usage
        self.events.append(
            CacheEvent(
                question_key=cache_key(question),
                hit=hit,
                billed_tokens=billed_usage.total_tokens,
                origin_tokens=origin_usage.total_tokens,
            )
        )
        return data, billed_usage
