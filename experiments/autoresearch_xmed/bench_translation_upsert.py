"""Microbenchmark du round 7 sur une table TEMP du clone isolé."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from experiments.autoresearch_xmed.run_live_baseline import _database_url

UPSERT = text(
    """
    INSERT INTO article_fr_round7 (pmid, title_fr, abstract_fr, updated_at)
    VALUES (:pmid, :t, :a, now())
    ON CONFLICT (pmid) DO UPDATE
      SET title_fr = EXCLUDED.title_fr,
          abstract_fr = EXCLUDED.abstract_fr,
          updated_at = now()
    """
)


def _once(session: Session, rows: list[dict], bulk: bool) -> float:
    session.execute(text("TRUNCATE article_fr_round7"))
    session.commit()
    started = time.perf_counter()
    if bulk:
        session.execute(UPSERT, rows)
    else:
        for row in rows:
            session.execute(UPSERT, row)
    session.commit()
    return time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if "autoresearch" not in args.database:
        raise SystemExit("REFUS: base non autoresearch")

    engine = create_engine(_database_url(args.database), pool_pre_ping=True)
    rows = [
        {"pmid": pmid, "t": f"Titre {pmid}", "a": "Résumé médical. " * 120} for pmid in range(1, 21)
    ]
    samples = {"loop": [], "bulk": []}
    with Session(engine) as session:
        session.execute(
            text(
                "CREATE TEMP TABLE article_fr_round7 ("
                "pmid BIGINT PRIMARY KEY, title_fr TEXT, abstract_fr TEXT, "
                "updated_at TIMESTAMPTZ NOT NULL) ON COMMIT PRESERVE ROWS"
            )
        )
        session.commit()
        for repeat in range(args.repeats):
            order = (False, True) if repeat % 2 == 0 else (True, False)
            for bulk in order:
                samples["bulk" if bulk else "loop"].append(_once(session, rows, bulk))
    engine.dispose()
    output = {
        "schema_version": 1,
        "database": args.database,
        "temporary_table_only": True,
        "repeats": args.repeats,
        "samples_s": samples,
        "median_s": {key: statistics.median(values) for key, values in samples.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["median_s"]))


if __name__ == "__main__":
    main()
