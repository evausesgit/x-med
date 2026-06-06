"""Explications factuelles des résultats, sans génération LLM.

Les concepts et le type d'étude viennent des métadonnées PubMed. La population
et l'intervention sont des mentions détectées dans le titre ou l'abstract ; elles
restent donc des indices de lecture, pas une interprétation clinique.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchExplanation:
    concepts: list[str]
    population: str | None
    intervention: str | None
    study_type: str | None


_POPULATION_MESH = (
    "Humans",
    "Female",
    "Male",
    "Adult",
    "Aged",
    "Middle Aged",
    "Young Adult",
    "Adolescent",
    "Child",
    "Infant",
    "Newborn",
    "Pregnant Women",
)

_POPULATION_PATTERNS = (
    re.compile(
        r"\b(?:participants?|patients?|subjects?|women|men|adults?|children|"
        r"adolescents?|infants?|newborns?|pregnant women)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:cohort|sample|population)\s+of\b", re.IGNORECASE),
)

_INTERVENTION_PATTERNS = (
    re.compile(
        r"\b(?:randomi[sz]ed|assigned|allocated)\s+(?:participants?|patients?|subjects?)?"
        r".{0,80}\bto\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:received|treated with|underwent|administered|therapy with|"
        r"intervention consisted of|effect(?:s)? of|efficacy of)\b",
        re.IGNORECASE,
    ),
)

_STUDY_TYPE_PRIORITY = (
    "Meta-Analysis",
    "Systematic Review",
    "Randomized Controlled Trial",
    "Controlled Clinical Trial",
    "Clinical Trial, Phase IV",
    "Clinical Trial, Phase III",
    "Clinical Trial, Phase II",
    "Clinical Trial, Phase I",
    "Clinical Trial",
    "Observational Study",
    "Comparative Study",
    "Multicenter Study",
    "Case-Control Studies",
    "Cohort Studies",
    "Case Reports",
    "Review",
)

_GENERIC_MESH = {
    "humans",
    "female",
    "male",
    "adult",
    "aged",
    "middle aged",
    "young adult",
    "adolescent",
    "child",
    "infant",
    "newborn",
    "animals",
}


def _normalized_words(value: str) -> set[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return {word for word in re.findall(r"[a-z0-9]+", ascii_value.lower()) if len(word) >= 3}


def _sentences(text: str | None) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]


def _matching_sentence(text: str | None, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for sentence in _sentences(text):
        if any(pattern.search(sentence) for pattern in patterns):
            return sentence[:220] + ("..." if len(sentence) > 220 else "")
    return None


def _concepts(mesh_terms: list[str] | None, title: str, query: str | None) -> list[str]:
    terms = [term for term in (mesh_terms or []) if term.lower() not in _GENERIC_MESH]
    if not terms:
        return []

    context_words = _normalized_words(f"{query or ''} {title}")

    def relevance(term: str) -> tuple[int, int]:
        overlap = len(_normalized_words(term) & context_words)
        title_match = int(term.lower() in title.lower())
        return title_match, overlap

    return sorted(terms, key=relevance, reverse=True)[:4]


def _population(mesh_terms: list[str] | None, abstract: str | None) -> str | None:
    indexed = [term for term in _POPULATION_MESH if term in (mesh_terms or [])]
    if indexed:
        return ", ".join(indexed[:4])
    return _matching_sentence(abstract, _POPULATION_PATTERNS)


def _study_type(publication_types: list[str] | None) -> str | None:
    available = publication_types or []
    for study_type in _STUDY_TYPE_PRIORITY:
        if study_type in available:
            return study_type
    return available[0] if available else None


def explain_article(
    *,
    title: str,
    abstract: str | None,
    mesh_terms: list[str] | None,
    publication_types: list[str] | None,
    query: str | None = None,
) -> SearchExplanation:
    return SearchExplanation(
        concepts=_concepts(mesh_terms, title, query),
        population=_population(mesh_terms, abstract),
        intervention=_matching_sentence(abstract, _INTERVENTION_PATTERNS),
        study_type=_study_type(publication_types),
    )
