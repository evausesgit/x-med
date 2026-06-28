"""Client PubMed E-utilities (esearch / esummary / efetch) — recherche à la demande.

Source distincte du flux FTP bulk (voir pubmed_ftp.py et ARCHITECTURE.md : « Deux
sources PubMed distinctes »). Utilisé par la recherche PubMed + IA
(/search/pubmed/deep) : on interroge PubMed en direct pour les articles récents et
pertinents, puis on enrichit avec notre base.

Pas de clé requise (limite NIH 3 req/s) ; une clé NCBI (gratuite) monte à 10 req/s.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from lxml import etree

from app.config import settings

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT = 20.0


def _common_params() -> dict[str, str]:
    p = {"tool": settings.ncbi_tool}
    if settings.ncbi_api_key:
        p["api_key"] = settings.ncbi_api_key
    if settings.ncbi_email:
        p["email"] = settings.ncbi_email
    return p


@dataclass
class PubmedHit:
    pmid: int
    title: str
    journal: str | None
    pub_year: int | None
    doi: str | None


def esearch(term: str, retmax: int = 20, sort: str = "relevance",
            reldate: int | None = None, mindate: str | None = None,
            maxdate: str | None = None) -> tuple[int, list[int]]:
    """Recherche PubMed. Filtre de date par fenêtre (`mindate`/`maxdate`, format
    YYYY-MM-DD ou YYYY) prioritaire ; sinon `reldate` (jours depuis aujourd'hui)."""
    params = {**_common_params(), "db": "pubmed", "term": term,
              "retmax": str(retmax), "retmode": "json", "sort": sort}
    if mindate or maxdate:
        params["datetype"] = "pdat"
        if mindate:
            params["mindate"] = mindate.replace("-", "/")
        if maxdate:
            params["maxdate"] = maxdate.replace("-", "/")
    elif reldate:
        params["reldate"] = str(reldate)
        params["datetype"] = "pdat"
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(f"{BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        d = r.json()["esearchresult"]
    return int(d.get("count", 0)), [int(x) for x in d.get("idlist", [])]


def esummary(pmids: list[int]) -> dict[int, PubmedHit]:
    """Métadonnées (titre, revue, année, DOI) pour une liste de PMID."""
    if not pmids:
        return {}
    params = {**_common_params(), "db": "pubmed",
              "id": ",".join(map(str, pmids)), "retmode": "json"}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(f"{BASE}/esummary.fcgi", params=params)
        r.raise_for_status()
        res = r.json().get("result", {})
    out: dict[int, PubmedHit] = {}
    for uid in res.get("uids", []):
        it = res[uid]
        doi = next((a.get("value") for a in it.get("articleids", [])
                    if a.get("idtype") == "doi"), None)
        pd = it.get("pubdate", "") or ""
        year = int(pd[:4]) if pd[:4].isdigit() else None
        out[int(uid)] = PubmedHit(
            pmid=int(uid),
            title=(it.get("title", "") or "").rstrip(" ."),
            journal=it.get("fulljournalname") or it.get("source"),
            pub_year=year,
            doi=doi,
        )
    return out


def efetch_abstracts(pmids: list[int]) -> dict[int, str]:
    """Résumés (texte) pour une liste de PMID, via efetch XML."""
    if not pmids:
        return {}
    params = {**_common_params(), "db": "pubmed",
              "id": ",".join(map(str, pmids)), "retmode": "xml", "rettype": "abstract"}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(f"{BASE}/efetch.fcgi", params=params)
        r.raise_for_status()
        root = etree.fromstring(r.content)
    out: dict[int, str] = {}
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        # Abstracts structurés : on préserve les sections (Label : texte, une par
        # ligne) comme à l'ingestion FTP (parse_articles._parse_article), pour que
        # le front rende le même « Résumé structuré » que le digest. `itertext()`
        # capte le balisage imbriqué (<i>, <sub>…) que `.text` perdrait.
        parts: list[str] = []
        for ab in art.findall(".//Abstract/AbstractText"):
            txt = "".join(ab.itertext()).strip()
            if not txt:
                continue
            label = ab.get("Label")
            parts.append(f"{label}: {txt}" if label else txt)
        abstract = "\n".join(parts).strip()
        if abstract:
            out[int(pmid_el.text)] = abstract
    return out
