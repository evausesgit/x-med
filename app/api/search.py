"""Endpoints de recherche : MeSH + plein-texte (le sémantique arrive à l'étape C)."""

from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
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
    model: str = DEFAULT_MODEL


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


class PubmedSearchResponse(BaseModel):
    query: str
    pubmed_query: str | None  # requête PubMed construite (None si fallback)
    mesh_terms: list[str]
    query_builder: Literal["codex", "fallback"]
    total_hits: int
    results: list[PubmedHitOut]
    related: list[ArticleResult]  # « plus comme ceux-ci » dans notre base


@router.post("/search/pubmed", response_model=PubmedSearchResponse)
def search_pubmed(req: PubmedRequest, session: Session = Depends(get_session)):
    """Interroge PubMed en direct (requête construite par codex), puis enrichit
    avec notre base : articles que nous avons déjà + voisins sémantiques."""
    from app.services import pubmed_eutils as eut
    from app.services.query_builder import QueryBuildError, build_pubmed_query

    builder: Literal["codex", "fallback"] = "codex"
    mesh: list[str] = []
    pubmed_query: str | None = None
    try:
        pq = build_pubmed_query(req.query)
        pubmed_query = pq["pubmed_query"]
        mesh = pq.get("mesh_terms", [])
        term = pubmed_query
    except QueryBuildError:
        builder = "fallback"
        term = req.query

    try:
        total, pmids = eut.esearch(
            term, retmax=req.k, reldate=req.recent_days,
            mindate=req.date_from, maxdate=req.date_to,
        )
    except Exception as e:
        raise HTTPException(502, f"PubMed indisponible : {e}")

    meta = eut.esummary(pmids) if pmids else {}
    arts = _fetch_articles(session, pmids)
    fr: dict[int, str] = {}
    if pmids:
        for pmid, abstract_fr in session.execute(
            sql_text("SELECT pmid, abstract_fr FROM article_fr WHERE pmid = ANY(:ids)"),
            {"ids": pmids},
        ).all():
            fr[pmid] = abstract_fr

    results: list[PubmedHitOut] = []
    for pmid in pmids:
        a = arts.get(pmid)
        m = meta.get(pmid)
        results.append(
            PubmedHitOut(
                pmid=pmid,
                title=(a.title if a else (m.title if m else str(pmid))),
                journal=(a.journal if a else (m.journal if m else None)),
                pub_year=(a.pub_year if a else (m.pub_year if m else None)),
                doi=(a.doi if a else (m.doi if m else None)),
                pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                in_db=a is not None,
                evidence_level=(a.evidence_level if a else None),
                abstract_fr=fr.get(pmid),
            )
        )

    # « plus comme ceux-ci » : voisins sémantiques dans notre base (sur la question
    # d'origine — bge-m3 est multilingue), en excluant ce que PubMed a déjà remonté.
    related: list[ArticleResult] = []
    try:
        qv = _embed_query(req.model, req.query)
        table = get_model(req.model).table
        seen = pmids or [0]
        rows = session.execute(
            sql_text(
                f"""
                SELECT e.pmid, 1 - (e.v <=> (:qv)::vector) AS sim
                FROM {table} e
                WHERE e.pmid <> ALL(:seen)
                ORDER BY e.v <=> (:qv)::vector
                LIMIT :k
                """
            ),
            {"qv": qv, "seen": seen, "k": req.k},
        ).all()
        rarts = _fetch_articles(session, [p for p, _ in rows])
        related = [
            _to_result(rarts[p], float(s), query=req.query) for p, s in rows if p in rarts
        ]
    except Exception:
        related = []

    return PubmedSearchResponse(
        query=req.query,
        pubmed_query=pubmed_query,
        mesh_terms=mesh,
        query_builder=builder,
        total_hits=total,
        results=results,
        related=related,
    )


@router.get("/search/pubmed/stream")
def search_pubmed_stream(
    session: Session = Depends(get_session),
    query: str = Query(..., min_length=1),
    k: int = Query(default=12, ge=1, le=50),
    recent_days: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    model: str = Query(default=DEFAULT_MODEL),
):
    """Identique à /search/pubmed mais en streaming SSE : émet le déroulé en
    direct (lancement codex, requête construite, esearch, enrichissement) puis
    un événement `result` avec le payload final (même forme que PubmedSearchResponse)."""
    from app.services import pubmed_eutils as eut
    from app.services.query_builder import QueryBuildError, build_pubmed_query

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        t0 = time.monotonic()
        el = lambda: round(time.monotonic() - t0, 1)  # noqa: E731

        yield sse("log", {"phase": "codex", "msg": "🚀 Lancement de codex pour construire la requête PubMed…"})
        builder = "codex"
        mesh: list[str] = []
        pubmed_query: str | None = None
        try:
            pq = build_pubmed_query(query)
            pubmed_query = pq["pubmed_query"]
            mesh = pq.get("mesh_terms", [])
            term = pubmed_query
            yield sse("log", {
                "phase": "codex_done",
                "msg": f"🧠 Requête PubMed construite en {el()}s",
                "pubmed_query": pubmed_query,
                "mesh_terms": mesh,
            })
        except QueryBuildError as e:
            builder = "fallback"
            term = query
            yield sse("log", {"phase": "fallback",
                              "msg": f"⚠️ codex indisponible ({e}). Repli sur la question brute."})

        window = f" ({date_from or '…'} → {date_to or 'aujourd’hui'})" if (date_from or date_to) else ""
        yield sse("log", {"phase": "esearch", "msg": f"🔎 Interrogation de PubMed (esearch){window}…"})
        try:
            total, pmids = eut.esearch(
                term, retmax=k, reldate=recent_days, mindate=date_from, maxdate=date_to,
            )
        except Exception as e:
            yield sse("error", {"msg": f"PubMed indisponible : {e}"})
            return
        yield sse("log", {"phase": "esearch_done", "msg": f"📚 {total} résultats — {len(pmids)} récupérés"})

        meta = eut.esummary(pmids) if pmids else {}
        arts = _fetch_articles(session, pmids)
        fr: dict[int, str] = {}
        if pmids:
            for pmid, abstract_fr in session.execute(
                sql_text("SELECT pmid, abstract_fr FROM article_fr WHERE pmid = ANY(:ids)"),
                {"ids": pmids},
            ).all():
                fr[pmid] = abstract_fr
        n_in_db = sum(1 for p in pmids if p in arts)
        yield sse("log", {"phase": "enrich",
                          "msg": f"🗄️ Enrichissement base : {n_in_db}/{len(pmids)} déjà chez nous, {len(fr)} traduits"})

        results = [
            PubmedHitOut(
                pmid=pmid,
                title=(a.title if (a := arts.get(pmid)) else (m.title if (m := meta.get(pmid)) else str(pmid))),
                journal=(arts[pmid].journal if pmid in arts else (meta[pmid].journal if pmid in meta else None)),
                pub_year=(arts[pmid].pub_year if pmid in arts else (meta[pmid].pub_year if pmid in meta else None)),
                doi=(arts[pmid].doi if pmid in arts else (meta[pmid].doi if pmid in meta else None)),
                pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                in_db=pmid in arts,
                evidence_level=(arts[pmid].evidence_level if pmid in arts else None),
                abstract_fr=fr.get(pmid),
            ).model_dump()
            for pmid in pmids
        ]

        yield sse("log", {"phase": "related", "msg": "🧬 Recherche de voisins sémantiques dans notre base…"})
        related: list[dict] = []
        try:
            qv = _embed_query(model, query)
            table = get_model(model).table
            rows = session.execute(
                sql_text(
                    f"""
                    SELECT e.pmid, 1 - (e.v <=> (:qv)::vector) AS sim
                    FROM {table} e
                    WHERE e.pmid <> ALL(:seen)
                    ORDER BY e.v <=> (:qv)::vector
                    LIMIT :k
                    """
                ),
                {"qv": qv, "seen": pmids or [0], "k": k},
            ).all()
            rarts = _fetch_articles(session, [p for p, _ in rows])
            related = [
                _to_result(rarts[p], float(s), query=query).model_dump()
                for p, s in rows if p in rarts
            ]
        except Exception:
            related = []

        yield sse("log", {"phase": "done", "msg": f"✅ Terminé en {el()}s"})
        yield sse("result", {
            "query": query,
            "pubmed_query": pubmed_query,
            "mesh_terms": mesh,
            "query_builder": builder,
            "total_hits": total,
            "results": results,
            "related": related,
        })

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
