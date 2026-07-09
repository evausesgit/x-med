"""Génération de posts LinkedIn X-Med (marketing Phase 1).

Pipeline : un sujet médical → une **vraie recherche X-Med** (réutilisée si déjà
sauvegardée, sinon lancée puis sauvegardée) → rédaction d'un post bilingue FR+EN
via le CLI codex (même mécanique structurée que `translate` / `codex_judge`) →
envoi du brouillon sur Telegram via Hermes pour validation humaine.

Garde-fous (contenu santé sensible, cf. stratégie marketing) câblés dans le
prompt : citer les PMID, distinguer association/causalité, jamais de conseil
clinique, ligne disclaimer. Rien n'est publié automatiquement : on produit un
brouillon à relire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.config import settings
from app.services.codex_cli import CodexCliError, run_codex

# Les 3 formats récurrents de la stratégie LinkedIn (rotation jour après jour).
PostFormat = Literal["science", "myth", "brief"]
FORMATS: tuple[PostFormat, ...] = ("science", "myth", "brief")

_FORMAT_SPECS: dict[PostFormat, str] = {
    "science": (
        "FORMAT « What does the science really say? » / « Ce que dit vraiment la "
        "science ». Structure : 1) l'accroche = la question telle quelle ; 2) « N "
        "études analysées » (N = nombre d'études fournies) ; 3) exactement 3 "
        "conclusions claires et nuancées tirées des études ; 4) un appel à "
        "l'action vers X-Med (« Réponse complète, sources à l'appui, sur X-Med »)."
    ),
    "myth": (
        "FORMAT « Medical Myth of the Week » / « Le mythe médical de la semaine ». "
        "Structure : 1) « Mythe médical de la semaine » + l'affirmation/question ; "
        "2) un verdict honnête et nuancé (vrai / faux / ça dépend), JAMAIS "
        "caricatural ; 3) ce que montrent réellement les études fournies ; 4) "
        "appel à l'action vers X-Med."
    ),
    "brief": (
        "FORMAT « X-Med Research Brief ». Structure : 1) « Nous avons analysé la "
        "littérature sur : <sujet> » ; 2) 3 à 5 enseignements clés (« findings ») "
        "tirés des études fournies, format liste ; 3) appel à l'action vers X-Med. "
        "Ton : synthèse d'expert, factuel."
    ),
}

# Schéma de sortie imposé à codex.
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "post_fr": {"type": "string"},
        "post_en": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pmid": {"type": "integer"},
                    "title": {"type": "string"},
                },
                "required": ["pmid", "title"],
            },
        },
    },
    "required": ["post_fr", "post_en", "hashtags", "citations"],
}

_GUARDRAILS = (
    "RÈGLES IMPÉRATIVES (contenu santé, audience de médecins spécialistes — ils "
    "repèrent toute approximation) :\n"
    "- Ne JAMAIS donner de conseil clinique ni de recommandation de prescription "
    "individuelle.\n"
    "- Distinguer explicitement association et causalité ; ne pas surinterpréter.\n"
    "- Rester fidèle aux études fournies ; n'invente AUCUNE donnée, chiffre ou "
    "résultat absent du contexte.\n"
    "- Citer les études par leur PMID dans le corps du post (ex. « (PMID 12345678) »).\n"
    "- Terminer CHAQUE version (FR et EN) par une ligne de disclaimer : en FR "
    "« Synthèse de littérature à visée d'information — ne remplace pas un avis "
    "médical. » ; en EN « Literature synthesis for information only — not medical "
    "advice. »\n"
    "- Ton LinkedIn : professionnel, crédible, pas racoleur. Émojis avec parcimonie."
)


@dataclass
class Study:
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    doi: str | None
    score: int | None
    reason: str | None
    abstract: str | None
    evidence_level: int | None

    @classmethod
    def from_payload(cls, d: dict[str, Any]) -> "Study":
        return cls(
            pmid=int(d["pmid"]),
            title=d.get("title") or "",
            journal=d.get("journal"),
            pub_year=d.get("pub_year"),
            doi=d.get("doi"),
            score=d.get("score"),
            reason=d.get("reason"),
            abstract=d.get("abstract") or d.get("abstract_fr"),
            evidence_level=d.get("evidence_level"),
        )


@dataclass
class GeneratedPost:
    topic_id: str
    fmt: PostFormat
    query: str
    question_fr: str
    question_en: str
    post_fr: str
    post_en: str
    hashtags: list[str]
    citations: list[dict[str, Any]]
    n_studies: int
    search_reused: bool


class LinkedInPostError(RuntimeError):
    pass


# ---------- Recherche X-Med (réutilisation ou exécution) ----------

def _api_base() -> str:
    return f"http://127.0.0.1:{settings.api_port if settings.api_port != 8000 else 8800}"


def fetch_studies(query: str, *, base_url: str | None = None) -> tuple[list[Study], bool]:
    """Retourne (études, réutilisée?) pour une requête.

    Tente d'abord `/saved-searches/lookup` (gratuit, zéro codex). Si rien, lance
    `/search/pubmed/deep` puis sauvegarde le snapshot pour les prochaines fois.
    """
    base = base_url or _api_base()
    with httpx.Client(base_url=base, timeout=1200.0) as client:
        # 1) Réutiliser une recherche identique déjà sauvegardée.
        r = client.get("/saved-searches/lookup", params={"query": query, "method": "v2"})
        if r.status_code == 200 and r.json():
            payload = r.json()["payload"]
            return _studies_from(payload), True

        # 2) Sinon lancer une vraie recherche profonde (v2), puis la sauvegarder.
        r = client.post("/search/pubmed/deep", json={"query": query})
        if r.status_code != 200:
            raise LinkedInPostError(
                f"recherche X-Med échouée ({r.status_code}) : {r.text[:300]}"
            )
        payload = r.json()
        try:
            client.post(
                "/saved-searches",
                json={"query": query, "payload": payload, "method": "v2"},
            )
        except Exception:
            pass  # la sauvegarde est un bonus, pas un bloquant
        return _studies_from(payload), False


def _studies_from(payload: dict[str, Any]) -> list[Study]:
    results = payload.get("results") or []
    studies = [Study.from_payload(d) for d in results if d.get("pmid")]
    # Les mieux notées d'abord, on garde le haut du panier pour le post.
    studies.sort(key=lambda s: (s.score or 0), reverse=True)
    return studies


# ---------- Rédaction du post (codex) ----------

def _studies_block(studies: list[Study], limit: int = 8) -> str:
    lines: list[str] = []
    for s in studies[:limit]:
        head = f"- PMID {s.pmid} — {s.title}"
        meta = " · ".join(
            x for x in (s.journal, str(s.pub_year) if s.pub_year else None) if x
        )
        if meta:
            head += f" ({meta})"
        lines.append(head)
        if s.reason:
            lines.append(f"  Pertinence : {s.reason}")
        if s.abstract:
            lines.append(f"  Résumé : {s.abstract[:600].strip()}")
    return "\n".join(lines)


def write_post(
    *,
    fmt: PostFormat,
    question_fr: str,
    question_en: str,
    query: str,
    studies: list[Study],
    timeout: int | None = None,
) -> dict[str, Any]:
    if not studies:
        raise LinkedInPostError("aucune étude exploitable pour rédiger le post")

    prompt = (
        "Tu es le responsable contenu de X-Med, une plateforme d'intelligence "
        "médicale qui transforme la littérature scientifique en réponses "
        "exploitables. Rédige UN post LinkedIn, en deux versions (français et "
        "anglais), à partir des études réelles ci-dessous (issues d'une vraie "
        "recherche X-Med).\n\n"
        f"{_FORMAT_SPECS[fmt]}\n\n"
        f"Sujet / accroche FR : {question_fr}\n"
        f"Sujet / accroche EN : {question_en}\n"
        f"Requête X-Med : {query}\n"
        f"Nombre d'études analysées : {len(studies)}\n\n"
        f"{_GUARDRAILS}\n\n"
        "Fournis aussi 3 hashtags pertinents (sans le #, ils seront ajoutés) et "
        "la liste des PMID cités. Réponds UNIQUEMENT via le schéma JSON imposé.\n\n"
        f"Études :\n{_studies_block(studies)}"
    )
    try:
        data, _usage = run_codex(
            prompt, _SCHEMA, timeout or settings.codex_abstract_timeout
        )
    except CodexCliError as e:
        raise LinkedInPostError(f"rédaction codex échouée : {e}") from e
    return data


def generate_post(
    *,
    topic: dict[str, Any],
    fmt: PostFormat,
    base_url: str | None = None,
) -> GeneratedPost:
    query = topic["query"]
    studies, reused = fetch_studies(query, base_url=base_url)
    data = write_post(
        fmt=fmt,
        question_fr=topic["question_fr"],
        question_en=topic["question_en"],
        query=query,
        studies=studies,
    )
    return GeneratedPost(
        topic_id=topic["id"],
        fmt=fmt,
        query=query,
        question_fr=topic["question_fr"],
        question_en=topic["question_en"],
        post_fr=data["post_fr"],
        post_en=data["post_en"],
        hashtags=[h.lstrip("#") for h in data.get("hashtags", [])],
        citations=data.get("citations", []),
        n_studies=len(studies),
        search_reused=reused,
    )


# ---------- Rendu + envoi Hermes ----------

def render_draft(post: GeneratedPost) -> str:
    tags = " ".join(f"#{h}" for h in post.hashtags)
    src = "recherche réutilisée" if post.search_reused else "nouvelle recherche"
    return "\n".join(
        [
            f"📝 X-Med — brouillon LinkedIn ({post.fmt})",
            f"Sujet : {post.question_fr}",
            f"Études analysées : {post.n_studies} ({src})",
            "",
            "━━━ FR ━━━",
            post.post_fr,
            tags,
            "",
            "━━━ EN ━━━",
            post.post_en,
            tags,
            "",
            f"PMID cités : {', '.join(str(c.get('pmid')) for c in post.citations)}",
            "→ Relire, ajuster, puis coller sur la page LinkedIn X-Med.",
        ]
    )


def send_to_hermes(message: str) -> bool:
    """Envoie le brouillon sur Telegram (API Bot ou Hermes selon la config)."""
    from app.services.search_notifications import deliver_notification

    return deliver_notification(message)
