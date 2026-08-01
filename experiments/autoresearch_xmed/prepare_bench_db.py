"""Construit un corpus PostgreSQL isolé, récent ou complet, pour autoresearch.

La source est ouverte avec `default_transaction_read_only=on`. La destination doit
avoir un nom contenant `autoresearch` et être vide. Le transfert utilise COPY binaire
entre deux connexions : aucune extension ni objet n'est créé dans la source. Le mode
`full` projette les seules colonnes utiles mais conserve les ~25 M de lignes.
"""

from __future__ import annotations

import argparse
import time
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings

ARTICLE_COLUMNS = (
    "pmid, title, abstract, authors, journal, issn, pub_date, pub_year, mesh_terms, "
    "doi, pmc_id, publication_types, evidence_level, fts, ingested_at"
)

CREATE_ARTICLES = """
CREATE TABLE articles (
    pmid BIGINT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    authors JSONB,
    journal TEXT,
    issn TEXT,
    pub_date DATE,
    pub_year INTEGER,
    mesh_terms TEXT[],
    doi TEXT,
    pmc_id TEXT,
    publication_types TEXT[],
    evidence_level INTEGER,
    fts TSVECTOR,
    ingested_at TIMESTAMPTZ
)
"""


def _destination_url(database: str) -> str:
    return (
        make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)
    )


def _copy_articles(source_engine, destination_engine, scope: str) -> tuple[int, float, int]:
    source = source_engine.raw_connection()
    destination = destination_engine.raw_connection()
    started = time.monotonic()
    transferred = 0
    next_report = 1024**3
    try:
        with source.cursor() as source_cursor, destination.cursor() as destination_cursor:
            # Snapshot stable même si une ingestion se produit pendant le long
            # transfert du corpus complet.
            source_cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            # Les champs ci-dessous existent dans le modèle ORM mais ne sont jamais
            # lus par la recherche profonde. Les remplacer par des NULL typés évite
            # plusieurs Gio de transfert sans modifier les prompts ni les résultats.
            projection = """
                a.pmid, a.title, a.abstract, NULL::jsonb, a.journal,
                NULL::text, a.pub_date, a.pub_year, NULL::text[], a.doi,
                NULL::text, NULL::text[], a.evidence_level, a.fts, a.ingested_at
            """
            if scope == "recent":
                # Le vivier étroit définit exactement le snapshot récent.
                source_cursor.execute("SET enable_hashjoin=off")
                source_cursor.execute("SET enable_mergejoin=off")
                select_sql = (
                    f"SELECT {projection} FROM article_search s "
                    "JOIN articles a ON a.pmid = s.pmid ORDER BY s.pmid"
                )
            else:
                # Un scan séquentiel est préférable pour les ~25 M lignes complètes.
                select_sql = f"SELECT {projection} FROM articles a"
            with (
                source_cursor.copy(f"COPY ({select_sql}) TO STDOUT (FORMAT BINARY)") as outgoing,
                destination_cursor.copy(
                    f"COPY articles ({ARTICLE_COLUMNS}) FROM STDIN (FORMAT BINARY)"
                ) as incoming,
            ):
                for block in outgoing:
                    incoming.write(block)
                    transferred += len(block)
                    if transferred >= next_report:
                        print(f"transféré: {transferred / 1024**3:.1f} Gio", flush=True)
                        next_report += 1024**3
            # Psycopg expose le nombre exact de lignes du COPY TO dans rowcount :
            # cela évite un second scan complet des ~25 M de lignes.
            source_count = int(source_cursor.rowcount)
        destination.commit()
        source.rollback()
    except BaseException:
        # Inclut KeyboardInterrupt : sans ce rollback explicite, le backend COPY
        # peut rester en attente de ClientRead et bloquer le nettoyage du clone.
        destination.rollback()
        source.rollback()
        raise
    finally:
        destination.close()
        source.close()
    return transferred, time.monotonic() - started, source_count


def prepare(database: str, scope: str = "recent") -> None:
    if "autoresearch" not in database:
        raise ValueError("le nom de destination doit contenir 'autoresearch'")
    if scope not in {"recent", "full"}:
        raise ValueError("scope doit valoir 'recent' ou 'full'")
    source_url = settings.corpus_database_url or settings.database_url
    if urlsplit(source_url).path.lstrip("/") == database:
        raise ValueError("source et destination identiques")
    source_engine = create_engine(
        source_url,
        connect_args={"options": "-c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )
    destination_engine = create_engine(_destination_url(database), pool_pre_ping=True)

    with source_engine.connect() as source:
        if source.scalar(text("SHOW default_transaction_read_only")) != "on":
            raise RuntimeError("la connexion source n'est pas read-only")
        source_database = source.scalar(text("SELECT current_database()"))
        source_min_year = int(source.scalar(text("SELECT article_search_min_year()")))
    with destination_engine.begin() as destination:
        destination_database = destination.scalar(text("SELECT current_database()"))
        if destination_database != database:
            raise RuntimeError("mauvaise base destination")
        exists = destination.scalar(text("SELECT to_regclass('public.articles')"))
        if exists:
            rows = int(destination.scalar(text("SELECT count(*) FROM articles")))
            if rows:
                raise RuntimeError(f"destination non vide : {rows} articles présents")
        else:
            destination.execute(text(CREATE_ARTICLES))
            destination.execute(
                text(
                    "CREATE TABLE article_fr (pmid BIGINT PRIMARY KEY, title_fr TEXT, "
                    "abstract_fr TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            destination.execute(
                text("CREATE TABLE autoresearch_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            )
            destination.execute(
                text(
                    "INSERT INTO autoresearch_meta (key, value) VALUES "
                    "('scope', :scope), ('source_database', :source_database), "
                    "('source_min_year', :source_min_year)"
                ),
                {
                    "scope": scope,
                    "source_database": source_database,
                    "source_min_year": str(source_min_year),
                },
            )
    print(f"source={source_database} scope={scope}", flush=True)
    transferred, elapsed, source_count = _copy_articles(source_engine, destination_engine, scope)
    print(f"snapshot={source_count:,} lignes", flush=True)
    print(f"COPY terminé: {transferred / 1024**3:.1f} Gio en {elapsed:.1f}s", flush=True)

    with destination_engine.begin() as destination:
        destination.execute(text("SET LOCAL maintenance_work_mem='1GB'"))
        destination.execute(text("ALTER TABLE articles ADD PRIMARY KEY (pmid)"))
        destination.execute(text("CREATE INDEX ix_articles_fts ON articles USING gin (fts)"))
        destination.execute(text("CREATE INDEX ix_articles_year ON articles (pub_year)"))
        article_search_where = "" if scope == "recent" else f" WHERE pub_year >= {source_min_year}"
        destination.execute(
            text(
                "CREATE TABLE article_search AS "
                f"SELECT pmid, pub_year, fts FROM articles{article_search_where}"
            )
        )
        destination.execute(text("ALTER TABLE article_search ADD PRIMARY KEY (pmid)"))
        destination.execute(
            text("CREATE INDEX ix_article_search_fts ON article_search USING gin (fts)")
        )
        destination.execute(
            text("CREATE INDEX ix_article_search_year ON article_search (pub_year)")
        )
        destination.execute(
            text(
                "CREATE FUNCTION article_search_min_year() RETURNS integer "
                f"LANGUAGE sql IMMUTABLE AS $$ SELECT {source_min_year} $$"
            )
        )
        destination.execute(text("ANALYZE articles"))
        destination.execute(text("ANALYZE article_search"))
        destination_count = int(destination.scalar(text("SELECT count(*) FROM articles")))
        if destination_count != source_count:
            raise RuntimeError(
                f"copie incomplète: source={source_count}, destination={destination_count}"
            )
        destination.execute(
            text(
                "INSERT INTO autoresearch_meta (key, value) VALUES "
                "('snapshot_rows', :rows), ('prepared', 'true') "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
            ),
            {"rows": str(destination_count)},
        )
    source_engine.dispose()
    destination_engine.dispose()
    print(f"OK: {database} contient {destination_count:,} articles récents")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="xmed_autoresearch")
    parser.add_argument("--scope", choices=("recent", "full"), default="recent")
    args = parser.parse_args()
    prepare(args.database, args.scope)


if __name__ == "__main__":
    main()
