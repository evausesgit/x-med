"""Jugement de pertinence d'un lot d'articles par le CLI codex (GPT-5.4).

Cœur de la méthode « PubMed + codex » (cf. PLAN_RECHERCHE_PUBMED_CODEX.md,
étapes 2-3) : plutôt que de classer le corpus par embeddings (pré-tri pgvector
peu cohérent), on fait LIRE à codex les abstracts d'un lot **borné** de candidats
(issus du filtre lexical + MeSH) et on lui demande, par rapport à la phrase du
médecin (`PRM`), un score de pertinence et une justification courte.

Même mécanique que `query_builder.build_pubmed_query` : on shelle `codex exec`
avec `--output-schema` pour une sortie JSON structurée. Si codex est absent, non
authentifié ou trop lent, on lève `JudgeError` et l'appelant retombe sur un
classement sans LLM (filtre lexical + récence).

Grille de score (entier) :
    0 = hors sujet  ·  1 = marginal  ·  2 = pertinent  ·  3 = très pertinent
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.codex_cli import CodexCliError, CodexUsage, run_codex

# On borne le lot pour qu'il tienne dans un seul appel codex (argv + contexte).
MAX_ABSTRACT_CHARS = 1200

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pmid": {"type": "integer"},
                    "score": {"type": "integer"},  # 0..3 (tri stable)
                    "relevance_pct": {"type": "integer"},  # 0..100 (affichage fin)
                    "reason": {"type": "string"},  # « apport » orienté lecteur
                },
                "required": ["pmid", "score", "relevance_pct", "reason"],
            },
        }
    },
    "required": ["judgements"],
}

_PROMPT_HEAD = (
    "Tu es médecin et expert en lecture critique d'articles biomédicaux. "
    "Pour la question clinique d'un médecin, évalue chaque article ci-dessous "
    "d'après son titre et son résumé. Juge le SENS et la pertinence clinique (pas "
    "la simple présence de mots), en respectant les contraintes précises de la "
    "question (population, intervention, critère, sous-type de maladie…).\n\n"
    "Pour chaque article, fournis :\n"
    "1. `score` (entier) : 0 = hors sujet · 1 = marginal · 2 = pertinent · "
    "3 = très pertinent.\n"
    "2. `relevance_pct` (entier 0–100) : finesse de l'adéquation à la question, "
    "cohérent avec `score` (3 ≈ 80–100, 2 ≈ 55–79, 1 ≈ 25–54, 0 ≈ 0–24).\n"
    "3. `reason` : UNE phrase (<= 25 mots) disant CE QUE L'ARTICLE APPORTE au "
    "médecin, pas une justification de note. Commence par un verbe d'action, sois "
    "concret (population, intervention, angle étudié). Exemples du registre "
    "attendu :\n"
    "   - « Mesure directement la prévalence du floppy eyelid syndrome chez des "
    "patients apnéiques. »\n"
    "   - « Analyse l'association entre apnée du sommeil et floppy eyelid syndrome. »\n"
    "   - « Évalue l'hyperlaxité palpébrale comme signe de dépistage de l'apnée. »\n\n"
    "Réponds UNIQUEMENT via le schéma JSON imposé, un objet par PMID fourni.\n\n"
    "Question clinique du médecin : {prm}\n\n"
    "Articles :\n"
)


@dataclass
class Judgement:
    score: int
    reason: str
    relevance_pct: int | None = None


class JudgeError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def _render_articles(articles: list[dict]) -> str:
    blocks = []
    for a in articles:
        abstract = (a.get("abstract") or "").strip()
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
        blocks.append(
            f"- PMID {a['pmid']}\n"
            f"  Titre : {a.get('title') or ''}\n"
            f"  Résumé : {abstract or '(résumé indisponible)'}"
        )
    return "\n".join(blocks)


def judge_articles(
    prm: str, articles: list[dict], timeout: int = 300
) -> tuple[dict[int, Judgement], CodexUsage]:
    """Score chaque article (par PMID) de 0 à 3 vis-à-vis de `PRM`.

    `articles` : liste de dicts {pmid, title, abstract}. Retourne ({pmid: Judgement},
    usage). Lève `JudgeError` si codex est indisponible / illisible.
    """
    if not articles:
        return {}, CodexUsage()

    prompt = _PROMPT_HEAD.format(prm=prm) + _render_articles(articles)
    try:
        data, usage = run_codex(prompt, _SCHEMA, timeout)
    except CodexCliError as e:
        raise JudgeError(str(e)) from e

    out: dict[int, Judgement] = {}
    for j in data.get("judgements", []):
        try:
            pmid = int(j["pmid"])
            score = max(0, min(3, int(j["score"])))
        except (KeyError, TypeError, ValueError):
            continue
        # relevance_pct est optionnel/borné ; à défaut on retombe sur le score 0–3.
        pct: int | None
        try:
            pct = max(0, min(100, int(j["relevance_pct"])))
        except (KeyError, TypeError, ValueError):
            pct = None
        out[pmid] = Judgement(
            score=score,
            reason=str(j.get("reason", "")).strip(),
            relevance_pct=pct,
        )
    return out, usage
