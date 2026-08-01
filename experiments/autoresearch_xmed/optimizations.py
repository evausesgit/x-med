"""Implémentations candidates partagées par les rounds techniques."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.models import Article


def fetch_articles_projected(corpus: Session, pmids: list[int]) -> dict[int, Article]:
    """Hydrate uniquement les colonnes lues par `_run_deep_search`.

    Les objets restent des `Article`, donc le reste de la pipeline ne change pas.
    Toute lecture accidentelle d'une colonne différée serait visible comme une requête
    SQL supplémentaire dans l'instrumentation du benchmark.
    """
    if not pmids:
        return {}
    rows = corpus.scalars(
        select(Article)
        .options(
            load_only(
                Article.pmid,
                Article.title,
                Article.abstract,
                Article.journal,
                Article.pub_date,
                Article.pub_year,
                Article.doi,
                Article.evidence_level,
            )
        )
        .where(Article.pmid.in_(pmids))
    ).all()
    return {article.pmid: article for article in rows}


def translation_inputs_from_hits(results: list, cap: int = 20) -> tuple[list[dict], list]:
    """Réutilise les textes déjà hydratés et isole les rares hits sans abstract.

    Retourne `(items_prêts, hits_manquants)`. Le candidat conserve donc le repli DB/
    NCBI existant uniquement pour les manquants, sans modifier ce cas dégradé.
    """
    need = [hit for hit in results if not hit.abstract_fr][:cap]
    # `_translate_kept` charge actuellement les lignes DB via la clé primaire, puis
    # ajoute les absents NCBI dans l'ordre des résultats. Rendre cet ordre explicite
    # conserve le prompt byte-identique sans refaire les lectures.
    db_ready = sorted(
        (hit for hit in need if hit.in_db and hit.abstract),
        key=lambda hit: hit.pmid,
    )
    external_ready = [hit for hit in need if not hit.in_db and hit.abstract]
    ready = [
        {"pmid": hit.pmid, "title": hit.title, "abstract": hit.abstract}
        for hit in (*db_ready, *external_ready)
    ]
    missing = [hit for hit in need if not hit.abstract]
    return ready, missing
