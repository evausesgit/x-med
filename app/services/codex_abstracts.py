"""Lecture semantique d'abstracts par Codex, avec decoupage par budget de tokens."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pmid": {"type": "integer"},
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "relevant": {"type": "boolean"},
                    "justification": {"type": "string"},
                },
                "required": ["pmid", "score", "relevant", "justification"],
            },
        }
    },
    "required": ["assessments"],
}

_PROMPT = """Tu es un expert en lecture critique de litterature biomedicale.

Compare semantiquement chaque article a la phrase recherchee du medecin (PRM).
La comparaison porte sur le sens et la pertinence medicale, pas sur la simple
presence des memes mots.

PRM:
{prm}

Utilise exactement cette grille absolue pour que les scores restent comparables
entre plusieurs lots:
- 0.00: sans rapport;
- 0.25: meme theme general, mais question ou contraintes cliniques non respectees;
- 0.50: partiellement pertinent, information indirecte ou incomplete;
- 0.75: pertinent et repond directement a une partie importante de la PRM;
- 1.00: repond directement et precisement a la PRM.

`relevant` doit etre vrai uniquement si score >= {threshold:.2f}. Evalue chaque
PMID fourni, sans en ajouter ni en omettre. La justification doit tenir en une
phrase courte. N'utilise aucune information exterieure aux articles fournis.

ARTICLES:
{articles}
"""


class CodexAbstractError(RuntimeError):
    """Codex est indisponible ou sa sortie ne respecte pas le contrat."""


@dataclass(frozen=True)
class AbstractCandidate:
    pmid: int
    title: str
    abstract: str


@dataclass(frozen=True)
class AbstractAssessment:
    pmid: int
    score: float
    relevant: bool
    justification: str


def estimate_tokens(text: str) -> int:
    """Estimation volontairement prudente pour du texte biomedical anglais."""
    return max(1, (len(text) + 2) // 3)


def candidate_tokens(candidate: AbstractCandidate) -> int:
    return estimate_tokens(candidate.title) + estimate_tokens(candidate.abstract) + 40


def iter_batches(
    candidates: Iterable[AbstractCandidate],
    *,
    token_budget: int | None = None,
    max_articles: int | None = None,
) -> Iterator[list[AbstractCandidate]]:
    """Produit des lots bornes a la fois en tokens estimes et en nombre d'articles."""
    budget = token_budget or settings.codex_abstract_batch_tokens
    article_limit = max_articles or settings.codex_abstract_batch_max_articles
    batch: list[AbstractCandidate] = []
    used = 0

    for candidate in candidates:
        cost = candidate_tokens(candidate)
        if batch and (used + cost > budget or len(batch) >= article_limit):
            yield batch
            batch = []
            used = 0
        batch.append(candidate)
        used += cost

    if batch:
        yield batch


def _articles_payload(batch: list[AbstractCandidate]) -> str:
    return json.dumps(
        [
            {"pmid": item.pmid, "title": item.title, "abstract": item.abstract}
            for item in batch
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def assess_batch(
    prm: str,
    batch: list[AbstractCandidate],
    *,
    threshold: float | None = None,
    timeout: int | None = None,
) -> list[AbstractAssessment]:
    """Demande a GPT-5.4 de juger semantiquement tous les abstracts d'un lot."""
    if not batch:
        return []

    relevance_threshold = (
        settings.codex_relevance_threshold if threshold is None else threshold
    )
    prompt = _PROMPT.format(
        prm=prm,
        threshold=relevance_threshold,
        articles=_articles_payload(batch),
    )

    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        out_path = Path(td) / "out.json"
        schema_path.write_text(json.dumps(_SCHEMA))
        cmd = [
            settings.codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "--color",
            "never",
            "-m",
            settings.codex_model,
            "--output-schema",
            str(schema_path),
            "-o",
            str(out_path),
            "-",
        ]
        try:
            subprocess.run(
                cmd,
                input=prompt,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout or settings.codex_abstract_timeout,
                check=True,
            )
        except FileNotFoundError as exc:
            raise CodexAbstractError(
                f"codex introuvable ({settings.codex_bin})"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexAbstractError("codex timeout pendant l'analyse des abstracts") from exc
        except subprocess.CalledProcessError as exc:
            tail = (exc.stderr or "")[-500:]
            raise CodexAbstractError(f"codex a echoue: {tail}") from exc

        try:
            data = json.loads(out_path.read_text())
        except Exception as exc:
            raise CodexAbstractError(f"sortie codex illisible: {exc}") from exc

    expected = {item.pmid for item in batch}
    assessments: dict[int, AbstractAssessment] = {}
    for item in data.get("assessments", []):
        pmid = int(item["pmid"])
        if pmid not in expected:
            continue
        score = min(1.0, max(0.0, float(item["score"])))
        assessments[pmid] = AbstractAssessment(
            pmid=pmid,
            score=score,
            relevant=score >= relevance_threshold,
            justification=str(item["justification"]).strip(),
        )

    missing = expected - assessments.keys()
    if missing:
        raise CodexAbstractError(
            f"codex n'a pas evalue {len(missing)} PMID du lot"
        )
    return [assessments[item.pmid] for item in batch]
