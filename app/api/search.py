"""Endpoints de recherche PubMed + IA, traduction FR et analyse comparative."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date
from functools import reduce
from itertools import zip_longest
from queue import Empty, Queue
from threading import Thread
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import CorpusSessionLocal, SessionLocal, get_corpus_session, get_session
from app.models import Article, ArticleSearch
from app.services import search_cancel
from app.services.explainability import explain_article
from app.services.usage_log import record_usage

router = APIRouter()

# Garde-fou latence du pré-filtre local, budget TOTAL de l'échelle de relâchement
# (toutes tentatives confondues, voir _local_prefilter). Depuis que le pré-filtre
# interroge les concepts en ET, une requête saine tient en quelques secondes :
# au-delà, ce n'est plus « le sujet est large », c'est une anomalie, et mieux vaut
# rendre la main vite avec les seuls résultats PubMed. Valeur dans Settings (env
# LOCAL_SEARCH_TIMEOUT_MS) ; bouton stop côté front en complément.
LOCAL_SEARCH_TIMEOUT_MS = settings.local_search_timeout_ms

# Vivier local jugé suffisant : en dessous, on relâche d'un cran (_local_prefilter).
# Ordre de grandeur voulu — le lot jugé par codex fait `judge_batch` (50 par défaut)
# et le vivier local n'est qu'une des deux sources, donc quelques dizaines suffisent
# à peser dans la fusion RRF sans déclencher un élargissement à chaque recherche.
LOCAL_MIN_POOL = 30

# Recherches locales en cours, annulables depuis le front (bouton stop) :
# token (fourni par le front) → PID du backend Postgres qui exécute la requête FTS.
# Un seul process API (uvicorn) → un dict module suffit, pas besoin de Redis.
_LOCAL_SEARCH_PIDS: dict[str, int] = {}


class ArticleExplanation(BaseModel):
    concepts: list[str]
    population: str | None
    intervention: str | None
    study_type: str | None


class ArticleResult(BaseModel):
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    evidence_level: int | None
    mesh_terms: list[str] | None
    abstract_snippet: str | None
    doi: str | None
    score: float | None = None
    pubmed_url: str
    explanation: ArticleExplanation


def _to_result(
    row: Article, score: float | None = None, query: str | None = None
) -> ArticleResult:
    snippet = None
    if row.abstract:
        snippet = row.abstract[:300] + ("…" if len(row.abstract) > 300 else "")
    explanation = explain_article(
        title=row.title,
        abstract=row.abstract,
        mesh_terms=row.mesh_terms,
        publication_types=row.publication_types,
        query=query,
    )
    return ArticleResult(
        pmid=row.pmid,
        title=row.title,
        journal=row.journal,
        pub_year=row.pub_year,
        evidence_level=row.evidence_level,
        mesh_terms=row.mesh_terms,
        abstract_snippet=snippet,
        doi=row.doi,
        score=score,
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{row.pmid}/",
        explanation=ArticleExplanation(
            concepts=explanation.concepts,
            population=explanation.population,
            intervention=explanation.intervention,
            study_type=explanation.study_type,
        ),
    )


@router.get("/articles/{pmid}", response_model=ArticleResult)
def get_article(pmid: int, corpus: Session = Depends(get_corpus_session)):
    article = corpus.get(Article, pmid)
    if article is None:
        raise HTTPException(status_code=404, detail="Article introuvable")
    # détail : on renvoie l'abstract complet dans le snippet
    result = _to_result(article)
    result.abstract_snippet = article.abstract
    return result


def _fetch_articles(corpus: Session, pmids: list[int]) -> dict[int, Article]:
    if not pmids:
        return {}
    rows = corpus.scalars(select(Article).where(Article.pmid.in_(pmids))).all()
    return {a.pmid: a for a in rows}


ProgressCallback = Callable[[str, str, dict], None]


# --- Méthode v2 « PubMed + codex » : filtre lexical/MeSH → codex lit & juge ---
# Voir PLAN_RECHERCHE_PUBMED_CODEX.md. Étapes :
#   1. GPT-5.6 → requête structurée (keywords_en + mesh_terms) → PubMed = A
#   2. même requête sur la base locale (FTS + MeSH) → candidats bornés → B
#   3. fusion A+B, dédup PMID, codex lit les abstracts et score (0-3),
#      tri pertinence → qualité (evidence_level) → récence = C
# Le pré-tri sémantique par vecteurs, essayé au début du projet, a été abandonné :
# jugé peu cohérent en pratique face au filtre lexical suivi du jugement codex.


class DeepSearchRequest(BaseModel):
    query: str  # PRM : phrase recherchée du médecin
    date_from: str | None = None  # st (YYYY-MM-DD ou YYYY)
    date_to: str | None = None  # ed
    k_pubmed: int = 20  # taille de A (esearch)
    max_local: int = 200  # candidats locaux (filtre FTS seul — MeSH retiré car trop coûteux en lexical) — vivier large, jugé par lots
    judge_batch: int = 50  # nombre d'abstracts jugés par codex à chaque lot (« 50 de plus »)
    min_score: int = 2  # seuil de conservation (0-3)
    # Algo v2 : fusion RRF (rang réciproque) des deux listes — PubMed Best Match +
    # local lexical — pour CHOISIR les candidats à juger (au lieu de « PubMed d'abord »),
    # afin de ne pas enterrer le local (~39 % des résultats pertinents en viennent).
    # Le tri FINAL reste toujours le score Codex. False = comportement v1 inchangé.
    rrf: bool = False
    # Minimum d'articles LOCAUX-seuls garantis dans le lot jugé (curseur UI). 0 = RRF
    # pur ; > 0 = on réserve ce nombre de places aux meilleurs candidats locaux.
    local_floor: int = 0
    # Jeton d'annulation (généré par le front pour chaque recherche). Deux usages :
    # - POST /search/local/stop/{token} annule la seule requête FTS locale (la
    #   recherche continue avec les résultats PubMed) ;
    # - POST /search/pubmed/deep/stop/{token} arrête TOUTE la recherche en cours
    #   (codex tué, pipeline stoppé au prochain jalon).
    local_token: str | None = None
    # Mode digest : la query est un metaprompt composé depuis le profil (FR, long).
    # L'envoyer brute à PubMed en repli n'aurait aucun sens — sans query-builder,
    # on échoue proprement au lieu de dégrader.
    require_builder: bool = False


class DeepHit(BaseModel):
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    doi: str | None
    pubmed_url: str
    in_db: bool
    source: Literal["pubmed", "local", "both"]
    evidence_level: int | None = None
    score: int | None = None  # 0-3 (None si non jugé) — clé de tri stable
    relevance_pct: int | None = None  # 0-100 (None si non jugé) — affichage fin
    reason: str | None = None  # « apport » : ce que l'article apporte au lecteur
    abstract: str | None = None  # abstract original (EN), toujours fourni si dispo
    abstract_fr: str | None = None  # traduction FR (cache ou streamée), si dispo
    title_fr: str | None = None  # titre traduit FR (cache ou streamé), si dispo
    # Article hors de la fenêtre de dates demandée. Purement INDICATIF : ce drapeau
    # n'intervient ni dans le filtrage ni dans le tri (cf. le tri final, par
    # pertinence seule), il sert au badge « hors période » qui dit au médecin que
    # l'article est ancien. Toujours False si aucune fenêtre n'a été demandée.
    out_of_window: bool = False


class DeepSearchResponse(BaseModel):
    query: str
    pubmed_query: str | None
    mesh_terms: list[str]
    keywords_en: list[str]
    query_builder: Literal["codex", "fallback"]
    judge: Literal["codex", "skipped"]
    codex_limit: bool = False  # quota GPT-5.6 atteint (résultats dégradés)
    codex_tokens: dict[str, int] = {}  # tokens GPT-5.6 par étape (query/judge/total)
    counts: dict[str, int]  # pubmed / local / merged / judgeable / judged / kept
    results: list[DeepHit]  # = C, classé
    # PMID jugeables (avec abstract) pas encore soumis à codex, dans l'ordre du
    # pré-filtre : le front les envoie par lots de `judge_batch` au flux « /more ».
    remaining: list[int] = []


class DeepMoreRequest(BaseModel):
    """« Analyser 50 de plus » : juge un lot de PMID déjà pré-filtrés (issus de
    `DeepSearchResponse.remaining`)."""

    query: str  # PRM : même phrase clinique que la recherche initiale
    pmids: list[int]  # lot suivant à juger (le front en envoie ≤ judge_batch)
    min_score: int = 2
    # Fenêtre de la recherche initiale — sert uniquement à marquer les articles
    # « hors période » comme dans le premier lot (jamais à filtrer ici).
    date_from: str | None = None
    date_to: str | None = None


class DeepMoreResponse(BaseModel):
    judge: Literal["codex", "skipped"]
    codex_limit: bool = False
    codex_tokens: dict[str, int] = {}
    judged: int  # abstracts effectivement jugés dans ce lot
    kept: int  # retenus (score ≥ min_score) dans ce lot
    results: list[DeepHit]


def _year(d: str | None) -> int | None:
    if not d:
        return None
    try:
        return int(str(d)[:4])
    except ValueError:
        return None


def _date_bound(d: str | None) -> date | None:
    """Borne 'YYYY-MM-DD' en date exacte ; 'YYYY' seul (ou invalide) → None."""
    if not d:
        return None
    try:
        return date.fromisoformat(str(d))
    except ValueError:
        return None


def _window_keep(
    pub_date: date | None,
    pub_year: int | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[bool, bool]:
    """(garder ?, date invérifiable ?) d'un candidat LOCAL-seul vis-à-vis de la fenêtre.

    Le pré-filtre local ne borne qu'à l'ANNÉE : une recherche « 30 derniers jours »
    laissait passer des articles de janvier. Politique (accordée avec Codex,
    recall-first) : exclusion stricte quand `pub_date` PROUVE la sortie de fenêtre ;
    à date inconnue, on retombe sur l'année (exclusion seulement si l'année sort),
    et on signale le candidat comme invérifiable (compteur `local_date_unverified`).
    Les candidats venus de PubMed (A) ne sont PAS écartés ici : esearch n'est plus
    borné (rappel maximal), ils sont seulement marqués via `_out_of_window`.
    """
    d_from, d_to = _date_bound(date_from), _date_bound(date_to)
    if pub_date is not None:
        if d_from is not None and pub_date < d_from:
            return False, False
        if d_to is not None and pub_date > d_to:
            return False, False
    unverified = pub_date is None and (date_from is not None or date_to is not None)
    year = pub_year if pub_date is None else pub_date.year
    yf, yt = _year(date_from), _year(date_to)
    if year is not None:
        if yf is not None and year < yf:
            return False, unverified
        if yt is not None and year > yt:
            return False, unverified
    return True, unverified


def _out_of_window(
    pub_date: date | None,
    pub_year: int | None,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    """Article hors de la fenêtre demandée ? (False si aucune fenêtre demandée.)

    Même politique de preuve que `_window_keep` — dont c'est la négation — mais
    appliquée à l'AFFICHAGE et non au filtrage : un article ancien reste dans la
    liste, avec un badge, au lieu d'être écarté. Une date invérifiable (année
    seule, dans la fenêtre) n'est donc jamais signalée comme hors période.
    """
    if not (date_from or date_to):
        return False
    keep, _ = _window_keep(pub_date, pub_year, date_from, date_to)
    return not keep


def _prefilter_source(corpus: Session, date_from: str | None):
    """Choisit la table du pré-filtre FTS selon la borne basse de la recherche.

    `article_search` (fenêtre récente, chaude en RAM → ~0,4 s) seulement si la
    recherche est bornée dans la fenêtre ; sinon la table complète `articles`
    (tout l'historique, mais froide → jusqu'à ~150 s, sous garde-fou timeout).
    Une recherche sans borne basse couvre tout l'historique → `articles`.

    La borne de fenêtre vient de la fonction SQL `article_search_min_year()` — même
    source de vérité que le trigger et le prune (migration 0006), et même horloge
    que la base (pas de dérive routage/DB au passage d'année civile)."""
    yf = _year(date_from)
    if not settings.use_narrow_search or yf is None:
        return Article
    min_year = corpus.scalar(sql_text("SELECT article_search_min_year()"))
    return ArticleSearch if yf >= min_year else Article


def _concept_groups(
    concepts: list[list[str]], keywords: list[str]
) -> list[list[str]]:
    """Groupes de synonymes du pré-filtre local, du plus fiable au dernier recours.

    - `concepts_en` de codex : un groupe par concept → ET des groupes (rapide) ;
    - à défaut `keywords_en` : un seul groupe, donc un OU à plat — c'est l'ancien
      comportement, lent dès qu'un mot banal traîne dans la liste. Il ne sert que
      si codex n'a pas honoré le schéma, et le garde-fou le coupe vite ;
    - rien d'exploitable : le pré-filtre est SAUTÉ. On n'envoie jamais la question
      FRANÇAISE à un index anglais — `websearch_to_tsquery('english', …)` n'en tire
      quasi aucun lexème utile et le vivier local retombait à 0 sans le dire.
    """
    from app.services.query_builder import normalize_concepts

    groups = normalize_concepts(concepts)
    if groups:
        return groups
    kw = [t.strip() for t in keywords or [] if t and t.strip()]
    return [kw] if kw else []


def _local_tsquery(groups: list[list[str]]):
    """tsquery = ET des concepts, chaque concept = OU de ses synonymes.

    **C'est le point clé de la performance du pré-filtre.** Le coût d'une requête
    FTS n'est pas dominé par la taille de la table mais par le NOMBRE DE LIGNES QUI
    MATCHENT : `ORDER BY ts_rank` doit détoaster le tsvector de chacune. Aplatir
    les concepts en un seul OU (« endometriosis OR cyst OR surgery OR pain ») revient
    à payer le mot le plus banal de la liste. Mesuré sur la fenêtre 2025-2026 :
    268 137 lignes en 92,8 s pour le OU à plat, contre 1 546 lignes en 21 ms pour
    le ET des mêmes concepts. Et le défaut est pervers : plus la question clinique
    est précise, plus codex émet de concepts, donc plus le risque qu'un mot banal
    (`pain` seul = 103 611 articles sur 2025-2026) fasse exploser le temps est grand.

    Postgres : `tsquery && tsquery` = ET. SQLAlchemy parenthèse l'expression, donc
    le `@@` de l'appelant ne capture pas le premier opérande (`fts @@ (a && b)`).
    """
    return reduce(
        lambda a, b: a.op("&&")(b),
        [func.websearch_to_tsquery("english", " OR ".join(g)) for g in groups],
    )


def _run_prefilter(
    corpus: Session,
    Src,
    groups: list[list[str]],
    conditions: list,
    limit: int,
    timeout_ms: int,
    token: str | None,
) -> tuple[list[int], str]:
    """Une tentative de pré-filtre, bornée dans sa propre transaction.

    Retourne (pmids, état) avec état ∈ {"ok", "timeout", "stopped"}.

    SET LOCAL vit jusqu'à la FIN DE LA TRANSACTION : on borne donc la requête FTS
    dans sa propre transaction, fermée des deux côtés — rollback() si Postgres
    l'annule (timeout ou bouton stop, seul le message d'erreur distingue les deux :
    « statement timeout » vs « user request »), commit() sinon. Sans cette borne,
    le timeout contaminerait les requêtes corpus suivantes (fetch abstracts…) de la
    même transaction. La session corpus n'écrit jamais : commit/rollback y sont sans
    autre effet que de clore la transaction. (Un savepoint ne suffisait pas : le
    RELEASE d'un savepoint réussi ne réinitialise PAS un SET LOCAL.)

    Enregistre le PID Postgres pour le bouton stop mais ne le retire PAS : c'est
    l'appelant qui le fait, à la fin de l'échelle. Sinon le jeton disparaîtrait
    entre deux tentatives et le bouton n'aurait rien à annuler.
    """
    tsq = _local_tsquery(groups)
    try:
        corpus.execute(
            sql_text(f"SET LOCAL statement_timeout = '{max(timeout_ms, 1)}ms'")
        )
        if token:
            _LOCAL_SEARCH_PIDS[token] = corpus.scalar(sql_text("SELECT pg_backend_pid()"))
        pmids = list(
            corpus.scalars(
                select(Src.pmid)
                .where(Src.fts.op("@@")(tsq), *conditions)
                .order_by(func.ts_rank(Src.fts, tsq).desc())
                .limit(limit)
            ).all()
        )
    except OperationalError as e:
        corpus.rollback()
        return [], "stopped" if "user request" in str(e) else "timeout"
    else:
        corpus.commit()
        return pmids, "ok"


def _interleave(head: list[int], lists: list[list[int]], limit: int) -> list[int]:
    """`head` en tête, puis les autres listes en tourniquet, sans doublon.

    Chaque variante du palier de relâchement est classée par SON ts_rank : les
    mettre bout à bout laisserait la première remplir toutes les places. Le
    tourniquet donne à chaque relâchement sa part du vivier. `head` (le palier
    strict, le plus précis) garde la tête : c'est lui qui doit peser dans la
    fusion RRF en aval.
    """
    out = list(dict.fromkeys(head))[:limit]
    seen = set(out)
    for row in zip_longest(*lists):
        for pmid in row:
            if pmid is not None and pmid not in seen:
                seen.add(pmid)
                out.append(pmid)
                if len(out) >= limit:
                    return out
    return out


def _local_prefilter(
    corpus: Session,
    Src,
    groups: list[list[str]],
    conditions: list,
    limit: int,
    token: str | None,
    emit: Callable[..., None],
) -> tuple[list[int], str]:
    """Pré-filtre local avec échelle de relâchement. Retourne (pmids, état).

    Le ET de tous les concepts est rapide mais parfois trop sévère : un article
    pertinent peut ne pas employer le vocabulaire d'un des concepts. On relâche
    alors d'un cran — chaque variante retire UN concept et garde les autres en ET —
    et on fusionne. Mesuré sur « kystes d'endométriose » (2025-2026, 3 concepts) :
    236 articles en 1,9 s pour le ET strict, 348 en 0,4 s et 1 488 en 1,3 s pour
    les variantes. On reste donc à quelques secondes là où le OU à plat dépassait
    les 120 s de garde-fou.

    Deux invariants :
    - **jamais moins de 2 concepts en ET** dans une variante — en dessous on
      retombe sur les centaines de milliers de lignes que ce code corrige ;
    - **le budget total** reste `LOCAL_SEARCH_TIMEOUT_MS`, réparti entre les
      tentatives : relâcher ne doit pas rallonger l'attente du médecin.
    """
    t0 = time.monotonic()

    def left() -> int:
        return LOCAL_SEARCH_TIMEOUT_MS - int((time.monotonic() - t0) * 1000)

    try:
        pmids, state = _run_prefilter(
            corpus, Src, groups, conditions, limit, left(), token
        )
        if state != "ok" or len(pmids) >= LOCAL_MIN_POOL or len(groups) < 3:
            return pmids, state

        emit("filter_relax",
             f"🪜 Vivier local étroit ({len(pmids)} articles) — on relâche un concept "
             "à la fois pour élargir…")
        variants: list[list[int]] = []
        for i in range(len(groups)):
            if left() <= 1_000:  # plus de budget : on s'arrête sur ce qu'on a
                break
            sub = [g for j, g in enumerate(groups) if j != i]
            got, st = _run_prefilter(corpus, Src, sub, conditions, limit, left(), token)
            if st == "stopped":  # bouton stop : on rend le palier strict, déjà acquis
                return pmids, "ok" if pmids else "stopped"
            if got:
                variants.append(got)
        return _interleave(pmids, variants, limit), "ok"
    finally:
        if token:
            _LOCAL_SEARCH_PIDS.pop(token, None)


def _candidate_order(
    a_pmids: list[int], local_pmids: list[int], rrf: bool, k: int = 60
) -> list[int]:
    """Ordre des candidats soumis au juge — **c'est ici que v1 et v2 diffèrent**.

    Les deux modes partent de la même union A ∪ B (candidats PubMed `a_pmids`,
    candidats locaux `local_pmids`), dédupliquée en gardant l'ordre d'arrivée :

    - **v1 (`rrf=False`)** — on garde cet ordre : PubMed d'abord (ordre Best
      Match), puis les locaux non déjà vus.
    - **v2 (`rrf=True`)** — fusion par rang réciproque : score = Σ 1/(k + rang)
      sur les deux listes. Bien classé par l'une OU l'autre → remonte ; par les
      deux → remonte le plus. N'utilise que les RANGS (pas les scores, donc pas
      de problème d'échelles). Le tri étant stable, deux candidats de même score
      conservent leur ordre d'origine.

    Sert à CHOISIR qui codex juge, jamais à classer le résultat final.
    """
    candidates = list(dict.fromkeys([*a_pmids, *local_pmids]))  # dédup, ordre stable
    if not rrf:
        return candidates
    rrf_score: dict[int, float] = {}
    for lst in (a_pmids, local_pmids):
        for rank, p in enumerate(lst):
            rrf_score[p] = rrf_score.get(p, 0.0) + 1.0 / (k + rank)
    candidates.sort(key=lambda p: -rrf_score.get(p, 0.0))
    return candidates


def _pick_judge_batch(
    judgeable: list[int], pubmed_pmids: set[int], batch_n: int, floor: int
) -> list[int]:
    """Choisit le lot d'abstracts effectivement soumis au juge.

    Par défaut, les `batch_n` premiers du vivier (ordre `_candidate_order`). Mais
    on garantit au moins `floor` articles **locaux-seuls** (absents de
    `pubmed_pmids`) : sinon PubMed peut monopoliser le lot et enterrer le local.
    `floor = 0` désactive le plancher ; il est borné par `batch_n`.

    Le lot renvoyé garde toujours l'ordre du vivier.
    """
    floor = min(floor, batch_n)
    first_batch = judgeable[:batch_n]
    if floor > 0 and sum(1 for p in first_batch if p not in pubmed_pmids) < floor:
        reserved = [p for p in judgeable if p not in pubmed_pmids][:floor]  # meilleurs locaux
        keep = set(reserved)
        for p in judgeable:  # complète avec le reste du vivier, dans l'ordre
            if len(keep) >= batch_n:
                break
            keep.add(p)
        order = {p: i for i, p in enumerate(judgeable)}
        first_batch = sorted(keep, key=lambda p: order[p])  # garde l'ordre du vivier
    return first_batch


def _fmt_tokens(usage) -> str:
    """Format lisible des tokens d'un appel codex (ex. « 27 014 tokens »)."""
    n = f"{usage.total_tokens:,}".replace(",", " ")
    if usage.cached_input_tokens:
        c = f"{usage.cached_input_tokens:,}".replace(",", " ")
        return f"{n} tokens (dont {c} en cache)"
    return f"{n} tokens"


# Titre tronqué dans la trace du jugement : la trace est persistée dans les
# jalons du run (JSONB), on la garde de l'ordre du Ko, pas du Mo.
JUDGE_LOG_TITLE_CHARS = 160


def _judge_detail(
    submitted: list[int],
    titles: Callable[[int], str],
    scores: dict[int, object],
    min_score: int,
) -> list[dict]:
    """Verdict de codex pour CHAQUE article soumis au juge — y compris les
    rejetés, qui sinon ne laissent aucune trace (ils ne sont ni dans `results`,
    ni dans `remaining`) et rendent le « 50 jugés → 3 retenus » inauditable.

    Un article soumis dont codex n'a rien renvoyé apparaît avec `score: null`
    (jamais silencieusement confondu avec un rejet). Trié comme le classement
    final (score, puis %), pour se lire dans le même ordre que les résultats.
    """
    rows: list[dict] = []
    for p in submitted:
        j = scores.get(p)
        score = getattr(j, "score", None)
        rows.append({
            "pmid": p,
            "title": titles(p)[:JUDGE_LOG_TITLE_CHARS],
            "score": score,
            "relevance_pct": getattr(j, "relevance_pct", None),
            "reason": getattr(j, "reason", None),
            "kept": score is not None and score >= min_score,
        })
    rows.sort(key=lambda r: (
        -(r["score"] if r["score"] is not None else -1),
        -(r["relevance_pct"] or 0),
    ))
    return rows


def _run_deep_search(
    req: DeepSearchRequest,
    corpus: Session,
    app_db: Session,
    progress: ProgressCallback | None = None,
) -> DeepSearchResponse:
    """Cœur de la recherche v2 — réutilisé par l'endpoint POST et le stream SSE.

    Deux sessions, une par monde : `corpus` (lectures articles/FTS, miroir
    PubMed) et `app_db` (cache de traduction `article_fr`). Ne jamais croiser."""
    from app.services import pubmed_eutils as eut
    from app.services.codex_judge import JudgeError, judge_articles
    from app.services.query_builder import (
        QueryBuildError,
        build_pubmed_query,
        is_usage_limit,
    )

    codex_limit = False
    codex_tokens: dict[str, int] = {"query": 0, "judge": 0, "total": 0}

    def emit(phase: str, msg: str, **data) -> None:
        if progress:
            progress(phase, msg, data)

    def note_limit(exc: Exception) -> None:
        """Si l'erreur codex est un dépassement de quota, on le signale (bandeau UI)."""
        nonlocal codex_limit
        if not codex_limit and is_usage_limit(str(exc)):
            codex_limit = True
            emit("codex_limit",
                 "🚫 Limite d'usage GPT-5.6 atteinte — résultats en mode dégradé "
                 "(pas de tri intelligent ni de traduction). Réessayez plus tard.")

    # --- Étape 1 : requête structurée + PubMed → A ---
    builder: Literal["codex", "fallback"] = "codex"
    pubmed_query: str | None = None
    mesh: list[str] = []
    keywords: list[str] = []
    concepts: list[list[str]] = []  # mots-clés groupés par concept → ET local
    emit("codex", "🚀 Construction de la requête PubMed (GPT-5.6)…")
    try:
        pq, qb_usage = build_pubmed_query(req.query)
        pubmed_query = pq["pubmed_query"]
        mesh = pq.get("mesh_terms", [])
        keywords = pq.get("keywords_en", [])
        concepts = pq.get("concepts_en", [])
        term = pubmed_query
        codex_tokens["query"] = qb_usage.total_tokens
        emit("codex_done", f"🧠 Requête PubMed construite · {_fmt_tokens(qb_usage)}",
             pubmed_query=pubmed_query, mesh_terms=mesh)
    except QueryBuildError as e:
        if req.require_builder:
            note_limit(e)
            raise HTTPException(
                502,
                "Digest indisponible : la construction de la requête PubMed "
                f"(GPT-5.6) a échoué ({e}). Réessayez plus tard.",
            )
        builder = "fallback"
        term = req.query
        note_limit(e)
        if not codex_limit:
            emit("fallback", "⚠️ codex indisponible — repli sur la question brute.")

    emit("esearch", "🔎 Interrogation de PubMed (esearch)…")
    try:
        # Rappel maximal : on n'envoie PLUS la fenêtre de dates à esearch. Sur un
        # sujet dont toute la littérature est ancienne, le défaut « depuis 2025 »
        # renvoyait 0 article là où PubMed en a (ex. floppy eyelid syndrome ×
        # glaucome à pression normale : 12 articles, aucun après 2023 — la même
        # recherche sur pubmed.ncbi.nlm.nih.gov aboutissait, la nôtre non).
        # La fenêtre devient une simple INDICATION, plus un couperet amont : les
        # articles hors fenêtre sont jugés, classés et affichés au mérite comme les
        # autres, marqués `out_of_window` (badge « hors période »).
        # Le vivier LOCAL, lui, reste borné : `_prefilter_source` s'appuie sur la
        # borne basse pour rester sur la table chaude (~0,4 s vs ~150 s).
        _, a_pmids = eut.esearch(term, retmax=req.k_pubmed)
    except Exception as e:
        raise HTTPException(502, f"PubMed indisponible : {e}")
    emit("esearch_done", f"📚 {len(a_pmids)} articles PubMed récupérés")

    # --- Étape 2 : même requête sur la base locale (FTS) → B ---
    # Pré-filtre = FTS seul (index GIN + tri ts_rank), sur les CONCEPTS de codex
    # combinés en ET (voir _local_tsquery : c'est ce qui tient le temps de réponse).
    # /!\ On N'AJOUTE PLUS `OR mesh_terms && ARRAY[...]` : un descripteur MeSH courant
    # (ex. « Heart Failure ») matche des millions d'articles que ts_rank doit tous
    # trier → la MÊME requête passait de 0,4 s à ~206 s. Les mots-clés EN de codex sont
    # déjà exhaustifs (synonymes cliniques + noms de molécules) et codex re-juge ensuite,
    # donc le gain de rappel du MeSH était marginal pour un coût prohibitif. `mesh` reste
    # utilisé pour la requête PubMed (esearch), pas pour le vivier local.
    groups = _concept_groups(concepts, keywords)
    local_pmids: list[int] = []
    local_state = "skipped"
    local_s = 0.0
    if not groups:
        emit("filter_skipped",
             "⏭️ Base locale non interrogée : pas de mots-clés anglais "
             "(construction de requête indisponible) — on s'appuie sur PubMed.")
    else:
        # La base locale miroir de PubMed compte ~25 M d'articles : on signale
        # l'étape AVANT de lancer la requête (et pas seulement après) pour que le
        # médecin voie qu'on fouille le fonds, plutôt qu'un écran figé.
        emit("filter_start",
             "🗄️ Recherche dans la base locale PubMed (~25 M d'articles)…")
        # Table étroite récente (chaude) si la recherche tient dans la fenêtre, sinon
        # la table complète. `Src` a les mêmes colonnes (pmid, pub_year, fts).
        Src = _prefilter_source(corpus, req.date_from)
        conditions = []
        yf, yt = _year(req.date_from), _year(req.date_to)
        if yf is not None:
            conditions.append(Src.pub_year >= yf)
        if yt is not None:
            conditions.append(Src.pub_year <= yt)
        t_local = time.monotonic()
        local_pmids, local_state = _local_prefilter(
            corpus, Src, groups, conditions, req.max_local, req.local_token, emit
        )
        local_s = time.monotonic() - t_local
    if local_state == "stopped":
        emit("filter_stopped",
             f"⏹️ Recherche locale interrompue au bout de {local_s:.1f}s — on "
             "continue avec les seuls résultats PubMed.")
    elif local_state == "timeout":
        emit("filter_timeout",
             f"⏱️ Recherche locale abandonnée (délai de "
             f"{LOCAL_SEARCH_TIMEOUT_MS / 1000:.0f}s dépassé) — on s'appuie "
             "sur les résultats PubMed pour cette recherche.")
    elif local_state == "ok":
        emit("filter",
             f"🧮 {len(local_pmids)} candidats locaux "
             f"(filtre lexical FTS · {local_s:.1f}s)")

    # --- Rassembler les candidats (A ∪ B) + récupérer titres/abstracts ---
    a_set, local_set = set(a_pmids), set(local_pmids)
    candidate_pmids = _candidate_order(a_pmids, local_pmids, req.rrf)
    db = _fetch_articles(corpus, candidate_pmids)

    # Fenêtre temporelle précise sur les candidats LOCAUX-seuls (les candidats A
    # sont déjà bornés au jour par esearch ; A ∩ B garde la validation PubMed).
    local_dropped = 0
    local_unverified = 0
    if req.date_from or req.date_to:
        kept: list[int] = []
        for p in candidate_pmids:
            a = db.get(p)
            if p in a_set or a is None:
                kept.append(p)
                continue
            keep, unverified = _window_keep(
                a.pub_date, a.pub_year, req.date_from, req.date_to
            )
            local_unverified += int(unverified and keep)
            if keep:
                kept.append(p)
            else:
                local_dropped += 1
        if local_dropped:
            emit("window_filter",
                 f"📅 {local_dropped} candidats locaux écartés (hors fenêtre de dates)")
        candidate_pmids = kept
        local_set &= set(kept)

    # Enrichissement des articles de A absents de la base : best-effort. Un hoquet
    # NCBI (rate-limit, XML, réseau) ne doit pas faire échouer toute la recherche —
    # on dégrade (titre/abstract manquants) plutôt que de renvoyer un 500.
    missing = [p for p in a_set if p not in db]
    meta = {}
    ext_abstracts = {}
    if missing:
        try:
            meta = eut.esummary(missing)
        except Exception:
            meta = {}
        try:
            ext_abstracts = eut.efetch_abstracts(missing)
        except Exception:
            ext_abstracts = {}

    def _title(p: int) -> str:
        return (db[p].title if p in db else (meta[p].title if p in meta else str(p)))

    def _abstract(p: int) -> str | None:
        return db[p].abstract if p in db else ext_abstracts.get(p)

    def _judge_item(p: int) -> dict:
        # Métadonnées en plus du texte : le juge peut appliquer les préférences
        # de la question (journaux, niveau de preuve, récence) au lieu de deviner.
        a, m = db.get(p), meta.get(p)
        return {
            "pmid": p,
            "title": _title(p),
            "abstract": _abstract(p),
            "journal": (a.journal if a else (m.journal if m else None)),
            "pub_year": (a.pub_year if a else (m.pub_year if m else None)),
            "evidence_level": (a.evidence_level if a else None),
        }

    # Candidats jugeables = ceux qui ont un abstract (codex doit lire le texte).
    # On ne juge que le PREMIER lot (`judge_batch`) ; le reste (`remaining`) est
    # renvoyé au front, qui peut demander « 50 de plus » via le flux /more.
    judgeable = [p for p in candidate_pmids if (_abstract(p) or "").strip()]
    # Lot jugé = les `judge_batch` premiers du vivier (ordre RRF en v2), MAIS on garantit
    # au moins `local_floor` articles locaux-seuls (curseur UI ; 0 = pas de plancher).
    first_batch = _pick_judge_batch(judgeable, a_set, req.judge_batch, req.local_floor)
    picked = set(first_batch)
    rest = [p for p in judgeable if p not in picked]
    emit("judge", f"🧬 GPT-5.6 lit et juge {len(first_batch)} abstracts "
                  f"(sur {len(judgeable)} jugeables)…")

    # --- Étape 3 : codex lit & juge le premier lot ---
    judge_mode: Literal["codex", "skipped"] = "codex"
    scores: dict[int, object] = {}
    try:
        scores, judge_usage = judge_articles(
            req.query, [_judge_item(p) for p in first_batch]
        )
        codex_tokens["judge"] = judge_usage.total_tokens
        emit("judge_done", f"🧠 Jugement terminé · {_fmt_tokens(judge_usage)}")
        # Trace auditable du tri : le verdict de chaque abstract soumis, retenu
        # ou non. Persistée avec les jalons du run, donc relisible plus tard.
        detail = _judge_detail(first_batch, _title, scores, req.min_score)
        emit("judge_detail",
             f"🔍 Détail du jugement · {len(detail)} articles évalués, "
             f"{sum(1 for r in detail if r['kept'])} retenus",
             judgements=detail)
    except JudgeError as e:
        judge_mode = "skipped"  # repli : pas de score, tri lexical + récence
        rest = []  # jugement HS → pas de pagination « 50 de plus »
        note_limit(e)

    # --- Assemblage + classement = C ---
    hits: list[DeepHit] = []
    for p in candidate_pmids:
        j = scores.get(p)
        score = j.score if j else None
        if judge_mode == "codex" and (score is None or score < req.min_score):
            continue  # rejeté par codex (ou non jugeable) quand le jugement a tourné
        a = db.get(p)
        m = meta.get(p)
        source = "both" if (p in a_set and p in local_set) else ("pubmed" if p in a_set else "local")
        hits.append(DeepHit(
            pmid=p,
            title=_title(p),
            journal=(a.journal if a else (m.journal if m else None)),
            pub_year=(a.pub_year if a else (m.pub_year if m else None)),
            doi=(a.doi if a else (m.doi if m else None)),
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{p}/",
            in_db=a is not None,
            source=source,
            evidence_level=(a.evidence_level if a else None),
            score=score,
            relevance_pct=(j.relevance_pct if j else None),
            reason=(j.reason if j else None),
            abstract=_abstract(p),
            out_of_window=_out_of_window(
                (a.pub_date if a else None),
                (a.pub_year if a else (m.pub_year if m else None)),
                req.date_from,
                req.date_to,
            ),
        ))

    # Tri final : TOUJOURS la pertinence évaluée par Codex (score → % → niveau de
    # preuve → récence), quel que soit l'algo. RRF ne sert qu'à CHOISIR les
    # candidats à juger ; il ne classe jamais ce que voit le médecin.
    # La fenêtre de dates n'entre PAS dans le tri : sur un sujet dont la
    # littérature de référence est ancienne, trier la période en premier enterrait
    # la vraie réponse (mesuré : les recommandations de traitement du syndrome de
    # Susac, 98 % de pertinence, passaient sous un article de revue à 82 % dont le
    # seul mérite était sa date). Les articles hors période sont donc classés au
    # mérite comme les autres, et signalés à l'affichage par `out_of_window`
    # (badge « hors période ») pour que le médecin sache toujours ce qu'il lit.
    hits.sort(key=lambda h: (
        -(h.score if h.score is not None else -1),
        -(h.relevance_pct if h.relevance_pct is not None else -1),
        h.evidence_level if h.evidence_level is not None else 99,
        -(h.pub_year or 0),
    ))

    # Traductions FR déjà en cache (instantané) — le reste est traduit en
    # streaming (voir l'endpoint stream), ce qui enrichit le cache au fil des
    # recherches.
    from app.services.translate import get_cached
    cached_fr = get_cached(app_db, [h.pmid for h in hits])
    for h in hits:
        tr = cached_fr.get(h.pmid)
        if tr:
            h.abstract_fr = tr.abstract_fr
            h.title_fr = tr.title_fr or None

    n_oow = sum(1 for h in hits if h.out_of_window)
    if n_oow:
        emit("out_of_window",
             f"📅 {n_oow} article(s) retenu(s) hors de votre fenêtre de dates — "
             "classés au mérite comme les autres, et signalés dans la liste.")

    emit("done", f"✅ {len(hits)} articles retenus")

    return DeepSearchResponse(
        query=req.query,
        pubmed_query=pubmed_query,
        mesh_terms=mesh,
        keywords_en=keywords,
        query_builder=builder,
        judge=judge_mode,
        codex_limit=codex_limit,
        codex_tokens={**codex_tokens, "total": codex_tokens["query"] + codex_tokens["judge"]},
        counts={
            "pubmed": len(a_set),
            "local": len(local_set),
            "merged": len(candidate_pmids),
            "judgeable": len(judgeable),
            "judged": len(scores),
            "kept": len(hits),
            # Provenance des articles RETENUS (pour le récap « X PubMed · Y local »).
            "kept_pubmed": sum(1 for h in hits if h.source == "pubmed"),
            "kept_both": sum(1 for h in hits if h.source == "both"),
            "kept_local": sum(1 for h in hits if h.source == "local"),
            # Fenêtre de dates : locaux-seuls écartés (date prouvée hors fenêtre)
            # et conservés sans date vérifiable (année seule) — pour mesurer le
            # compromis recall-first avant d'envisager pub_date dans article_search.
            "local_dropped_window": local_dropped,
            "local_date_unverified": local_unverified,
            # Retenus HORS fenêtre (venus de PubMed, qu'esearch ne borne plus) :
            # mesure directe de ce que le filtrage amont faisait disparaître.
            "kept_out_of_window": n_oow,
        },
        results=hits,
        remaining=rest,
    )


def _deep_metrics(result: DeepSearchResponse) -> dict:
    """Métriques v2 pour la notification Hermes (vrais tokens GPT-5.6)."""
    return {
        "method": "v2 (filtre lexical/MeSH + jugement codex)",
        "pubmed_query": result.pubmed_query,
        "pubmed_total_hits": result.counts.get("pubmed"),
        "merged_candidates": result.counts.get("merged"),
        "local_abstracts": result.counts.get("local"),
        "judged": result.counts.get("judged"),
        "codex_tokens": result.codex_tokens.get("total"),
        "relevant_total": result.counts.get("kept"),
        "codex_limit": result.codex_limit,
    }


def _run_deep_more(
    req: DeepMoreRequest,
    corpus: Session,
    app_db: Session,
    progress: ProgressCallback | None = None,
) -> DeepMoreResponse:
    """Juge un lot de PMID déjà pré-filtrés (pagination « 50 de plus » de la v2).

    Réutilisé par l'endpoint POST et le flux SSE. Récupère titres/abstracts (base
    locale puis efetch NCBI pour les manquants), fait juger le lot par codex, ne
    garde que les articles ≥ `min_score`, classe et complète les traductions FR
    déjà en cache.
    """
    from app.services import pubmed_eutils as eut
    from app.services.codex_judge import JudgeError, judge_articles
    from app.services.query_builder import is_usage_limit
    from app.services.translate import get_cached

    codex_limit = False
    codex_tokens: dict[str, int] = {"judge": 0, "total": 0}

    def emit(phase: str, msg: str, **data) -> None:
        if progress:
            progress(phase, msg, data)

    pmids = list(dict.fromkeys(req.pmids))  # dédup en gardant l'ordre du pré-filtre
    db = _fetch_articles(corpus, pmids)
    missing = [p for p in pmids if p not in db]
    meta: dict = {}
    ext_abstracts: dict = {}
    if missing:
        try:
            meta = eut.esummary(missing)
        except Exception:
            meta = {}
        try:
            ext_abstracts = eut.efetch_abstracts(missing)
        except Exception:
            ext_abstracts = {}

    def _title(p: int) -> str:
        return db[p].title if p in db else (meta[p].title if p in meta else str(p))

    def _abstract(p: int) -> str | None:
        return db[p].abstract if p in db else ext_abstracts.get(p)

    def _judge_item(p: int) -> dict:
        a, m = db.get(p), meta.get(p)
        return {
            "pmid": p,
            "title": _title(p),
            "abstract": _abstract(p),
            "journal": (a.journal if a else (m.journal if m else None)),
            "pub_year": (a.pub_year if a else (m.pub_year if m else None)),
            "evidence_level": (a.evidence_level if a else None),
        }

    judgeable = [p for p in pmids if (_abstract(p) or "").strip()]
    emit("judge", f"🧬 GPT-5.6 lit et juge {len(judgeable)} abstracts de plus…")

    judge_mode: Literal["codex", "skipped"] = "codex"
    scores: dict[int, object] = {}
    try:
        scores, judge_usage = judge_articles(
            req.query, [_judge_item(p) for p in judgeable]
        )
        codex_tokens["judge"] = judge_usage.total_tokens
        emit("judge_done", f"🧠 Jugement terminé · {_fmt_tokens(judge_usage)}")
        # Même trace que la recherche initiale (cf. `_judge_detail`) : les lots
        # « 50 de plus » ne sont pas rattachés au run, elle vit donc le temps de
        # la page — mais le déroulé reste complet à l'écran.
        detail = _judge_detail(judgeable, _title, scores, req.min_score)
        emit("judge_detail",
             f"🔍 Détail du jugement · {len(detail)} articles évalués, "
             f"{sum(1 for r in detail if r['kept'])} retenus",
             judgements=detail)
    except JudgeError as e:
        judge_mode = "skipped"
        if is_usage_limit(str(e)):
            codex_limit = True
            emit("codex_limit",
                 "🚫 Limite d'usage GPT-5.6 atteinte — réessayez plus tard.")
        else:
            emit("judge_skip", f"⚠️ Jugement indisponible ({e})")

    hits: list[DeepHit] = []
    for p in pmids:
        j = scores.get(p)
        score = j.score if j else None
        if score is None or score < req.min_score:
            continue
        a = db.get(p)
        m = meta.get(p)
        hits.append(DeepHit(
            pmid=p,
            title=_title(p),
            journal=(a.journal if a else (m.journal if m else None)),
            pub_year=(a.pub_year if a else (m.pub_year if m else None)),
            doi=(a.doi if a else (m.doi if m else None)),
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{p}/",
            in_db=a is not None,
            source=("local" if a is not None else "pubmed"),
            evidence_level=(a.evidence_level if a else None),
            score=score,
            relevance_pct=(j.relevance_pct if j else None),
            reason=(j.reason if j else None),
            abstract=_abstract(p),
            out_of_window=_out_of_window(
                (a.pub_date if a else None),
                (a.pub_year if a else (m.pub_year if m else None)),
                req.date_from,
                req.date_to,
            ),
        ))

    # Même règle que la recherche initiale : pertinence seule, la fenêtre ne
    # classe pas — sinon la fusion côté front mélangerait deux ordres.
    hits.sort(key=lambda h: (
        -(h.score if h.score is not None else -1),
        -(h.relevance_pct if h.relevance_pct is not None else -1),
        h.evidence_level if h.evidence_level is not None else 99,
        -(h.pub_year or 0),
    ))

    cached_fr = get_cached(app_db, [h.pmid for h in hits])
    for h in hits:
        tr = cached_fr.get(h.pmid)
        if tr:
            h.abstract_fr = tr.abstract_fr
            h.title_fr = tr.title_fr or None

    emit("done", f"✅ {len(hits)} articles retenus dans ce lot")
    return DeepMoreResponse(
        judge=judge_mode,
        codex_limit=codex_limit,
        codex_tokens={**codex_tokens, "total": codex_tokens["judge"]},
        judged=len(scores),
        kept=len(hits),
        results=hits,
    )


@router.post("/search/pubmed/deep", response_model=DeepSearchResponse)
def search_pubmed_deep(
    req: DeepSearchRequest,
    request: Request,
    corpus: Session = Depends(get_corpus_session),
    session: Session = Depends(get_session),
):
    """Recherche v2 : PubMed (A) + base locale filtrée (B), jugée par codex."""
    record_usage(
        request,
        "search.deep",
        query=req.query,
        params={"date_from": req.date_from, "date_to": req.date_to, "rrf": req.rrf},
    )
    from app.services.search_notifications import send_search_notification

    t0 = time.monotonic()
    progress_events: list[dict] = []

    def progress(phase: str, msg: str, data: dict) -> None:
        progress_events.append(
            {"phase": phase, "msg": msg, "elapsed_s": round(time.monotonic() - t0, 1), **data}
        )

    user = request.headers.get("x-user-email")
    try:
        result = _run_deep_search(req, corpus, session, progress)
        send_search_notification(
            status="ok",
            query=req.query,
            duration_s=time.monotonic() - t0,
            metrics=_deep_metrics(result),
            progress_events=progress_events,
            user=user,
        )
        return result
    except Exception as exc:
        send_search_notification(
            status="error",
            query=req.query,
            duration_s=time.monotonic() - t0,
            metrics={"method": "v2 (filtre lexical/MeSH + jugement codex)"},
            progress_events=progress_events,
            error=str(exc),
            user=user,
        )
        raise


def _translate_kept(
    result: DeepSearchResponse,
    corpus: Session,
    app_db: Session,
    progress,
    cap: int = 20,
) -> dict[str, dict]:
    """Traduit en FR les résultats retenus pas encore traduits (cache article_fr).

    Retourne {pmid(str): {title_fr, abstract_fr}} pour l'événement SSE `translations`.
    Borné à `cap` pour maîtriser le coût ; le cache se remplit au fil des recherches.
    """
    from app.services import pubmed_eutils as eut
    from app.services.query_builder import is_usage_limit
    from app.services.translate import TranslateError, translate_abstracts

    need = [h for h in result.results if not h.abstract_fr][:cap]
    if not need:
        return {}
    progress("translate", f"🌐 Traduction FR de {len(need)} abstracts…", {})

    pmids = [h.pmid for h in need]
    items: dict[int, dict] = {}
    for a in corpus.scalars(select(Article).where(Article.pmid.in_(pmids))).all():
        if a.abstract:
            items[a.pmid] = {"pmid": a.pmid, "title": a.title, "abstract": a.abstract}
    missing = [h for h in need if h.pmid not in items]
    if missing:
        try:
            ext = eut.efetch_abstracts([h.pmid for h in missing])
            for h in missing:
                ab = ext.get(h.pmid)
                if ab:
                    items[h.pmid] = {"pmid": h.pmid, "title": h.title, "abstract": ab}
        except Exception:
            pass
    if not items:
        return {}

    try:
        fr, tr_usage = translate_abstracts(list(items.values()), app_db)
    except TranslateError as e:
        if is_usage_limit(str(e)):
            progress("codex_limit",
                     "🚫 Limite d'usage GPT-5.6 atteinte — traduction indisponible "
                     "pour l'instant. Réessayez plus tard.", {})
        else:
            progress("translate_skip", f"⚠️ Traduction indisponible ({e})", {})
        return {}
    progress("translate_done",
             f"🌐 {len(fr)} traductions ajoutées au cache · {_fmt_tokens(tr_usage)}", {})
    return {
        str(p): {"title_fr": t.title_fr, "abstract_fr": t.abstract_fr}
        for p, t in fr.items()
    }


class TranslateRequest(BaseModel):
    pmid: int
    title: str | None = None
    abstract: str | None = None  # abstract EN déjà affiché (évite un aller-retour NCBI)


class TranslateResponse(BaseModel):
    pmid: int
    title_fr: str | None
    abstract_fr: str | None


@router.post("/translate", response_model=TranslateResponse)
def translate_one(
    req: TranslateRequest,
    corpus: Session = Depends(get_corpus_session),
    session: Session = Depends(get_session),
):
    """Traduction FR à la demande d'un article (bouton « Traduire en français »).

    Sert le cache `article_fr` s'il existe, sinon appelle codex et met en cache.
    L'abstract peut être fourni par le front (déjà affiché) ; à défaut on le
    récupère dans la base locale puis, en dernier recours, via efetch NCBI.
    """
    from app.services.query_builder import is_usage_limit
    from app.services.translate import TranslateError, get_cached, translate_abstracts

    cached = get_cached(session, [req.pmid])
    if req.pmid in cached:
        tr = cached[req.pmid]
        return TranslateResponse(pmid=req.pmid, title_fr=tr.title_fr, abstract_fr=tr.abstract_fr)

    title = req.title
    abstract = (req.abstract or "").strip()
    if not abstract:
        art = corpus.get(Article, req.pmid)
        if art and art.abstract:
            abstract = art.abstract
            title = title or art.title
        else:
            from app.services import pubmed_eutils as eut

            try:
                abstract = (eut.efetch_abstracts([req.pmid]).get(req.pmid) or "").strip()
            except Exception:
                abstract = ""
    if not abstract:
        raise HTTPException(404, "Aucun abstract à traduire pour cet article.")

    try:
        fr, _ = translate_abstracts(
            [{"pmid": req.pmid, "title": title or "", "abstract": abstract}], session
        )
    except TranslateError as e:
        if is_usage_limit(str(e)):
            raise HTTPException(429, "Limite d'usage GPT-5.6 atteinte — réessayez plus tard.")
        raise HTTPException(502, f"Traduction indisponible : {e}")

    tr = fr.get(req.pmid)
    if not tr:
        raise HTTPException(502, "Traduction indisponible pour cet article.")
    return TranslateResponse(pmid=req.pmid, title_fr=tr.title_fr, abstract_fr=tr.abstract_fr)


class TranslateBatchItem(BaseModel):
    pmid: int
    title: str | None = None
    abstract: str | None = None  # abstract EN déjà affiché (évite un aller-retour NCBI)


class TranslateBatchRequest(BaseModel):
    items: list[TranslateBatchItem]


class TranslateBatchResponse(BaseModel):
    # {pmid(str): {title_fr, abstract_fr}} pour les articles traduisibles ; les PMID
    # sans abstract exploitable sont simplement absents de la map.
    translations: dict[str, TranslateResponse]


# On borne le lot pour qu'un seul appel codex tienne (argv + contexte) ; au-delà le
# front rappelle l'endpoint. Aligné sur le cap de traduction du flux de recherche.
MAX_TRANSLATE_BATCH = 50


@router.post("/translate/batch", response_model=TranslateBatchResponse)
def translate_batch(
    req: TranslateBatchRequest,
    corpus: Session = Depends(get_corpus_session),
    session: Session = Depends(get_session),
):
    """Traduit FR un lot d'articles en **un seul appel codex** (basculer une vue en
    français). Sert le cache `article_fr` pour les PMID déjà connus et ne traduit que
    le reste — d'où un coût ≈ 1 appel quel que soit le nombre d'articles déjà vus.

    L'abstract de chaque article peut être fourni par le front (déjà affiché) ; à
    défaut on le résout dans la base locale puis, en dernier recours, via efetch NCBI.
    Utilisé par la recherche ET la recherche sauvegardée (le cache est global par PMID).
    """
    from app.services import pubmed_eutils as eut
    from app.services.query_builder import is_usage_limit
    from app.services.translate import TranslateError, get_cached, translate_abstracts

    items = req.items[:MAX_TRANSLATE_BATCH]
    if not items:
        return TranslateBatchResponse(translations={})

    out: dict[str, TranslateResponse] = {}

    # 1. Cache d'abord — instantané, aucun appel codex.
    cached = get_cached(session, [it.pmid for it in items])
    for it in items:
        tr = cached.get(it.pmid)
        if tr:
            out[str(it.pmid)] = TranslateResponse(
                pmid=it.pmid, title_fr=tr.title_fr, abstract_fr=tr.abstract_fr
            )

    # 2. Pour le reste, résoudre l'abstract (front → base locale → efetch).
    need = [it for it in items if str(it.pmid) not in out]
    to_translate: list[dict] = []
    missing_pmids: list[int] = []
    for it in need:
        abstract = (it.abstract or "").strip()
        title = it.title
        if not abstract:
            art = corpus.get(Article, it.pmid)
            if art and art.abstract:
                abstract = art.abstract
                title = title or art.title
            else:
                missing_pmids.append(it.pmid)
                continue
        to_translate.append({"pmid": it.pmid, "title": title or "", "abstract": abstract})

    if missing_pmids:
        try:
            ext = eut.efetch_abstracts(missing_pmids)
        except Exception:
            ext = {}
        for it in need:
            if it.pmid in missing_pmids:
                ab = (ext.get(it.pmid) or "").strip()
                if ab:
                    to_translate.append(
                        {"pmid": it.pmid, "title": it.title or "", "abstract": ab}
                    )

    # 3. Un seul appel codex pour tout le lot non caché.
    if to_translate:
        try:
            fr, _ = translate_abstracts(to_translate, session)
        except TranslateError as e:
            if is_usage_limit(str(e)):
                raise HTTPException(429, "Limite d'usage GPT-5.6 atteinte — réessayez plus tard.")
            raise HTTPException(502, f"Traduction indisponible : {e}")
        for pmid, tr in fr.items():
            out[str(pmid)] = TranslateResponse(
                pmid=pmid, title_fr=tr.title_fr, abstract_fr=tr.abstract_fr
            )

    return TranslateBatchResponse(translations=out)


class LocalStopResponse(BaseModel):
    stopped: bool  # True si une requête locale a bien été annulée


@router.post("/search/local/stop/{token}", response_model=LocalStopResponse)
def stop_local_search(token: str):
    """Bouton stop du front : annule la requête FTS locale en cours identifiée par
    `token` (pg_cancel_backend). La recherche v2 continue avec PubMed seul — même
    chemin de repli que le timeout. Sans requête en cours (déjà finie, token
    inconnu), ne fait rien et renvoie stopped=False."""
    pid = _LOCAL_SEARCH_PIDS.get(token)
    if pid is None:
        return LocalStopResponse(stopped=False)
    # La requête FTS tourne sur la base CORPUS : le pg_cancel_backend doit
    # partir de la même base (le PID n'existe pas côté app).
    with CorpusSessionLocal() as s:
        ok = bool(s.scalar(sql_text("SELECT pg_cancel_backend(:pid)"), {"pid": pid}))
    return LocalStopResponse(stopped=ok)


@router.post("/search/pubmed/deep/stop/{token}", response_model=LocalStopResponse)
def stop_deep_search(token: str):
    """Bouton « Arrêter la recherche » du front : annule TOUTE la recherche v2 en
    cours identifiée par `token` — l'appel codex en vol est tué, la requête FTS
    locale éventuelle est annulée (pg_cancel_backend), et le pipeline s'arrête au
    prochain jalon. À distinguer de /search/local/stop/{token}, qui n'interrompt
    que le pré-filtre local (la recherche continue alors avec PubMed seul).
    Sans recherche en cours (déjà finie, jeton inconnu), renvoie stopped=False."""
    stopped = search_cancel.cancel(token)
    pid = _LOCAL_SEARCH_PIDS.get(token)
    if pid is not None:
        with CorpusSessionLocal() as s:
            s.scalar(sql_text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
    return LocalStopResponse(stopped=stopped)


@router.post("/search/pubmed/deep/more", response_model=DeepMoreResponse)
def search_pubmed_deep_more(
    req: DeepMoreRequest,
    request: Request,
    corpus: Session = Depends(get_corpus_session),
    session: Session = Depends(get_session),
):
    """« Analyser N de plus » : juge le lot de PMID fourni (cf. `remaining`)."""
    record_usage(
        request, "search.deep.more", query=req.query, params={"n_pmids": len(req.pmids)}
    )
    return _run_deep_more(req, corpus, session)


@router.get("/search/pubmed/deep/more/stream")
def search_pubmed_deep_more_stream(
    request: Request,
    query: str = Query(..., min_length=1),
    pmids: str = Query(..., description="PMID à juger, séparés par des virgules"),
    min_score: int = Query(default=2, ge=0, le=3),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    """Version SSE de /search/pubmed/deep/more : émet le déroulé puis `result`
    (forme DeepMoreResponse), comme le stream de la recherche initiale. Les
    keep-alives évitent que le proxy coupe l'appel codex (qui peut durer ~1 min)."""
    pmid_list = [int(x) for x in pmids.split(",") if x.strip().isdigit()]
    record_usage(
        request,
        "search.deep.more",
        query=query,
        params={"n_pmids": len(pmid_list), "stream": True},
    )

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()

        def progress(phase: str, msg: str, data: dict) -> None:
            elapsed = round(time.monotonic() - t0, 1)
            events.put(("log", {"phase": phase, "msg": msg, "elapsed_s": elapsed, **data}))

        def produce() -> None:
            try:
                with CorpusSessionLocal() as corpus_s, SessionLocal() as app_s:
                    result = _run_deep_more(
                        DeepMoreRequest(
                            query=query, pmids=pmid_list, min_score=min_score,
                            date_from=date_from, date_to=date_to,
                        ),
                        corpus_s,
                        app_s,
                        progress,
                    )
                    events.put(("result", result.model_dump()))
                    fr = _translate_kept(result, corpus_s, app_s, progress)
                    if fr:
                        events.put(("translations", fr))
                    events.put(("complete", {}))
            except Exception as exc:
                events.put(("error", {"msg": f"Jugement indisponible : {exc}"}))
            finally:
                events.put(None)

        Thread(target=produce, daemon=True).start()
        while True:
            try:
                event = events.get(timeout=10)
            except Empty:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                return
            event_name, payload = event
            yield sse(event_name, payload)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# Analyse critique comparative (V1) : le médecin sélectionne 2–3 articles dans
# les résultats et lance une comparaison structurée (cf. codex_critique).
# ---------------------------------------------------------------------------

# Borne dure : la V1 ne compare que 2 à 3 articles (un seul appel codex lisible).
MAX_COMPARE = 3


class CompareRequest(BaseModel):
    query: str = Field(..., min_length=1)  # question clinique (PRM)
    pmids: list[int] = Field(..., min_length=2, max_length=MAX_COMPARE)


class CompareRow(BaseModel):
    pmid: int
    title: str | None = None
    study_type: str
    population: str
    primary_outcome: str
    effect_size: str
    limits: str


class CompareResponse(BaseModel):
    query: str
    rows: list[CompareRow]
    concordance: str
    synthesis: str
    codex_limit: bool = False
    codex_tokens: dict[str, int] = {}


def _resolve_compare_articles(
    corpus: Session, pmids: list[int]
) -> dict[int, dict]:
    """Résout titre + abstract de chaque PMID : base locale d'abord, puis NCBI
    (efetch abstracts + esummary titres) pour ce qui manque. EventSource étant en
    GET, le front ne peut pas POSTer les abstracts déjà affichés — on les
    re-résout ici (2–3 PMID, rapide)."""
    out: dict[int, dict] = {}
    missing_abs: list[int] = []
    missing_title: list[int] = []
    for pmid in pmids:
        art = corpus.get(Article, pmid)
        title = art.title if art else None
        abstract = (art.abstract if art else None) or ""
        out[pmid] = {"pmid": pmid, "title": title, "abstract": abstract}
        if not abstract.strip():
            missing_abs.append(pmid)
        if not title:
            missing_title.append(pmid)

    if missing_abs:
        from app.services import pubmed_eutils as eut

        try:
            fetched = eut.efetch_abstracts(missing_abs)
        except Exception:
            fetched = {}
        for pmid, ab in fetched.items():
            out[pmid]["abstract"] = ab
    if missing_title:
        from app.services import pubmed_eutils as eut

        try:
            summ = eut.esummary(missing_title)
        except Exception:
            summ = {}
        for pmid, hit in summ.items():
            out[pmid]["title"] = hit.title
    return out


def _run_compare(
    req: CompareRequest, corpus: Session, progress: ProgressCallback | None = None
) -> CompareResponse:
    """Cœur de l'analyse critique : résout les abstracts puis appelle codex."""
    from app.services.codex_critique import CritiqueError, compare_articles
    from app.services.query_builder import is_usage_limit

    def emit(phase: str, msg: str, data: dict | None = None) -> None:
        if progress:
            progress(phase, msg, data or {})

    emit("resolve", f"Récupération des {len(req.pmids)} articles sélectionnés", {})
    resolved = _resolve_compare_articles(corpus, req.pmids)
    # On garde l'ordre de sélection du médecin.
    articles = [resolved[p] for p in req.pmids if p in resolved]
    usable = [a for a in articles if (a.get("abstract") or "").strip()]
    if len(usable) < 2:
        raise HTTPException(
            422,
            "Au moins 2 des articles sélectionnés doivent avoir un résumé "
            "exploitable pour lancer l'analyse comparative.",
        )

    emit("critique", "Analyse critique comparative par codex", {})
    try:
        critique, usage = compare_articles(req.query, usable)
    except CritiqueError as e:
        if is_usage_limit(str(e)):
            return CompareResponse(
                query=req.query, rows=[], concordance="", synthesis="",
                codex_limit=True,
            )
        raise HTTPException(502, f"Analyse critique indisponible : {e}")

    emit("done", f"Analyse terminée — {_fmt_tokens(usage)}", {})
    titles = {p: resolved[p]["title"] for p in resolved}
    rows = [
        CompareRow(
            pmid=r.pmid,
            title=titles.get(r.pmid),
            study_type=r.study_type,
            population=r.population,
            primary_outcome=r.primary_outcome,
            effect_size=r.effect_size,
            limits=r.limits,
        )
        for r in critique.rows
    ]
    return CompareResponse(
        query=req.query,
        rows=rows,
        concordance=critique.concordance,
        synthesis=critique.synthesis,
        codex_tokens={"total": usage.total_tokens},
    )


@router.post("/analyze/compare", response_model=CompareResponse)
def analyze_compare(
    req: CompareRequest,
    request: Request,
    corpus: Session = Depends(get_corpus_session),
):
    """Analyse critique comparative de 2–3 articles (non streaming, pour tests)."""
    record_usage(request, "analyze.compare", query=req.query, params={"pmids": req.pmids})
    return _run_compare(req, corpus)


@router.get("/analyze/compare/stream")
def analyze_compare_stream(
    request: Request,
    query: str = Query(..., min_length=1),
    pmids: str = Query(..., description="PMID à comparer (2–3), séparés par des virgules"),
):
    """Version SSE de /analyze/compare : émet le déroulé puis un événement
    `result` (forme CompareResponse). Les keep-alives évitent que le proxy coupe
    l'appel codex (qui peut durer ~1 min)."""
    pmid_list = [int(x) for x in pmids.split(",") if x.strip().isdigit()][:MAX_COMPARE]
    record_usage(
        request,
        "analyze.compare",
        query=query,
        params={"pmids": pmid_list, "stream": True},
    )

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()

        def progress(phase: str, msg: str, data: dict) -> None:
            elapsed = round(time.monotonic() - t0, 1)
            events.put(("log", {"phase": phase, "msg": msg, "elapsed_s": elapsed, **data}))

        def produce() -> None:
            try:
                if len(pmid_list) < 2:
                    events.put((
                        "error",
                        {"msg": "Sélectionnez 2 à 3 articles pour lancer l'analyse."},
                    ))
                    return
                with CorpusSessionLocal() as corpus_s:
                    result = _run_compare(
                        CompareRequest(query=query, pmids=pmid_list),
                        corpus_s,
                        progress,
                    )
                    events.put(("result", result.model_dump()))
            except HTTPException as exc:
                events.put(("error", {"msg": str(exc.detail)}))
            except Exception as exc:
                events.put(("error", {"msg": f"Analyse critique indisponible : {exc}"}))
            finally:
                events.put(None)

        Thread(target=produce, daemon=True).start()
        while True:
            try:
                event = events.get(timeout=10)
            except Empty:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                return
            event_name, payload = event
            yield sse(event_name, payload)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )
