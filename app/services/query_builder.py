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
        "keyword_groups_en": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "maxItems": 5,
        },
    },
    "required": ["pubmed_query", "mesh_terms", "keywords_en", "keyword_groups_en"],
}

_PROMPT = (
    "Tu es expert en recherche bibliographique biomédicale (PubMed). "
    "Transforme la question clinique française suivante en UNE requête PubMed "
    "efficace et ciblée : traduis les concepts en anglais ; ajoute les synonymes "
    "utiles (noms de molécules, codes de développement, variantes) ; utilise les "
    "tags [MeSH] et [tiab] et les opérateurs AND/OR ; reste précis sans "
    "sur-élargir. En plus de la requête PubMed, produis keyword_groups_en : "
    "chaque sous-liste représente UN concept obligatoire et contient uniquement "
    "ses synonymes ou variantes ; OR s'applique dans une sous-liste et AND entre "
    "les sous-listes. Tous les noms de molécules, codes, marques et alternatives "
    "d'un même traitement doivent rester dans UNE seule sous-liste, même si elle "
    "est longue : ne les sépare jamais en plusieurs groupes. Les groupes doivent "
    "être une projection mécanique de pubmed_query : sépare uniquement les blocs "
    "reliés par AND au niveau supérieur et conserve dans le même groupe tout ce "
    "qui est relié par OR dans un bloc. Ne sépare donc pas cognition, neurologie "
    "et neurocognition si pubmed_query les met dans le même bloc OR. Vise au "
    "maximum cinq groupes. N'ajoute pas de mots génériques comme study, patient, "
    "risk, outcome ou treatment, et ne mets jamais des concepts différents dans le "
    "même groupe. keyword_groups_en n'est pas un résumé : recopie tous les termes "
    "anglais utiles déjà présents dans pubmed_query, en retirant seulement les tags "
    "[MeSH] et [tiab], sans oublier les variantes importantes. "
    "keywords_en doit être l'union aplatie des groupes. Exemple : "
    "[['endometriosis'], ['GLP-1', 'semaglutide', 'liraglutide']]. "
    "Question : {q}. Réponds uniquement via le schéma JSON imposé."
)


class QueryBuildError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def _clean_terms(value: object) -> list[str]:
    """Nettoie une liste de termes issue du JSON du query-builder."""
    if not isinstance(value, list):
        return []

    terms: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        term = " ".join(item.split())
        key = term.casefold()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return terms


def normalize_keyword_groups(
    raw_groups: object, fallback_terms: object = None
) -> list[list[str]]:
    """Retourne des groupes propres, avec repli compatible avec l'ancien JSON.

    Les anciens résultats ne contiennent que ``keywords_en``. Ils sont conservés
    comme un seul groupe OR jusqu'à ce qu'une nouvelle réponse LLM fournisse la
    structure AND/OR.
    """
    groups: list[list[str]] = []
    if isinstance(raw_groups, list):
        for raw_group in raw_groups:
            terms = _clean_terms(raw_group)
            if terms:
                groups.append(terms)
    if groups:
        return groups

    terms = _clean_terms(fallback_terms)
    return [terms] if terms else []


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
    """Retourne la requête PubMed et la structure FTS, avec l'usage Codex."""
    try:
        data, usage = run_codex(_PROMPT.format(q=question), _SCHEMA, timeout)
    except CodexCliError as e:
        raise QueryBuildError(str(e)) from e
    if not data.get("pubmed_query"):
        raise QueryBuildError("pubmed_query vide")
    data.setdefault("mesh_terms", [])
    data["keywords_en"] = _clean_terms(data.get("keywords_en"))
    data["keyword_groups_en"] = normalize_keyword_groups(
        data.get("keyword_groups_en"), data["keywords_en"]
    )
    data["keywords_en"] = [
        term for group in data["keyword_groups_en"] for term in group
    ]
    return data, usage
