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
        # Les mêmes mots-clés, mais GROUPÉS PAR CONCEPT : un groupe = les synonymes
        # d'une même idée. C'est la structure `(A1 OR A2) AND (B1 OR B2)` que codex
        # produit déjà pour PubMed, rendue explicite pour que le pré-filtre local
        # puisse la rejouer en ET au lieu d'aplatir tout en un seul OU (cf.
        # `_local_tsquery` dans app/api/search.py : le OU à plat coûte le mot le
        # plus banal de la liste — 92,8 s contre 21 ms mesurés).
        "concepts_en": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        },
    },
    "required": ["pubmed_query", "mesh_terms", "keywords_en", "concepts_en"],
}

_PROMPT = (
    "Tu es expert en recherche bibliographique biomédicale (PubMed). "
    "Transforme la question clinique française suivante en UNE requête PubMed "
    "efficace et ciblée : traduis les concepts en anglais ; ajoute les synonymes "
    "utiles (noms de molécules, codes de développement, variantes) ; utilise les "
    "tags [MeSH] et [tiab] et les opérateurs AND/OR ; reste précis sans "
    "sur-élargir. Question : {q}. "
    "`concepts_en` doit refléter la STRUCTURE de ta requête : un tableau par "
    "concept relié par AND, contenant les synonymes anglais de ce concept "
    "(termes simples, sans tag [MeSH]/[tiab] ni opérateur ; une expression de "
    "plusieurs mots est autorisée). Classe les concepts du plus spécifique au "
    "plus général. Vise 2 à 4 concepts : un seul concept ne filtre rien, et un "
    "concept banal (pain, treatment, surgery) isolé en ramène des centaines de "
    "milliers. `keywords_en` reste la liste à plat de tous ces synonymes. "
    "Réponds uniquement via le schéma JSON imposé."
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


def normalize_concepts(concepts) -> list[list[str]]:
    """Nettoie `concepts_en` : groupes et termes vides retirés, doublons écartés.

    Le pré-filtre local en fait un ET de OU : un groupe vide ou un terme blanc
    produirait une tsquery invalide, et un groupe dupliqué coûterait un ET inutile.
    Tolère aussi une chaîne à la place d'un groupe (codex peut aplatir un concept
    à un seul synonyme).
    """
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in concepts or []:
        items = [group] if isinstance(group, str) else group
        if not isinstance(items, (list, tuple)):
            continue
        terms = list(
            dict.fromkeys(t.strip() for t in items if isinstance(t, str) and t.strip())
        )
        key = tuple(sorted(t.lower() for t in terms))
        if terms and key not in seen:
            seen.add(key)
            out.append(terms)
    return out


def build_pubmed_query(question: str, timeout: int = 180) -> tuple[dict, CodexUsage]:
    """Retourne ({pubmed_query, mesh_terms, keywords_en, concepts_en}, usage).

    Lève QueryBuildError si codex est absent, non authentifié, trop lent, ou muet.
    """
    try:
        data, usage = run_codex(_PROMPT.format(q=question), _SCHEMA, timeout)
    except CodexCliError as e:
        raise QueryBuildError(str(e)) from e
    if not data.get("pubmed_query"):
        raise QueryBuildError("pubmed_query vide")
    data.setdefault("mesh_terms", [])
    data.setdefault("keywords_en", [])
    data["concepts_en"] = normalize_concepts(data.get("concepts_en"))
    return data, usage
