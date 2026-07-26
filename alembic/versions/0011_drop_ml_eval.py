"""Retrait des chantiers abandonnés : embeddings, benchmark, évaluation

Trois chantiers des débuts du projet quittent la base (voir PLAN_NETTOYAGE.md) :

- `emb_bge_m3` (4,1 Go) et `emb_medcpt` (120 Mo) — le pré-tri sémantique par
  vecteurs, jugé peu cohérent face au filtre lexical suivi du jugement codex.
  La recherche v2 ne les lit pas.
- `bench_*` — le banc d'essai qui comparait ces mêmes modèles d'embedding.
- `eval_*` — le gold set d'annotation médecin, jamais démarré
  (`eval_annotations` : 0 ligne au moment du retrait).

L'extension `vector` part avec eux : plus aucune colonne ni aucun import Python
ne s'en sert.

CONSERVÉ : `article_fr`, le cache de traduction FR payé en tokens codex et lu
par la recherche en production. Seul son chargeur de test disparaît.

Archive prise avant application (410 lignes : eval_pool 400, bench_results 8,
bench_runs 2) — voir `archives/archive_eval_bench_<date>.sql`. Les tables
`emb_*` ne sont pas archivées : des vecteurs recalculables ne valent pas 4,2 Go
de sauvegarde.

Le downgrade recrée les structures vides, pas les données : c'est un filet pour
que la chaîne de migrations reste réversible, pas une restauration.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-26
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ordre : enfants d'abord (bench_qrels/bench_results portent des FK vers
    # bench_queries/bench_runs), puis les tables sans dépendance.
    op.execute("DROP TABLE IF EXISTS bench_results")
    op.execute("DROP TABLE IF EXISTS bench_qrels")
    op.execute("DROP TABLE IF EXISTS bench_runs")
    op.execute("DROP TABLE IF EXISTS bench_queries")

    op.execute("DROP TABLE IF EXISTS eval_annotations")
    op.execute("DROP TABLE IF EXISTS eval_pool")

    # 4,3 Go récupérés. Les index HNSW partent avec les tables.
    op.execute("DROP TABLE IF EXISTS emb_bge_m3")
    op.execute("DROP TABLE IF EXISTS emb_medcpt")

    # Plus aucune colonne `vector` : l'extension n'a plus de raison d'être.
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        "CREATE TABLE emb_medcpt (pmid BIGINT PRIMARY KEY "
        "REFERENCES articles(pmid) ON DELETE CASCADE, v vector(768))"
    )
    op.execute(
        "CREATE TABLE emb_bge_m3 (pmid BIGINT PRIMARY KEY "
        "REFERENCES articles(pmid) ON DELETE CASCADE, v vector(1024))"
    )

    # DDL repris tel quel de 0003_eval_annotation.py
    op.execute(
        """
        CREATE TABLE eval_pool (
            id        SERIAL PRIMARY KEY,
            query_id  INTEGER NOT NULL,
            theme     TEXT,
            query     TEXT NOT NULL,
            pmid      BIGINT NOT NULL,
            found_by  TEXT,
            UNIQUE (query_id, pmid)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE eval_annotations (
            query_id   INTEGER NOT NULL,
            pmid       BIGINT NOT NULL,
            grade      INTEGER NOT NULL CHECK (grade IN (0, 1, 2)),
            annotator  TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (query_id, pmid)
        )
        """
    )

    # DDL repris tel quel de 0001_initial_schema.py
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
