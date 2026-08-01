"""Cache TTL exact de PubMed esearch, réservé aux expériences."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from app.services.pubmed_eutils import esearch

Search = Callable[..., tuple[int, list[int]]]


def _key(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def search_cached(
    term: str,
    cache_dir: Path,
    *,
    retmax: int = 20,
    sort: str = "relevance",
    mindate: str | None = None,
    maxdate: str | None = None,
    ttl_s: float = 300,
    search: Search = esearch,
) -> tuple[int, list[int], bool]:
    params = {
        "term": term,
        "retmax": retmax,
        "sort": sort,
        "mindate": mindate,
        "maxdate": maxdate,
    }
    key = _key(params)
    path = cache_dir / f"{key}.json"
    now = time.time()
    if path.exists():
        payload = json.loads(path.read_text())
        age = now - float(payload.get("fetched_at", 0))
        if payload.get("key") == key and 0 <= age <= ttl_s:
            return int(payload["total"]), [int(pmid) for pmid in payload["pmids"]], True

    total, pmids = search(
        term,
        retmax=retmax,
        sort=sort,
        mindate=mindate,
        maxdate=maxdate,
    )
    payload = {
        "schema_version": 1,
        "key": key,
        "fetched_at": now,
        "total": total,
        "pmids": pmids,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=cache_dir)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return int(total), [int(pmid) for pmid in pmids], False
