"""Endpoints de recherche : MeSH + plein-texte (le sémantique arrive à l'étape C)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import date
from queue import Empty, Queue
from threading import Thread
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text as sql_text
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


# --- Mode « PubMed d'abord » : recherche live PubMed, puis enrichissement base ---


class PubmedRequest(BaseModel):
    query: str
    k: int = 12
    recent_days: int | None = None
    date_from: str | None = None  # YYYY-MM-DD ou YYYY (fenêtre de publication)
    date_to: str | None = None


class PubmedHitOut(BaseModel):
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    doi: str | None
    pubmed_url: str
    in_db: bool  # article déjà présent dans notre base ?
    evidence_level: int | None = None
    abstract_fr: str | None = None  # traduction FR si on l'a


class RankedPubmedHit(BaseModel):
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    evidence_level: int | None
    doi: str | None
    pubmed_url: str
    in_db: bool
    sources: list[Literal["pubmed", "local"]]
    score: float
    justification: str
    abstract_snippet: str | None


class PubmedSearchResponse(BaseModel):
    query: str
    pubmed_query: str | None  # requête PubMed construite (None si fallback)
    mesh_terms: list[str]
    query_builder: Literal["codex", "fallback"]
    total_hits: int
    results: list[PubmedHitOut]
    related: list[ArticleResult] = Field(
        default_factory=list
    )  # compatibilite avec l'ancien contrat
    ranked: list[RankedPubmedHit]
    local_abstracts: int
    codex_batches: int
    relevant_total: int


ProgressCallback = Callable[[str, str, dict], None]


def _parse_search_date(value: str | None, *, end: bool = False) -> date | None:
    if not value:
        return None
    if len(value) == 4 and value.isdigit():
        return date(int(value), 12 if end else 1, 31 if end else 1)
    return date.fromisoformat(value)


def _local_conditions(date_from: str | None, date_to: str | None) -> list:
    conditions = [
        Article.abstract.is_not(None),
        func.length(Article.abstract) > 0,
    ]
    start = _parse_search_date(date_from)
    end = _parse_search_date(date_to, end=True)
    if start:
        conditions.append(Article.pub_year >= start.year)
        conditions.append(
            or_(
                Article.pub_date >= start,
                Article.pub_date.is_(None),
            )
        )
    if end:
        conditions.append(Article.pub_year <= end.year)
        conditions.append(
            or_(
                Article.pub_date <= end,
                Article.pub_date.is_(None),
            )
        )
    return conditions


def _iter_local_abstracts(
    session: Session,
    date_from: str | None,
    date_to: str | None,
    *,
    page_size: int = 1000,
) -> Iterator[tuple[int, str, str]]:
    """Parcourt le corpus par pages sans garder un curseur DB pendant les appels Codex."""
    conditions = _local_conditions(date_from, date_to)
    last_pmid = 0
    while True:
        rows = session.execute(
            select(Article.pmid, Article.title, Article.abstract)
            .where(and_(*conditions), Article.pmid > last_pmid)
            .order_by(Article.pmid)
            .limit(page_size)
        ).all()
        if not rows:
            return
        for pmid, title, abstract in rows:
            yield pmid, title, abstract
        last_pmid = rows[-1][0]


def _fetch_articles_chunked(session: Session, pmids: set[int]) -> dict[int, Article]:
    out: dict[int, Article] = {}
    ids = sorted(pmids)
    for start in range(0, len(ids), 1000):
        out.update(_fetch_articles(session, ids[start : start + 1000]))
    return out


def _run_pubmed_codex_search(
    req: PubmedRequest,
    session: Session,
    progress: ProgressCallback | None = None,
) -> PubmedSearchResponse:
    from app.services import pubmed_eutils as eut
    from app.services.codex_abstracts import (
        AbstractCandidate,
        assess_batch,
        iter_batches,
    )
    from app.services.query_builder import QueryBuildError, build_pubmed_query

    def emit(phase: str, msg: str, **data) -> None:
        if progress:
            progress(phase, msg, data)

    builder: Literal["codex", "fallback"] = "codex"
    mesh: list[str] = []
    pubmed_query: str | None = None
    emit("codex", "Lancement de GPT-5.4 pour construire la requete PubMed...")
    try:
        pq = build_pubmed_query(req.query)
        pubmed_query = pq["pubmed_query"]
        mesh = pq.get("mesh_terms", [])
        term = pubmed_query
        emit(
            "codex_done",
            "Requete PubMed construite",
            pubmed_query=pubmed_query,
            mesh_terms=mesh,
        )
    except QueryBuildError as exc:
        builder = "fallback"
        term = req.query
        emit("fallback", f"GPT-5.4 indisponible ({exc}). Repli sur la question brute.")

    emit("esearch", "Interrogation de PubMed...")
    total, pmids = eut.esearch(
        term,
        retmax=req.k,
        reldate=req.recent_days,
        mindate=req.date_from,
        maxdate=req.date_to,
    )
    emit("esearch_done", f"{total} resultats PubMed, {len(pmids)} recuperes")

    meta = eut.esummary(pmids) if pmids else {}
    pubmed_articles = _fetch_articles(session, pmids)
    missing_abstract_pmids = [
        pmid
        for pmid in pmids
        if pmid not in pubmed_articles or not pubmed_articles[pmid].abstract
    ]
    remote_abstracts = eut.efetch_abstracts(missing_abstract_pmids)
    emit(
        "efetch_done",
        f"{len(remote_abstracts)} abstracts PubMed recuperes hors base",
    )

    fr: dict[int, str] = {}
    if pmids:
        for pmid, abstract_fr in session.execute(
            sql_text("SELECT pmid, abstract_fr FROM article_fr WHERE pmid = ANY(:ids)"),
            {"ids": pmids},
        ).all():
            fr[pmid] = abstract_fr

    results = [
        PubmedHitOut(
            pmid=pmid,
            title=(
                pubmed_articles[pmid].title
                if pmid in pubmed_articles
                else (meta[pmid].title if pmid in meta else str(pmid))
            ),
            journal=(
                pubmed_articles[pmid].journal
                if pmid in pubmed_articles
                else (meta[pmid].journal if pmid in meta else None)
            ),
            pub_year=(
                pubmed_articles[pmid].pub_year
                if pmid in pubmed_articles
                else (meta[pmid].pub_year if pmid in meta else None)
            ),
            doi=(
                pubmed_articles[pmid].doi
                if pmid in pubmed_articles
                else (meta[pmid].doi if pmid in meta else None)
            ),
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            in_db=pmid in pubmed_articles,
            evidence_level=(
                pubmed_articles[pmid].evidence_level
                if pmid in pubmed_articles
                else None
            ),
            abstract_fr=fr.get(pmid),
        )
        for pmid in pmids
    ]

    local_total = session.scalar(
        select(func.count()).select_from(Article).where(
            and_(*_local_conditions(req.date_from, req.date_to))
        )
    ) or 0
    emit(
        "local_start",
        f"Analyse exhaustive de {local_total} abstracts locaux par lots GPT-5.4...",
        local_abstracts=int(local_total),
    )

    pubmed_set = set(pmids)
    assessments = {}
    relevant_local: set[int] = set()
    batch_count = 0

    local_candidates = (
        AbstractCandidate(pmid, title, abstract)
        for pmid, title, abstract in _iter_local_abstracts(
            session, req.date_from, req.date_to
        )
    )
    for batch_count, batch in enumerate(iter_batches(local_candidates), start=1):
        emit(
            "local_batch",
            f"Lot {batch_count}: analyse de {len(batch)} abstracts...",
            batch=batch_count,
            batch_size=len(batch),
        )
        for assessment in assess_batch(req.query, batch):
            if assessment.relevant:
                relevant_local.add(assessment.pmid)
                assessments[assessment.pmid] = assessment
            elif assessment.pmid in pubmed_set:
                assessments[assessment.pmid] = assessment
        emit(
            "local_batch_done",
            f"Lot {batch_count} termine, {len(relevant_local)} articles locaux retenus",
            batch=batch_count,
            relevant_local=len(relevant_local),
        )

    # Les articles de A absents du corpus local doivent eux aussi etre lus par Codex.
    unassessed_a: list[AbstractCandidate] = []
    for pmid in pmids:
        if pmid in assessments:
            continue
        local_article = pubmed_articles.get(pmid)
        abstract = (
            local_article.abstract
            if local_article and local_article.abstract
            else remote_abstracts.get(pmid)
        )
        if abstract:
            title = (
                local_article.title
                if local_article
                else (meta[pmid].title if pmid in meta else str(pmid))
            )
            unassessed_a.append(AbstractCandidate(pmid, title, abstract))

    for batch in iter_batches(unassessed_a):
        batch_count += 1
        emit(
            "pubmed_batch",
            f"Lot {batch_count}: evaluation de {len(batch)} abstracts de A...",
            batch=batch_count,
            batch_size=len(batch),
        )
        for assessment in assess_batch(req.query, batch):
            assessments[assessment.pmid] = assessment

    relevant_a = {
        pmid
        for pmid in pmids
        if pmid in assessments and assessments[pmid].relevant
    }
    merged = relevant_local | relevant_a
    local_meta = _fetch_articles_chunked(session, merged)

    ranked: list[RankedPubmedHit] = []
    for pmid in merged:
        article = local_meta.get(pmid)
        remote = meta.get(pmid)
        assessment = assessments[pmid]
        abstract = (
            article.abstract
            if article and article.abstract
            else remote_abstracts.get(pmid)
        )
        sources: list[Literal["pubmed", "local"]] = []
        if pmid in pubmed_set:
            sources.append("pubmed")
        if pmid in relevant_local:
            sources.append("local")
        ranked.append(
            RankedPubmedHit(
                pmid=pmid,
                title=(
                    article.title
                    if article
                    else (remote.title if remote else str(pmid))
                ),
                journal=article.journal if article else (remote.journal if remote else None),
                pub_year=article.pub_year if article else (remote.pub_year if remote else None),
                evidence_level=article.evidence_level if article else None,
                doi=article.doi if article else (remote.doi if remote else None),
                pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                in_db=article is not None,
                sources=sources,
                score=assessment.score,
                justification=assessment.justification,
                abstract_snippet=(
                    abstract[:500] + ("..." if len(abstract) > 500 else "")
                    if abstract
                    else None
                ),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            item.evidence_level if item.evidence_level is not None else 99,
            -(item.pub_year or 0),
            -item.pmid,
        )
    )
    emit(
        "done",
        f"Termine: {len(merged)} articles coherents apres fusion A + B",
        relevant_total=len(merged),
        codex_batches=batch_count,
    )
    return PubmedSearchResponse(
        query=req.query,
        pubmed_query=pubmed_query,
        mesh_terms=mesh,
        query_builder=builder,
        total_hits=total,
        results=results,
        related=[],
        ranked=ranked[: req.k],
        local_abstracts=int(local_total),
        codex_batches=batch_count,
        relevant_total=len(merged),
    )


@router.post("/search/pubmed", response_model=PubmedSearchResponse)
def search_pubmed(req: PubmedRequest, session: Session = Depends(get_session)):
    """Execute la recherche PubMed + lecture exhaustive des abstracts locaux."""
    try:
        return _run_pubmed_codex_search(req, session)
    except Exception as e:
        raise HTTPException(502, f"Recherche PubMed/Codex indisponible : {e}")


@router.get("/search/pubmed/stream")
def search_pubmed_stream(
    query: str = Query(..., min_length=1),
    k: int = Query(default=12, ge=1, le=50),
    recent_days: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    """Recherche complete en SSE, avec progression de chaque lot d'abstracts."""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        events: Queue[tuple[str, dict] | None] = Queue()

        def progress(phase: str, msg: str, data: dict) -> None:
            events.put(
                (
                    "log",
                    {
                        "phase": phase,
                        "msg": f"{msg} ({round(time.monotonic() - t0, 1)}s)",
                        **data,
                    },
                )
            )

        def produce() -> None:
            try:
                with SessionLocal() as worker_session:
                    result = _run_pubmed_codex_search(
                        PubmedRequest(
                            query=query,
                            k=k,
                            recent_days=recent_days,
                            date_from=date_from,
                            date_to=date_to,
                        ),
                        worker_session,
                        progress,
                    )
                events.put(("result", result.model_dump()))
            except Exception as exc:
                events.put(
                    (
                        "error",
                        {"msg": f"Recherche PubMed/Codex indisponible : {exc}"},
                    )
                )
            finally:
                events.put(None)

        Thread(target=produce, daemon=True).start()
        while True:
            try:
                event = events.get(timeout=15)
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
    max_local: int = 50  # candidats locaux (filtre FTS+MeSH)
    judge_cap: int = 80  # plafond d'articles soumis à codex (1 appel)
    min_score: int = 2  # seuil de conservation (0-3)


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
    score: int | None = None  # 0-3 (None si non jugé)
    reason: str | None = None


class DeepSearchResponse(BaseModel):
    query: str
    pubmed_query: str | None
    mesh_terms: list[str]
    keywords_en: list[str]
    query_builder: Literal["codex", "fallback"]
    judge: Literal["codex", "skipped"]
    counts: dict[str, int]  # pubmed / local / merged / judged / kept
    results: list[DeepHit]  # = C, classé


def _year(d: str | None) -> int | None:
    if not d:
        return None
    try:
        return int(str(d)[:4])
    except ValueError:
        return None


@router.post("/search/pubmed/deep", response_model=DeepSearchResponse)
def search_pubmed_deep(req: DeepSearchRequest, session: Session = Depends(get_session)):
    """Recherche v2 : PubMed (A) + base locale filtrée (B), jugée par codex."""
    from app.services import pubmed_eutils as eut
    from app.services.codex_judge import JudgeError, judge_articles
    from app.services.query_builder import QueryBuildError, build_pubmed_query

    # --- Étape 1 : requête structurée + PubMed → A ---
    builder: Literal["codex", "fallback"] = "codex"
    pubmed_query: str | None = None
    mesh: list[str] = []
    keywords: list[str] = []
    try:
        pq = build_pubmed_query(req.query)
        pubmed_query = pq["pubmed_query"]
        mesh = pq.get("mesh_terms", [])
        keywords = pq.get("keywords_en", [])
        term = pubmed_query
    except QueryBuildError:
        builder = "fallback"
        term = req.query

    try:
        _, a_pmids = eut.esearch(
            term, retmax=req.k_pubmed,
            mindate=req.date_from, maxdate=req.date_to,
        )
    except Exception as e:
        raise HTTPException(502, f"PubMed indisponible : {e}")

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

    # --- Rassembler les candidats (A ∪ B) + récupérer titres/abstracts ---
    a_set, local_set = set(a_pmids), set(local_pmids)
    candidate_pmids = list(dict.fromkeys([*a_pmids, *local_pmids]))  # dédup, ordre stable
    db = _fetch_articles(session, candidate_pmids)

    missing = [p for p in a_set if p not in db]  # articles de A pas dans la base
    meta = eut.esummary(missing) if missing else {}
    ext_abstracts = eut.efetch_abstracts(missing) if missing else {}

    def _title(p: int) -> str:
        return (db[p].title if p in db else (meta[p].title if p in meta else str(p)))

    def _abstract(p: int) -> str | None:
        return db[p].abstract if p in db else ext_abstracts.get(p)

    # Candidats jugeables = ceux qui ont un abstract (codex doit lire le texte)
    judgeable = [p for p in candidate_pmids if (_abstract(p) or "").strip()][: req.judge_cap]

    # --- Étape 3 : codex lit & juge ---
    judge_mode: Literal["codex", "skipped"] = "codex"
    scores: dict[int, object] = {}
    try:
        scores = judge_articles(
            req.query,
            [{"pmid": p, "title": _title(p), "abstract": _abstract(p)} for p in judgeable],
        )
    except JudgeError:
        judge_mode = "skipped"  # repli : pas de score, tri lexical + récence

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
            reason=(j.reason if j else None),
        ))

    # tri : pertinence (score desc) → qualité (evidence_level asc) → récence (année desc)
    hits.sort(key=lambda h: (
        -(h.score if h.score is not None else -1),
        h.evidence_level if h.evidence_level is not None else 99,
        -(h.pub_year or 0),
    ))

    return DeepSearchResponse(
        query=req.query,
        pubmed_query=pubmed_query,
        mesh_terms=mesh,
        keywords_en=keywords,
        query_builder=builder,
        judge=judge_mode,
        counts={
            "pubmed": len(a_set),
            "local": len(local_set),
            "merged": len(candidate_pmids),
            "judged": len(scores),
            "kept": len(hits),
        },
        results=hits,
    )
