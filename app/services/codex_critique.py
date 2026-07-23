"""Analyse critique comparative d'un petit lot d'articles par le CLI codex (GPT-5.6).

Le médecin sélectionne 2 à 3 articles dans les résultats et lance une comparaison.
On fait LIRE à codex les abstracts des articles choisis et on lui demande de
remplir, pour chacun, une grille de lecture critique (V1) puis une synthèse
transversale (concordance + bottom-line clinique).

Même mécanique que `codex_judge.judge_articles` : on shelle `codex exec` avec
`--output-schema` pour une sortie JSON structurée (cf. `codex_cli.run_codex`). Si
codex est absent, non authentifié ou trop lent, on lève `CritiqueError`.

⚠ Contrainte de design (honnêteté) : l'analyse ne porte que sur l'abstract. Quand
une information n'y figure pas (fréquent pour NNT, IC, financement), codex doit
écrire « Non précisé dans le résumé » plutôt que de l'inventer.

Grille V1 (axes par article) :
    - study_type      : type d'étude + niveau de preuve
    - population      : population étudiée (effectif n + profil)
    - primary_outcome : critère de jugement principal
    - effect_size     : taille d'effet (RR/OR/HR, absolu vs relatif, IC, NNT…)
    - limits          : limites principales
Plus, au niveau du lot : `concordance` (les articles convergent-ils ?) et
`synthesis` (à retenir en pratique, 2–3 phrases).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.codex_cli import CodexCliError, CodexUsage, run_codex

# On borne chaque abstract pour que le lot tienne dans un seul appel codex.
MAX_ABSTRACT_CHARS = 2000

# Phrase de repli imposée quand l'info manque dans l'abstract (honnêteté).
NA = "Non précisé dans le résumé"

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pmid": {"type": "integer"},
                    "study_type": {"type": "string"},
                    "population": {"type": "string"},
                    "primary_outcome": {"type": "string"},
                    "effect_size": {"type": "string"},
                    "limits": {"type": "string"},
                },
                "required": [
                    "pmid",
                    "study_type",
                    "population",
                    "primary_outcome",
                    "effect_size",
                    "limits",
                ],
            },
        },
        "concordance": {"type": "string"},
        "synthesis": {"type": "string"},
    },
    "required": ["rows", "concordance", "synthesis"],
}

_PROMPT_HEAD = (
    "Tu es médecin et expert en lecture critique d'articles biomédicaux. Le "
    "médecin a sélectionné les articles ci-dessous pour les COMPARER au regard de "
    "sa question clinique. À partir du seul titre et résumé de chaque article, "
    "remplis une grille de lecture critique.\n\n"
    "Pour CHAQUE article, renseigne :\n"
    "1. `study_type` : type d'étude + niveau de preuve (ex. « Essai contrôlé "
    "randomisé en double aveugle — preuve élevée », « Étude de cohorte "
    "rétrospective », « Méta-analyse »).\n"
    "2. `population` : population étudiée — effectif (n) et profil (âge, pathologie, "
    "critères marquants).\n"
    "3. `primary_outcome` : critère de jugement principal (en précisant s'il est "
    "« dur » — mortalité, événement clinique — ou intermédiaire/substitut).\n"
    "4. `effect_size` : taille d'effet — RR/OR/HR, différence absolue vs relative, "
    "intervalle de confiance, NNT, p si disponibles.\n"
    "5. `limits` : limites principales (biais, puissance, généralisabilité…).\n\n"
    "Puis, au niveau du lot :\n"
    "- `concordance` : les articles vont-ils dans le même sens ? Concordances et "
    "divergences, et lequel paraît le plus solide (et pourquoi).\n"
    "- `synthesis` : à retenir en pratique clinique, en 2–3 phrases.\n\n"
    "RÈGLE D'HONNÊTETÉ ABSOLUE : ne déduis ni n'invente jamais une donnée absente "
    f"du résumé. Si une information n'y figure pas, écris exactement « {NA} ». "
    "Beaucoup d'abstracts ne donnent ni NNT, ni IC, ni financement : c'est normal "
    "de l'indiquer.\n"
    "Réponds en FRANÇAIS, de façon concise, UNIQUEMENT via le schéma JSON imposé "
    "(un objet `rows` par PMID fourni).\n\n"
    "Question clinique du médecin : {prm}\n\n"
    "Articles à comparer :\n"
)


@dataclass
class CritiqueRow:
    pmid: int
    study_type: str
    population: str
    primary_outcome: str
    effect_size: str
    limits: str


@dataclass
class Critique:
    rows: list[CritiqueRow]
    concordance: str
    synthesis: str


class CritiqueError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def _render_articles(articles: list[dict]) -> str:
    blocks = []
    for i, a in enumerate(articles, 1):
        abstract = (a.get("abstract") or "").strip()
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
        blocks.append(
            f"--- Article {i} ---\n"
            f"PMID {a['pmid']}\n"
            f"Titre : {a.get('title') or ''}\n"
            f"Résumé : {abstract or '(résumé indisponible)'}"
        )
    return "\n\n".join(blocks)


def compare_articles(
    prm: str, articles: list[dict], timeout: int = 420
) -> tuple[Critique, CodexUsage]:
    """Compare 2–3 articles (dicts {pmid, title, abstract}) vis-à-vis de `prm`.

    Retourne (Critique, usage). Lève `CritiqueError` si codex est indisponible
    ou si la sortie est illisible.
    """
    if len(articles) < 2:
        raise CritiqueError("Il faut au moins 2 articles pour une analyse comparative.")

    prompt = _PROMPT_HEAD.format(prm=prm) + _render_articles(articles)
    try:
        data, usage = run_codex(prompt, _SCHEMA, timeout)
    except CodexCliError as e:
        raise CritiqueError(str(e)) from e

    rows: list[CritiqueRow] = []
    for r in data.get("rows", []):
        try:
            pmid = int(r["pmid"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            CritiqueRow(
                pmid=pmid,
                study_type=str(r.get("study_type", "") or NA).strip(),
                population=str(r.get("population", "") or NA).strip(),
                primary_outcome=str(r.get("primary_outcome", "") or NA).strip(),
                effect_size=str(r.get("effect_size", "") or NA).strip(),
                limits=str(r.get("limits", "") or NA).strip(),
            )
        )
    if not rows:
        raise CritiqueError("Analyse critique illisible (aucune ligne renvoyée).")

    return (
        Critique(
            rows=rows,
            concordance=str(data.get("concordance", "") or "").strip(),
            synthesis=str(data.get("synthesis", "") or "").strip(),
        ),
        usage,
    )
