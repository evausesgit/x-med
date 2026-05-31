"""pool d'évaluation + annotations in-site (gold set FR)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-31
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Candidats à juger (produit par scripts.build_pool : union des méthodes)
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
    # Jugements de pertinence (0/1/2) saisis par les médecins via la page /annotate
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_annotations")
    op.execute("DROP TABLE IF EXISTS eval_pool")
