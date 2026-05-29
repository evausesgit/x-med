"""Chargement des jeux de benchmark.

- NFCorpus (BEIR, via ir_datasets) : corpus médical dérivé de PubMed, requêtes
  en langage naturel + jugements de pertinence (qrels). Standard, reproductible.
- Gold set FR interne : requêtes en français + PMIDs pertinents (à annoter),
  chargé depuis bench/gold_fr.json s'il existe.
"""

from __future__ import annotations

import json
from pathlib import Path

# Structures renvoyées :
#   docs   : dict[doc_id -> texte]
#   queries: dict[query_id -> texte]
#   qrels  : dict[query_id -> dict[doc_id -> pertinence(int)]]


def load_nfcorpus(max_docs: int | None = None) -> tuple[dict, dict, dict]:
    import ir_datasets

    ds = ir_datasets.load("beir/nfcorpus/test")

    docs: dict[str, str] = {}
    for d in ds.docs_iter():
        title = getattr(d, "title", "") or ""
        body = getattr(d, "text", "") or ""
        docs[d.doc_id] = (title + "\n" + body).strip()
        if max_docs and len(docs) >= max_docs:
            break

    queries = {q.query_id: q.text for q in ds.queries_iter()}

    qrels: dict[str, dict[str, int]] = {}
    for qr in ds.qrels_iter():
        if qr.doc_id in docs:
            qrels.setdefault(qr.query_id, {})[qr.doc_id] = int(qr.relevance)

    # On ne garde que les requêtes ayant au moins un doc pertinent présent
    queries = {qid: t for qid, t in queries.items() if qrels.get(qid)}
    return docs, queries, qrels


def load_gold_fr() -> tuple[dict, dict, dict] | None:
    """Gold set FR : bench/gold_fr.json = [{id, query, relevant:[pmid,…]}].

    Les 'docs' sont des PMIDs de NOTRE corpus → le runner les résout via la base.
    Renvoie None si le fichier n'existe pas encore.
    """
    path = Path(__file__).parent / "gold_fr.json"
    if not path.exists():
        return None
    items = json.loads(path.read_text())
    queries = {str(it["id"]): it["query"] for it in items}
    qrels = {str(it["id"]): {str(p): 1 for p in it["relevant"]} for it in items}
    return {}, queries, qrels  # docs vide : corpus = base PubMed
