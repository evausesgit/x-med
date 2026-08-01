"""Compare `articles` et `article_search` en lecture seule.

Ce micro-benchmark isole le round « table FTS étroite ». Il reprend les expansions
de requête déjà archivées pour ne déclencher ni Codex ni PubMed. La connexion force
`default_transaction_read_only=on` et le script refuse de continuer si PostgreSQL ne
le confirme pas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import settings


def _safe_db_identity(url: str) -> dict:
    parsed = urlsplit(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
    }


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    cases = []
    for index, row in enumerate(data.get("queries", []), 1):
        baseline = row.get("v1", {})
        keywords = baseline.get("keywords_en") or []
        if keywords:
            cases.append(
                {
                    "id": f"legacy-{index:02d}",
                    "query": row["query"],
                    "terms": " OR ".join(keywords),
                    "date_from": data["window"].get("from"),
                    "date_to": data["window"].get("to"),
                }
            )
    if not cases:
        raise ValueError(f"aucune expansion keywords_en dans {path}")
    return cases


def _year(value: str | None) -> int | None:
    return int(value[:4]) if value else None


def _run_query(connection, table: str, case: dict, limit: int, timeout_ms: int) -> dict:
    clauses = ["fts @@ websearch_to_tsquery('english', :terms)"]
    params = {"terms": case["terms"], "limit": limit}
    if year := _year(case.get("date_from")):
        clauses.append("pub_year >= :year_from")
        params["year_from"] = year
    if year := _year(case.get("date_to")):
        clauses.append("pub_year <= :year_to")
        params["year_to"] = year
    query = text(
        f"SELECT pmid FROM {table} WHERE {' AND '.join(clauses)} "  # noqa: S608
        "ORDER BY ts_rank(fts, websearch_to_tsquery('english', :terms)) DESC "
        "LIMIT :limit"
    )
    started = time.monotonic()
    try:
        connection.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
        pmids = [int(row[0]) for row in connection.execute(query, params)]
        connection.commit()
        return {"elapsed_s": time.monotonic() - started, "timeout": False, "pmids": pmids}
    except DBAPIError as exc:
        connection.rollback()
        message = str(exc).lower()
        if "statement timeout" not in message:
            raise
        return {"elapsed_s": time.monotonic() - started, "timeout": True, "pmids": []}


def run(fixture: Path, limit: int, timeout_ms: int) -> dict:
    source_url = settings.corpus_database_url or settings.database_url
    engine = create_engine(
        source_url,
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    cases = _load_cases(fixture)
    rows = []
    with engine.connect() as connection:
        read_only = connection.scalar(text("SHOW default_transaction_read_only"))
        if read_only != "on":
            raise RuntimeError("connexion corpus non read-only; benchmark refusé")
        min_year = int(connection.scalar(text("SELECT article_search_min_year()")))
        connection.commit()
        for case in cases:
            full = _run_query(connection, "articles", case, limit, timeout_ms)
            narrow = _run_query(connection, "article_search", case, limit, timeout_ms)
            comparable = not full["timeout"] and not narrow["timeout"]
            rows.append(
                {
                    "id": case["id"],
                    "query": case["query"],
                    "full": full,
                    "narrow": narrow,
                    "exact_topk": comparable and full["pmids"] == narrow["pmids"],
                    "comparable": comparable,
                }
            )
    engine.dispose()
    return {
        "schema_version": 1,
        "experiment": "article_search parity and latency",
        "database": _safe_db_identity(source_url),
        "read_only": True,
        "fixture": str(fixture),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "limit": limit,
        "timeout_ms": timeout_ms,
        "article_search_min_year": min_year,
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("bench/v1_v2/results.json"))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.fixture, args.limit, args.timeout_ms)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for row in result["cases"]:
        full, narrow = row["full"], row["narrow"]
        print(
            f"{row['id']} full={full['elapsed_s']:.2f}s"
            f"{' timeout' if full['timeout'] else ''} "
            f"narrow={narrow['elapsed_s']:.2f}s"
            f"{' timeout' if narrow['timeout'] else ''} "
            f"exact={row['exact_topk'] if row['comparable'] else 'n/a'}"
        )


if __name__ == "__main__":
    main()
