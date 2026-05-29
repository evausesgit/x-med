"""schéma initial : articles, embeddings multi-modèles, benchmark

Revision ID: 0001
Revises:
Create Date: 2026-05-29
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Articles (métadonnées PubMed) ---
    op.execute(
        """
        CREATE TABLE articles (
            pmid              BIGINT PRIMARY KEY,
            title             TEXT NOT NULL,
            abstract          TEXT,
            authors           JSONB,
            journal           TEXT,
            issn              TEXT,
            pub_date          DATE,
            pub_year          INTEGER,
            mesh_terms        TEXT[],
            doi               TEXT,
            pmc_id            TEXT,
            publication_types TEXT[],
            evidence_level    INTEGER,
            fts               tsvector GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,''))
            ) STORED,
            ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_articles_fts ON articles USING gin (fts)")
    op.execute("CREATE INDEX ix_articles_mesh ON articles USING gin (mesh_terms)")
    op.execute("CREATE INDEX ix_articles_pub_year ON articles (pub_year)")

    # --- Descripteurs MeSH (autocomplétion) ---
    op.execute(
        """
        CREATE TABLE mesh_descriptors (
            ui   TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_mesh_name_trgm ON mesh_descriptors (lower(name) text_pattern_ops)")

    # --- Suivi des fichiers ingérés ---
    op.execute(
        """
        CREATE TABLE ftp_state (
            filename      TEXT PRIMARY KEY,
            checksum      TEXT,
            article_count INTEGER,
            downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # --- Embeddings : une table par modèle (dimension fixe par table) ---
    # Les index HNSW sont créés à l'étape C, après peuplement (build plus rapide).
    op.execute(
        "CREATE TABLE emb_medcpt (pmid BIGINT PRIMARY KEY REFERENCES articles(pmid) ON DELETE CASCADE, v vector(768))"
    )
    op.execute(
        "CREATE TABLE emb_bge_m3 (pmid BIGINT PRIMARY KEY REFERENCES articles(pmid) ON DELETE CASCADE, v vector(1024))"
    )

    # --- Benchmark ---
    op.execute(
        """
        CREATE TABLE bench_queries (
            id      SERIAL PRIMARY KEY,
            dataset TEXT NOT NULL,
            text    TEXT NOT NULL,
            lang    TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bench_qrels (
            query_id  INTEGER NOT NULL REFERENCES bench_queries(id) ON DELETE CASCADE,
            pmid      BIGINT NOT NULL,
            relevance INTEGER NOT NULL,
            PRIMARY KEY (query_id, pmid)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bench_runs (
            id         SERIAL PRIMARY KEY,
            model_name TEXT NOT NULL,
            dataset    TEXT NOT NULL,
            params     JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bench_results (
            run_id INTEGER NOT NULL REFERENCES bench_runs(id) ON DELETE CASCADE,
            metric TEXT NOT NULL,
            value  DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (run_id, metric)
        )
        """
    )


def downgrade() -> None:
    for tbl in (
        "bench_results",
        "bench_runs",
        "bench_qrels",
        "bench_queries",
        "emb_bge_m3",
        "emb_medcpt",
        "ftp_state",
        "mesh_descriptors",
        "articles",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
