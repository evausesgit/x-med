"""Endpoints de recherche : MeSH + plein-texte (le sémantique arrive à l'étape C)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
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
