"""Endpoints de recherche : MeSH + plein-texte (le sémantique arrive à l'étape C)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_session
from app.models import Article, MeshDescriptor
from app.services.embeddings import REGISTRY, get_model
from app.services.explainability import explain_article

router = APIRouter()

DEFAULT_MODEL = settings.embedding_model_list[0] if settings.embedding_model_list else "bge_m3"


def _vec_literal(vec) -> str:
    """Formate un vecteur numpy en littéral pgvector '[..]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _embed_query(model_name: str, query: str) -> str:
    model = get_model(model_name)
    return _vec_literal(model.encode_query([query])[0])


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


class SearchResponse(BaseModel):
    total: int
    results: list[ArticleResult]


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


@router.get("/search/mesh", response_model=SearchResponse)
def search_mesh(
    session: Session = Depends(get_session),
    mesh: list[str] = Query(default=[], description="tags MeSH (répétable)"),
    q: str | None = Query(default=None, description="texte libre (plein-texte)"),
    mode: Literal["and", "or"] = Query(default="or", description="ET = tous les tags, OU = au moins un"),
    year_from: int | None = None,
    year_to: int | None = None,
    evidence_max: int | None = Query(default=None, ge=1, le=4),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Recherche par tags MeSH (ET/OU) + filtres, optionnellement croisée au plein-texte."""
    conditions = []
    if mesh:
        conditions.append(
            Article.mesh_terms.contains(mesh) if mode == "and" else Article.mesh_terms.overlap(mesh)
        )
    tsquery = None
    if q:
        tsquery = func.websearch_to_tsquery("english", q)
        conditions.append(Article.fts.op("@@")(tsquery))
    if year_from is not None:
        conditions.append(Article.pub_year >= year_from)
    if year_to is not None:
        conditions.append(Article.pub_year <= year_to)
    if evidence_max is not None:
        conditions.append(Article.evidence_level <= evidence_max)

    total = session.scalar(select(func.count()).select_from(Article).where(*conditions)) or 0

    stmt = select(Article).where(*conditions)
    if tsquery is not None:
        stmt = stmt.order_by(func.ts_rank(Article.fts, tsquery).desc())
    else:
        stmt = stmt.order_by(Article.pub_year.desc().nulls_last(), Article.pmid.desc())
    stmt = stmt.limit(limit).offset(offset)

    rows = session.scalars(stmt).all()
    return SearchResponse(total=total, results=[_to_result(r, query=q) for r in rows])


@router.get("/search", response_model=SearchResponse)
def search_fulltext(
    session: Session = Depends(get_session),
    q: str = Query(..., min_length=1, description="requête plein-texte"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Recherche plein-texte classée par pertinence (ts_rank).

    Sera étendue en recherche hybride (plein-texte + sémantique, fusion RRF)
    à l'étape C, une fois les embeddings disponibles.
    """
    tsquery = func.websearch_to_tsquery("english", q)
    cond = Article.fts.op("@@")(tsquery)
    total = session.scalar(select(func.count()).select_from(Article).where(cond)) or 0
    rank = func.ts_rank(Article.fts, tsquery)
    stmt = select(Article, rank).where(cond).order_by(rank.desc()).limit(limit).offset(offset)
    rows = session.execute(stmt).all()
    return SearchResponse(
        total=total, results=[_to_result(a, float(s), query=q) for a, s in rows]
    )


@router.get("/mesh/autocomplete")
def mesh_autocomplete(
    session: Session = Depends(get_session),
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[str]:
    """Suggestions de descripteurs MeSH par préfixe (insensible à la casse)."""
    stmt = (
        select(MeshDescriptor.name)
        .where(func.lower(MeshDescriptor.name).like(f"{q.lower()}%"))
        .order_by(MeshDescriptor.name)
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


@router.get("/articles/{pmid}", response_model=ArticleResult)
def get_article(pmid: int, session: Session = Depends(get_session)):
    article = session.get(Article, pmid)
    if article is None:
        raise HTTPException(status_code=404, detail="Article introuvable")
    # détail : on renvoie l'abstract complet dans le snippet
    result = _to_result(article)
    result.abstract_snippet = article.abstract
    return result


# ---------- Recherche sémantique & hybride ----------

class SemanticRequest(BaseModel):
    query: str
    model: str = DEFAULT_MODEL
    k: int = 20


@router.get("/models")
def list_models(session: Session = Depends(get_session)) -> list[dict]:
    """Modèles d'embedding disponibles + nombre d'articles déjà vectorisés."""
    out = []
    for name, m in REGISTRY.items():
        n = session.scalar(sql_text(f"SELECT count(*) FROM {m.table}")) or 0
        out.append({"name": name, "dim": m.dim, "embedded": int(n)})
    return out


@router.get("/embeddings/progress")
def embeddings_progress(model: str = "bge_m3", session: Session = Depends(get_session)) -> dict:
    """Avancement de la vectorisation, pour la page /embeddings.

    Trois angles : couverture *globale* (tous les articles), *périmètre prévu*
    (articles avec abstract — seuls candidats à l'embedding, cf. --require-abstract)
    et détail *par année*. Le nom de table vient de REGISTRY (jamais de l'entrée
    utilisateur), donc l'interpolation est sûre.
    """
    if model not in REGISTRY:
        raise HTTPException(400, f"Modèle d'embedding inconnu : {model}")
    table = REGISTRY[model].table
    has_abstract = "a.abstract IS NOT NULL AND length(a.abstract) > 0"

    total_articles = session.scalar(sql_text("SELECT count(*) FROM articles")) or 0
    embedded_total = session.scalar(sql_text(f"SELECT count(*) FROM {table}")) or 0
    planned_total = session.scalar(
        sql_text(f"SELECT count(*) FROM articles a WHERE {has_abstract}")
    ) or 0
    planned_done = session.scalar(
        sql_text(
            f"SELECT count(*) FROM {table} e JOIN articles a ON a.pmid = e.pmid "
            f"WHERE {has_abstract}"
        )
    ) or 0

    rows = session.execute(
        sql_text(
            f"""
            SELECT a.pub_year,
                   count(*) FILTER (WHERE {has_abstract}) AS total,
                   count(e.pmid) FILTER (WHERE {has_abstract}) AS embedded
            FROM articles a
            LEFT JOIN {table} e ON e.pmid = a.pmid
            WHERE a.pub_year IS NOT NULL
            GROUP BY a.pub_year
            HAVING count(*) FILTER (WHERE {has_abstract}) > 0
            ORDER BY a.pub_year DESC
            """
        )
    ).all()
    by_year = [{"year": r[0], "total": int(r[1]), "embedded": int(r[2])} for r in rows]

    return {
        "model": model,
        "global": {"embedded": int(embedded_total), "total": int(total_articles)},
        "planned": {"embedded": int(planned_done), "total": int(planned_total)},
        "by_year": by_year,
    }


def _fetch_articles(session: Session, pmids: list[int]) -> dict[int, Article]:
    if not pmids:
        return {}
    rows = session.scalars(select(Article).where(Article.pmid.in_(pmids))).all()
    return {a.pmid: a for a in rows}


@router.get("/bench/leaderboard")
def bench_leaderboard(session: Session = Depends(get_session)) -> list[dict]:
    """Dernier run par (modèle, dataset) avec ses métriques."""
    rows = session.execute(
        sql_text(
            """
            SELECT DISTINCT ON (r.model_name, r.dataset)
                   r.id, r.model_name, r.dataset, r.created_at
            FROM bench_runs r
            ORDER BY r.model_name, r.dataset, r.created_at DESC
            """
        )
    ).all()
    out = []
    for run_id, model_name, dataset, created_at in rows:
        metrics = dict(
            session.execute(
                sql_text("SELECT metric, value FROM bench_results WHERE run_id = :r"),
                {"r": run_id},
            ).all()
        )
        out.append(
            {
                "model": model_name,
                "dataset": dataset,
                "created_at": created_at.isoformat(),
                "metrics": metrics,
            }
        )
    return out


@router.post("/search/semantic", response_model=SearchResponse)
def search_semantic(req: SemanticRequest, session: Session = Depends(get_session)):
    """Recherche par sens : embed la requête, plus proches voisins (cosinus)."""
    if req.model not in REGISTRY:
        raise HTTPException(400, f"Modèle inconnu : {req.model}")
    table = get_model(req.model).table
    try:
        qv = _embed_query(req.model, req.query)
    except Exception as e:  # modèle non téléchargé / torch absent
        raise HTTPException(503, f"Embeddings indisponibles : {e}")

    rows = session.execute(
        sql_text(
            f"""
            SELECT e.pmid, 1 - (e.v <=> (:qv)::vector) AS similarity
            FROM {table} e
            ORDER BY e.v <=> (:qv)::vector
            LIMIT :k
            """
        ),
        {"qv": qv, "k": req.k},
    ).all()

    arts = _fetch_articles(session, [pmid for pmid, _ in rows])
    results = [
        _to_result(arts[pmid], float(sim), query=req.query)
        for pmid, sim in rows
        if pmid in arts
    ]
    return SearchResponse(total=len(results), results=results)


@router.get("/search/hybrid", response_model=SearchResponse)
def search_hybrid(
    session: Session = Depends(get_session),
    q: str = Query(..., min_length=1),
    model: str = Query(default=DEFAULT_MODEL),
    limit: int = Query(default=20, ge=1, le=100),
    pool: int = Query(default=50, ge=10, le=200, description="taille du pool par méthode"),
):
    """Fusion RRF entre plein-texte (ts_rank) et sémantique (pgvector)."""
    if model not in REGISTRY:
        raise HTTPException(400, f"Modèle inconnu : {model}")
    table = get_model(model).table

    # plein-texte
    tsquery = func.websearch_to_tsquery("english", q)
    ft_ids = [
        r[0]
        for r in session.execute(
            select(Article.pmid)
            .where(Article.fts.op("@@")(tsquery))
            .order_by(func.ts_rank(Article.fts, tsquery).desc())
            .limit(pool)
        ).all()
    ]

    # sémantique
    sem_ids = []
    try:
        qv = _embed_query(model, q)
        sem_ids = [
            r[0]
            for r in session.execute(
                sql_text(
                    f"SELECT e.pmid FROM {table} e ORDER BY e.v <=> (:qv)::vector LIMIT :k"
                ),
                {"qv": qv, "k": pool},
            ).all()
        ]
    except Exception:
        pass  # si embeddings indispo, on retombe sur le plein-texte seul

    # fusion RRF (k=60)
    scores: dict[int, float] = {}
    for ranking in (ft_ids, sem_ids):
        for rank, pmid in enumerate(ranking):
            scores[pmid] = scores.get(pmid, 0.0) + 1.0 / (60 + rank + 1)
    ordered = sorted(scores, key=lambda p: scores[p], reverse=True)[:limit]

    arts = _fetch_articles(session, ordered)
    results = [
        _to_result(arts[p], round(scores[p], 5), query=q) for p in ordered if p in arts
    ]
    return SearchResponse(total=len(results), results=results)


ProgressCallback = Callable[[str, str, dict], None]


# --- Méthode v2 « PubMed + codex » : filtre lexical/MeSH → codex lit & juge ---
# Voir PLAN_RECHERCHE_PUBMED_CODEX.md. Étapes :
#   1. GPT-5.4 → requête structurée (keywords_en + mesh_terms) → PubMed = A
#   2. même requête sur la base locale (FTS + MeSH) → candidats bornés → B
#   3. fusion A+B, dédup PMID, codex lit les abstracts et score (0-3),
#      tri pertinence → qualité (evidence_level) → récence = C
# Les embeddings ne sont PAS sur le chemin critique (pré-tri pgvector peu cohérent).


class DeepSearchRequest(BaseModel):
    query: str  # PRM : phrase recherchée du médecin
    date_from: str | None = None  # st (YYYY-MM-DD ou YYYY)
    date_to: str | None = None  # ed
    k_pubmed: int = 20  # taille de A (esearch)
    max_local: int = 200  # candidats locaux (filtre FTS+MeSH) — vivier large, jugé par lots
    judge_batch: int = 50  # nombre d'abstracts jugés par codex à chaque lot (« 50 de plus »)
    min_score: int = 2  # seuil de conservation (0-3)
    # Algo v2 « hybride re-classé » : même vivier A∪B, mais tri final par pertinence
    # PubMed Best Match (A d'abord, dans l'ordre esearch ; locaux-seuls ensuite) au
    # lieu du tri par score IA. False = comportement v1 strictement inchangé.
    rank_by_pubmed: bool = False


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


class DeepSearchResponse(BaseModel):
    query: str
    pubmed_query: str | None
    mesh_terms: list[str]
    keywords_en: list[str]
    query_builder: Literal["codex", "fallback"]
    judge: Literal["codex", "skipped"]
    codex_limit: bool = False  # quota GPT-5.4 atteint (résultats dégradés)
    codex_tokens: dict[str, int] = {}  # tokens GPT-5.4 par étape (query/judge/total)
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


def _fmt_tokens(usage) -> str:
    """Format lisible des tokens d'un appel codex (ex. « 27 014 tokens »)."""
    n = f"{usage.total_tokens:,}".replace(",", " ")
    if usage.cached_input_tokens:
        c = f"{usage.cached_input_tokens:,}".replace(",", " ")
        return f"{n} tokens (dont {c} en cache)"
    return f"{n} tokens"


def _run_deep_search(
    req: DeepSearchRequest, session: Session, progress: ProgressCallback | None = None
) -> DeepSearchResponse:
    """Cœur de la recherche v2 — réutilisé par l'endpoint POST et le stream SSE."""
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
                 "🚫 Limite d'usage GPT-5.4 atteinte — résultats en mode dégradé "
                 "(pas de tri intelligent ni de traduction). Réessayez plus tard.")

    # --- Étape 1 : requête structurée + PubMed → A ---
    builder: Literal["codex", "fallback"] = "codex"
    pubmed_query: str | None = None
    mesh: list[str] = []
    keywords: list[str] = []
    emit("codex", "🚀 Construction de la requête PubMed (GPT-5.4)…")
    try:
        pq, qb_usage = build_pubmed_query(req.query)
        pubmed_query = pq["pubmed_query"]
        mesh = pq.get("mesh_terms", [])
        keywords = pq.get("keywords_en", [])
        term = pubmed_query
        codex_tokens["query"] = qb_usage.total_tokens
        emit("codex_done", f"🧠 Requête PubMed construite · {_fmt_tokens(qb_usage)}",
             pubmed_query=pubmed_query, mesh_terms=mesh)
    except QueryBuildError as e:
        builder = "fallback"
        term = req.query
        note_limit(e)
        if not codex_limit:
            emit("fallback", "⚠️ codex indisponible — repli sur la question brute.")

    emit("esearch", "🔎 Interrogation de PubMed (esearch)…")
    try:
        _, a_pmids = eut.esearch(
            term, retmax=req.k_pubmed,
            mindate=req.date_from, maxdate=req.date_to,
        )
    except Exception as e:
        raise HTTPException(502, f"PubMed indisponible : {e}")
    emit("esearch_done", f"📚 {len(a_pmids)} articles PubMed récupérés")

    # --- Étape 2 : même requête sur la base locale (FTS + MeSH) → B ---
    ts = " OR ".join(keywords) if keywords else req.query
    tsq = func.websearch_to_tsquery("english", ts)
    cond = Article.fts.op("@@")(tsq)
    if mesh:
        cond = cond | Article.mesh_terms.overlap(mesh)
    conditions = [cond]
    yf, yt = _year(req.date_from), _year(req.date_to)
    if yf is not None:
        conditions.append(Article.pub_year >= yf)
    if yt is not None:
        conditions.append(Article.pub_year <= yt)
    local_pmids = list(
        session.scalars(
            select(Article.pmid)
            .where(*conditions)
            .order_by(func.ts_rank(Article.fts, tsq).desc())
            .limit(req.max_local)
        ).all()
    )
    emit("filter", f"🧮 {len(local_pmids)} candidats locaux (filtre lexical + MeSH)")

    # --- Rassembler les candidats (A ∪ B) + récupérer titres/abstracts ---
    a_set, local_set = set(a_pmids), set(local_pmids)
    candidate_pmids = list(dict.fromkeys([*a_pmids, *local_pmids]))  # dédup, ordre stable
    db = _fetch_articles(session, candidate_pmids)

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

    # Candidats jugeables = ceux qui ont un abstract (codex doit lire le texte).
    # On ne juge que le PREMIER lot (`judge_batch`) ; le reste (`remaining`) est
    # renvoyé au front, qui peut demander « 50 de plus » via le flux /more.
    judgeable = [p for p in candidate_pmids if (_abstract(p) or "").strip()]
    first_batch = judgeable[: req.judge_batch]
    rest = judgeable[req.judge_batch :]
    emit("judge", f"🧬 GPT-5.4 lit et juge {len(first_batch)} abstracts "
                  f"(sur {len(judgeable)} jugeables)…")

    # --- Étape 3 : codex lit & juge le premier lot ---
    judge_mode: Literal["codex", "skipped"] = "codex"
    scores: dict[int, object] = {}
    try:
        scores, judge_usage = judge_articles(
            req.query,
            [{"pmid": p, "title": _title(p), "abstract": _abstract(p)} for p in first_batch],
        )
        codex_tokens["judge"] = judge_usage.total_tokens
        emit("judge_done", f"🧠 Jugement terminé · {_fmt_tokens(judge_usage)}")
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
        ))

    if req.rank_by_pubmed:
        # v2 « hybride re-classé » : ordre PubMed Best Match (A d'abord, dans l'ordre
        # de l'esearch) ; les articles locaux-seuls (absents de A) passent après,
        # départagés par le score IA. Le filtre min_score s'applique déjà plus haut.
        pubmed_rank = {p: i for i, p in enumerate(a_pmids)}
        _BIG = 10**9
        hits.sort(key=lambda h: (
            pubmed_rank.get(h.pmid, _BIG),
            -(h.score if h.score is not None else -1),
            -(h.relevance_pct if h.relevance_pct is not None else -1),
        ))
    else:
        # v1 : pertinence (score desc) → qualité (evidence_level asc) → récence (année desc)
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
    cached_fr = get_cached(session, [h.pmid for h in hits])
    for h in hits:
        tr = cached_fr.get(h.pmid)
        if tr:
            h.abstract_fr = tr.abstract_fr
            h.title_fr = tr.title_fr or None

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
        },
        results=hits,
        remaining=rest,
    )


def _deep_metrics(result: DeepSearchResponse) -> dict:
    """Métriques v2 pour la notification Hermes (vrais tokens GPT-5.4)."""
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
    req: DeepMoreRequest, session: Session, progress: ProgressCallback | None = None
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
    db = _fetch_articles(session, pmids)
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

    judgeable = [p for p in pmids if (_abstract(p) or "").strip()]
    emit("judge", f"🧬 GPT-5.4 lit et juge {len(judgeable)} abstracts de plus…")

    judge_mode: Literal["codex", "skipped"] = "codex"
    scores: dict[int, object] = {}
    try:
        scores, judge_usage = judge_articles(
            req.query,
            [{"pmid": p, "title": _title(p), "abstract": _abstract(p)} for p in judgeable],
        )
        codex_tokens["judge"] = judge_usage.total_tokens
        emit("judge_done", f"🧠 Jugement terminé · {_fmt_tokens(judge_usage)}")
    except JudgeError as e:
        judge_mode = "skipped"
        if is_usage_limit(str(e)):
            codex_limit = True
            emit("codex_limit",
                 "🚫 Limite d'usage GPT-5.4 atteinte — réessayez plus tard.")
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
        ))

    hits.sort(key=lambda h: (
        -(h.score if h.score is not None else -1),
        -(h.relevance_pct if h.relevance_pct is not None else -1),
        h.evidence_level if h.evidence_level is not None else 99,
        -(h.pub_year or 0),
    ))

    cached_fr = get_cached(session, [h.pmid for h in hits])
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
def search_pubmed_deep(req: DeepSearchRequest, session: Session = Depends(get_session)):
    """Recherche v2 : PubMed (A) + base locale filtrée (B), jugée par codex."""
    from app.services.search_notifications import send_search_notification

    t0 = time.monotonic()
    progress_events: list[dict] = []

    def progress(phase: str, msg: str, data: dict) -> None:
        progress_events.append(
            {"phase": phase, "msg": msg, "elapsed_s": round(time.monotonic() - t0, 1), **data}
        )

    try:
        result = _run_deep_search(req, session, progress)
        send_search_notification(
            status="ok",
            query=req.query,
            duration_s=time.monotonic() - t0,
            metrics=_deep_metrics(result),
            progress_events=progress_events,
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
        )
        raise


def _translate_kept(
    result: DeepSearchResponse, session: Session, progress, cap: int = 20
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
    for a in session.scalars(select(Article).where(Article.pmid.in_(pmids))).all():
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
        fr, tr_usage = translate_abstracts(list(items.values()), session)
    except TranslateError as e:
        if is_usage_limit(str(e)):
            progress("codex_limit",
                     "🚫 Limite d'usage GPT-5.4 atteinte — traduction indisponible "
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
def translate_one(req: TranslateRequest, session: Session = Depends(get_session)):
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
        art = session.get(Article, req.pmid)
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
            raise HTTPException(429, "Limite d'usage GPT-5.4 atteinte — réessayez plus tard.")
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
def translate_batch(req: TranslateBatchRequest, session: Session = Depends(get_session)):
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
            art = session.get(Article, it.pmid)
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
                raise HTTPException(429, "Limite d'usage GPT-5.4 atteinte — réessayez plus tard.")
            raise HTTPException(502, f"Traduction indisponible : {e}")
        for pmid, tr in fr.items():
            out[str(pmid)] = TranslateResponse(
                pmid=pmid, title_fr=tr.title_fr, abstract_fr=tr.abstract_fr
            )

    return TranslateBatchResponse(translations=out)


@router.get("/search/pubmed/deep/stream")
def search_pubmed_deep_stream(
    query: str = Query(..., min_length=1),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    k_pubmed: int = Query(default=20, ge=1, le=200),
    max_local: int = Query(default=200, ge=1, le=400),
    rank_by_pubmed: bool = Query(default=False),
):
    """Identique à /search/pubmed/deep mais en SSE : émet le déroulé en direct
    (les keep-alives empêchent le proxy de couper les requêtes longues) puis un
    événement `result` avec le payload final (forme DeepSearchResponse).

    `rank_by_pubmed=True` (+ `k_pubmed` élevé) = algo v2 « hybride re-classé »."""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()
        progress_events: list[dict] = []

        def progress(phase: str, msg: str, data: dict) -> None:
            elapsed = round(time.monotonic() - t0, 1)
            progress_events.append({"phase": phase, "msg": msg, "elapsed_s": elapsed, **data})
            events.put(("log", {"phase": phase, "msg": f"{msg} ({elapsed}s)", **data}))

        def produce() -> None:
            from app.services.search_notifications import send_search_notification

            notified = False
            try:
                with SessionLocal() as worker_session:
                    result = _run_deep_search(
                        DeepSearchRequest(
                            query=query, date_from=date_from, date_to=date_to,
                            k_pubmed=k_pubmed, max_local=max_local,
                            rank_by_pubmed=rank_by_pubmed,
                        ),
                        worker_session,
                        progress,
                    )
                    # Notif dès que la recherche a abouti (la traduction qui suit est
                    # un post-traitement best-effort, pas un échec de recherche).
                    send_search_notification(
                        status="ok", query=query,
                        duration_s=time.monotonic() - t0,
                        metrics=_deep_metrics(result),
                        progress_events=progress_events,
                    )
                    notified = True
                    # On envoie les résultats tout de suite (traductions en cache
                    # déjà incluses), puis on traduit le reste en arrière-plan.
                    events.put(("result", result.model_dump()))
                    fr = _translate_kept(result, worker_session, progress)
                    if fr:
                        events.put(("translations", fr))
            except Exception as exc:
                if not notified:
                    send_search_notification(
                        status="error", query=query,
                        duration_s=time.monotonic() - t0,
                        metrics={"method": "v2 (filtre lexical/MeSH + jugement codex)"},
                        progress_events=progress_events,
                        error=str(exc),
                    )
                events.put(("error", {"msg": f"Recherche v2 indisponible : {exc}"}))
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


@router.post("/search/pubmed/deep/more", response_model=DeepMoreResponse)
def search_pubmed_deep_more(req: DeepMoreRequest, session: Session = Depends(get_session)):
    """« Analyser N de plus » : juge le lot de PMID fourni (cf. `remaining`)."""
    return _run_deep_more(req, session)


@router.get("/search/pubmed/deep/more/stream")
def search_pubmed_deep_more_stream(
    query: str = Query(..., min_length=1),
    pmids: str = Query(..., description="PMID à juger, séparés par des virgules"),
    min_score: int = Query(default=2, ge=0, le=3),
):
    """Version SSE de /search/pubmed/deep/more : émet le déroulé puis `result`
    (forme DeepMoreResponse), comme le stream de la recherche initiale. Les
    keep-alives évitent que le proxy coupe l'appel codex (qui peut durer ~1 min)."""
    pmid_list = [int(x) for x in pmids.split(",") if x.strip().isdigit()]

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()

        def progress(phase: str, msg: str, data: dict) -> None:
            elapsed = round(time.monotonic() - t0, 1)
            events.put(("log", {"phase": phase, "msg": f"{msg} ({elapsed}s)", **data}))

        def produce() -> None:
            try:
                with SessionLocal() as worker_session:
                    result = _run_deep_more(
                        DeepMoreRequest(query=query, pmids=pmid_list, min_score=min_score),
                        worker_session,
                        progress,
                    )
                    events.put(("result", result.model_dump()))
                    fr = _translate_kept(result, worker_session, progress)
                    if fr:
                        events.put(("translations", fr))
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
    session: Session, pmids: list[int]
) -> dict[int, dict]:
    """Résout titre + abstract de chaque PMID : base locale d'abord, puis NCBI
    (efetch abstracts + esummary titres) pour ce qui manque. EventSource étant en
    GET, le front ne peut pas POSTer les abstracts déjà affichés — on les
    re-résout ici (2–3 PMID, rapide)."""
    out: dict[int, dict] = {}
    missing_abs: list[int] = []
    missing_title: list[int] = []
    for pmid in pmids:
        art = session.get(Article, pmid)
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
    req: CompareRequest, session: Session, progress: ProgressCallback | None = None
) -> CompareResponse:
    """Cœur de l'analyse critique : résout les abstracts puis appelle codex."""
    from app.services.codex_critique import CritiqueError, compare_articles
    from app.services.query_builder import is_usage_limit

    def emit(phase: str, msg: str, data: dict | None = None) -> None:
        if progress:
            progress(phase, msg, data or {})

    emit("resolve", f"Récupération des {len(req.pmids)} articles sélectionnés", {})
    resolved = _resolve_compare_articles(session, req.pmids)
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
def analyze_compare(req: CompareRequest, session: Session = Depends(get_session)):
    """Analyse critique comparative de 2–3 articles (non streaming, pour tests)."""
    return _run_compare(req, session)


@router.get("/analyze/compare/stream")
def analyze_compare_stream(
    query: str = Query(..., min_length=1),
    pmids: str = Query(..., description="PMID à comparer (2–3), séparés par des virgules"),
):
    """Version SSE de /analyze/compare : émet le déroulé puis un événement
    `result` (forme CompareResponse). Les keep-alives évitent que le proxy coupe
    l'appel codex (qui peut durer ~1 min)."""
    pmid_list = [int(x) for x in pmids.split(",") if x.strip().isdigit()][:MAX_COMPARE]

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()

        def progress(phase: str, msg: str, data: dict) -> None:
            elapsed = round(time.monotonic() - t0, 1)
            events.put(("log", {"phase": phase, "msg": f"{msg} ({elapsed}s)", **data}))

        def produce() -> None:
            try:
                if len(pmid_list) < 2:
                    events.put((
                        "error",
                        {"msg": "Sélectionnez 2 à 3 articles pour lancer l'analyse."},
                    ))
                    return
                with SessionLocal() as worker_session:
                    result = _run_compare(
                        CompareRequest(query=query, pmids=pmid_list),
                        worker_session,
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
