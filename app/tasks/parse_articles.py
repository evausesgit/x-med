"""Parsing streaming des fichiers PubMed .xml.gz → upsert dans `articles`.

Conçu pour la DTD NLM PubMed. Utilise lxml.iterparse (mémoire constante) :
on traite chaque <PubmedArticle> puis on libère l'élément.
"""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path
from typing import Iterator

from lxml import etree
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Article, MeshDescriptor

# --- Dérivation du niveau de preuve (1 = plus haut) ---
_EVIDENCE_BY_TYPE = {
    "Meta-Analysis": 1,
    "Systematic Review": 1,
    "Randomized Controlled Trial": 1,
    "Controlled Clinical Trial": 2,
    "Clinical Trial": 2,
    "Clinical Trial, Phase III": 2,
    "Clinical Trial, Phase IV": 2,
    "Comparative Study": 2,
    "Multicenter Study": 2,
    "Observational Study": 2,
    "Case Reports": 3,
}
# Tout le reste (Review, Editorial, Letter, Comment, Journal Article…) → 4

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _itertext(elem) -> str:
    """Texte aplati d'un nœud (gère le markup inline <i>, <sup>, …)."""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _evidence_level(pub_types: list[str]) -> int:
    levels = [_EVIDENCE_BY_TYPE[t] for t in pub_types if t in _EVIDENCE_BY_TYPE]
    return min(levels) if levels else 4


def _parse_month(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        m = int(raw)
        return m if 1 <= m <= 12 else None
    return _MONTHS.get(raw[:3].lower())


def _parse_pubdate(article_el) -> tuple[int | None, date | None]:
    """Renvoie (pub_year, pub_date) ; pub_date seulement si année+mois+jour valides."""
    pd = article_el.find("./Journal/JournalIssue/PubDate")
    if pd is None:
        return None, None
    year_el = pd.find("Year")
    year = None
    if year_el is not None and year_el.text and year_el.text.strip().isdigit():
        year = int(year_el.text.strip())
    else:
        # MedlineDate : ex "1975 Jun-Jul" → on extrait la 1re année
        md = pd.find("MedlineDate")
        if md is not None and md.text:
            for tok in md.text.split():
                if tok[:4].isdigit():
                    year = int(tok[:4])
                    break
    if year is None:
        return None, None
    month = _parse_month(_itertext(pd.find("Month")) or None)
    day_el = pd.find("Day")
    day = int(day_el.text) if (day_el is not None and day_el.text and day_el.text.strip().isdigit()) else None
    full = None
    if month and day:
        try:
            full = date(year, month, day)
        except ValueError:
            full = None
    return year, full


def _parse_authors(article_el) -> list[dict] | None:
    authors = []
    for a in article_el.findall("./AuthorList/Author"):
        coll = a.find("CollectiveName")
        if coll is not None:
            authors.append({"collective": _itertext(coll)})
            continue
        entry = {}
        for tag, key in (("LastName", "last"), ("ForeName", "fore"), ("Initials", "initials")):
            el = a.find(tag)
            if el is not None and el.text:
                entry[key] = el.text.strip()
        if entry:
            authors.append(entry)
    return authors or None


def _parse_article(citation_el) -> dict | None:
    """Extrait un <PubmedArticle> complet (MedlineCitation + PubmedData)."""
    medline = citation_el.find("MedlineCitation")
    if medline is None:
        return None
    pmid_el = medline.find("PMID")
    if pmid_el is None or not pmid_el.text:
        return None
    pmid = int(pmid_el.text)

    article_el = medline.find("Article")
    if article_el is None:
        return None

    title = _itertext(article_el.find("ArticleTitle"))

    # Abstract (sections multiples possibles, avec Label)
    parts = []
    for ab in article_el.findall("./Abstract/AbstractText"):
        label = ab.get("Label")
        txt = _itertext(ab)
        if not txt:
            continue
        parts.append(f"{label}: {txt}" if label else txt)
    abstract = "\n".join(parts) or None

    journal = _itertext(article_el.find("./Journal/Title")) or None
    issn = _itertext(article_el.find("./Journal/ISSN")) or None
    pub_year, pub_date = _parse_pubdate(article_el)

    pub_types = [_itertext(pt) for pt in article_el.findall("./PublicationTypeList/PublicationType")]
    pub_types = [p for p in pub_types if p]

    # MeSH : (ui, nom) du descripteur
    mesh_pairs: list[tuple[str, str]] = []
    for dn in medline.findall("./MeshHeadingList/MeshHeading/DescriptorName"):
        name = _itertext(dn)
        ui = dn.get("UI")
        if name and ui:
            mesh_pairs.append((ui, name))
    mesh_terms = [name for _, name in mesh_pairs] or None

    # ArticleIds (doi, pmc) dans PubmedData
    doi = pmc_id = None
    for aid in citation_el.findall("./PubmedData/ArticleIdList/ArticleId"):
        idtype = aid.get("IdType")
        if idtype == "doi" and aid.text:
            doi = aid.text.strip()
        elif idtype == "pmc" and aid.text:
            pmc_id = aid.text.strip()

    return {
        "pmid": pmid,
        "title": title or "(sans titre)",
        "abstract": abstract,
        "authors": _parse_authors(article_el),
        "journal": journal,
        "issn": issn,
        "pub_date": pub_date,
        "pub_year": pub_year,
        "mesh_terms": mesh_terms,
        "doi": doi,
        "pmc_id": pmc_id,
        "publication_types": pub_types or None,
        "evidence_level": _evidence_level(pub_types),
        "_mesh_pairs": mesh_pairs,  # extrait pour mesh_descriptors, retiré avant upsert
    }


def iter_records(path: Path) -> Iterator[tuple[str, object]]:
    """Yield ('article', dict) ou ('delete', pmid) en streaming sur un .xml.gz."""
    with gzip.open(path, "rb") as fh:
        context = etree.iterparse(fh, events=("end",), tag=("PubmedArticle", "DeleteCitation"))
        for _, elem in context:
            if elem.tag == "DeleteCitation":
                for pmid_el in elem.findall("PMID"):
                    if pmid_el.text:
                        yield "delete", int(pmid_el.text)
            else:
                rec = _parse_article(elem)
                if rec is not None:
                    yield "article", rec
            # libère la mémoire : l'élément + ses frères déjà traités
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]


# --- Upsert ---
_UPSERT_COLS = [
    "pmid", "title", "abstract", "authors", "journal", "issn", "pub_date",
    "pub_year", "mesh_terms", "doi", "pmc_id", "publication_types", "evidence_level",
]


def _flush_articles(session: Session, rows: list[dict]) -> None:
    if not rows:
        return
    stmt = insert(Article).values(rows)
    update_cols = {c: getattr(stmt.excluded, c) for c in _UPSERT_COLS if c != "pmid"}
    stmt = stmt.on_conflict_do_update(index_elements=["pmid"], set_=update_cols)
    session.execute(stmt)


def _flush_mesh(session: Session, pairs: dict[str, str]) -> None:
    if not pairs:
        return
    rows = [{"ui": ui, "name": name} for ui, name in pairs.items()]
    stmt = insert(MeshDescriptor).values(rows).on_conflict_do_nothing(index_elements=["ui"])
    session.execute(stmt)


def ingest_file(session: Session, path: Path, batch_size: int = 1000) -> dict:
    """Ingère un fichier .xml.gz. Renvoie {'articles', 'deleted'}."""
    batch: list[dict] = []
    mesh: dict[str, str] = {}
    n_articles = n_deleted = 0
    deletes: list[int] = []

    def flush():
        _flush_mesh(session, mesh)
        _flush_articles(session, batch)
        session.commit()
        batch.clear()
        mesh.clear()

    for kind, payload in iter_records(path):
        if kind == "delete":
            deletes.append(payload)
            if len(deletes) >= batch_size:
                session.execute(sql_text("DELETE FROM articles WHERE pmid = ANY(:ids)"), {"ids": deletes})
                n_deleted += len(deletes)
                deletes.clear()
            continue
        for ui, name in payload.pop("_mesh_pairs"):
            mesh[ui] = name
        batch.append(payload)
        n_articles += 1
        if len(batch) >= batch_size:
            flush()

    flush()
    if deletes:
        session.execute(sql_text("DELETE FROM articles WHERE pmid = ANY(:ids)"), {"ids": deletes})
        n_deleted += len(deletes)
        session.commit()

    return {"articles": n_articles, "deleted": n_deleted}
