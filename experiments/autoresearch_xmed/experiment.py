"""Seul fichier mutable pendant les 30 rounds autoresearch X-Med.

La baseline reproduit les paramètres envoyés par l'interface actuelle. Les runners
sidecar importent cette configuration ; ils ne patchent jamais le runtime de prod.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Experiment:
    name: str = "baseline-ui-v1"
    gate: str = "fidelity"
    k_pubmed: int = 20
    max_local: int = 200
    judge_batch: int = 50
    min_score: int = 2
    rrf: bool = False
    local_floor: int = 0
    use_narrow_search: bool = False
    reuse_query_builder: bool = False
    reuse_esearch: bool = False
    parallel_pubmed_fts: bool = False
    parallel_ncbi_hydration: bool = False
    reuse_hydrated_translation_input: bool = False
    bulk_translation_upsert: bool = False
    project_articles: bool = False


EXPERIMENT = Experiment()


def config() -> dict:
    return asdict(EXPERIMENT)
