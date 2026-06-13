"""Annotation in-site du gold set FR (page /annotate).

Le pool de candidats (table eval_pool) est produit par scripts.build_pool ;
les médecins notent la pertinence 0/1/2, stockée dans eval_annotations. Voir
PLAN_EVAL.md et bench/GUIDE_ANNOTATION.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


class QueryProgress(BaseModel):
    query_id: int
    theme: str | None
    query: str
    n_candidates: int
    n_annotated: int


class Candidate(BaseModel):
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    abstract: str | None
    title_fr: str | None
    abstract_fr: str | None
    pubmed_url: str
    found_by: str | None
    grade: int | None


class PoolOut(BaseModel):
    query_id: int
    theme: str | None
    query: str
    candidates: list[Candidate]


class AnnotateIn(BaseModel):
    query_id: int
    pmid: int
    grade: int = Field(ge=0, le=2)
    annotator: str | None = None


@router.get("/eval/queries", response_model=list[QueryProgress])
def eval_queries(session: Session = Depends(get_session)):
    """Liste des requêtes du pool avec l'avancement de l'annotation."""
    rows = session.execute(
        sql_text(
            """
            SELECT p.query_id, max(p.theme) AS theme, max(p.query) AS query,
                   count(*) AS n_candidates,
                   count(a.grade) AS n_annotated
            FROM eval_pool p
            LEFT JOIN eval_annotations a
              ON a.query_id = p.query_id AND a.pmid = p.pmid
            GROUP BY p.query_id
            ORDER BY p.query_id
            """
        )
    ).all()
    return [
        QueryProgress(query_id=r[0], theme=r[1], query=r[2], n_candidates=r[3], n_annotated=r[4])
        for r in rows
    ]


@router.get("/eval/pool/{query_id}", response_model=PoolOut)
def eval_pool(query_id: int, session: Session = Depends(get_session)):
    """Candidats à juger pour une requête (avec article + note courante)."""
    head = session.execute(
        sql_text("SELECT theme, query FROM eval_pool WHERE query_id = :q LIMIT 1"),
        {"q": query_id},
    ).first()
    if head is None:
        raise HTTPException(404, "Requête inconnue dans le pool")

    rows = session.execute(
        sql_text(
            """
            SELECT p.pmid, ar.title, ar.journal, ar.pub_year, ar.abstract,
                   p.found_by, a.grade, fr.title_fr, fr.abstract_fr
            FROM eval_pool p
            JOIN articles ar ON ar.pmid = p.pmid
            LEFT JOIN eval_annotations a
              ON a.query_id = p.query_id AND a.pmid = p.pmid
            LEFT JOIN article_fr fr ON fr.pmid = p.pmid
            WHERE p.query_id = :q
            ORDER BY a.grade IS NULL DESC, p.pmid
            """
        ),
        {"q": query_id},
    ).all()
    candidates = [
        Candidate(
            pmid=r[0], title=r[1], journal=r[2], pub_year=r[3], abstract=r[4],
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{r[0]}/",
            found_by=r[5], grade=r[6], title_fr=r[7], abstract_fr=r[8],
        )
        for r in rows
    ]
    return PoolOut(query_id=query_id, theme=head[0], query=head[1], candidates=candidates)


@router.post("/eval/annotate")
def eval_annotate(body: AnnotateIn, session: Session = Depends(get_session)) -> dict:
    """Enregistre (ou met à jour) la note d'un article pour une requête."""
    session.execute(
        sql_text(
            """
            INSERT INTO eval_annotations (query_id, pmid, grade, annotator)
            VALUES (:q, :p, :g, :a)
            ON CONFLICT (query_id, pmid)
            DO UPDATE SET grade = EXCLUDED.grade,
                          annotator = EXCLUDED.annotator,
                          updated_at = now()
            """
        ),
        {"q": body.query_id, "p": body.pmid, "g": body.grade, "a": body.annotator},
    )
    session.commit()
    return {"ok": True}


@router.get("/eval/gold")
def eval_gold(session: Session = Depends(get_session)) -> list[dict]:
    """Gold set compilé depuis les annotations (même format que bench/gold_fr.json)."""
    rows = session.execute(
        sql_text(
            """
            SELECT p.query_id, max(p.theme) AS theme, max(p.query) AS query,
                   a.pmid, a.grade
            FROM eval_annotations a
            JOIN eval_pool p ON p.query_id = a.query_id AND p.pmid = a.pmid
            GROUP BY p.query_id, a.pmid, a.grade
            ORDER BY p.query_id
            """
        )
    ).all()
    gold: dict[int, dict] = {}
    for query_id, theme, query, pmid, grade in rows:
        item = gold.setdefault(
            query_id, {"id": query_id, "theme": theme, "query": query, "judgments": {}}
        )
        item["judgments"][str(pmid)] = int(grade)
    return list(gold.values())
