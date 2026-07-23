"""Construction d'une requête PubMed à partir d'une question clinique FR.

Plutôt qu'une clé API, on shelle le CLI `codex` (`codex exec`) avec
`--output-schema` pour obtenir une sortie JSON structurée. C'est l'étape clé du
mode « PubMed d'abord » : sans elle, envoyer la question française brute à PubMed
(lexical/MeSH) reproduit les travers du moteur lexical (mots banals qui dominent).

Si codex est absent, non authentifié, ou trop lent, on lève QueryBuildError et
l'appelant retombe sur la question brute.
"""

from __future__ import annotations

from app.services.codex_cli import CodexCliError, CodexUsage, run_codex

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pubmed_query": {"type": "string"},
        "mesh_terms": {"type": "array", "items": {"type": "string"}},
        "keywords_en": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["pubmed_query", "mesh_terms", "keywords_en"],
}

_PROMPT = (
    "Tu es expert en recherche bibliographique biomédicale (PubMed). "
    "Transforme la question clinique française suivante en UNE requête PubMed "
    "efficace et ciblée : traduis les concepts en anglais ; ajoute les synonymes "
    "utiles (noms de molécules, codes de développement, variantes) ; utilise les "
    "tags [MeSH] et [tiab] et les opérateurs AND/OR ; reste précis sans "
    "sur-élargir. Question : {q}. Réponds uniquement via le schéma JSON imposé."
)


class QueryBuildError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def is_usage_limit(text: str | None) -> bool:
    """Vrai si le message d'erreur codex indique un dépassement de quota GPT-5.6.

    Partagé par les 3 appels codex (requête, jugement, traduction) pour afficher
    un bandeau explicite à l'utilisateur plutôt qu'un « mode dégradé » silencieux.
    """
    t = (text or "").lower()
    return (
        "usage limit" in t
        or "hit your usage limit" in t
        or "purchase more credits" in t
        or "rate limit" in t
    )


def build_pubmed_query(question: str, timeout: int = 180) -> tuple[dict, CodexUsage]:
    """Retourne ({pubmed_query, mesh_terms, keywords_en}, usage). Lève QueryBuildError."""
    try:
        data, usage = run_codex(_PROMPT.format(q=question), _SCHEMA, timeout)
    except CodexCliError as e:
        raise QueryBuildError(str(e)) from e
    if not data.get("pubmed_query"):
        raise QueryBuildError("pubmed_query vide")
    data.setdefault("mesh_terms", [])
    data.setdefault("keywords_en", [])
    return data, usage
