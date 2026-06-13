"""traductions FR des articles (titre + résumé) pour l'annotation

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-13
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Traductions françaises générées pour faciliter l'annotation des médecins
    # sur /annotate (les abstracts PubMed sont en anglais). Table séparée pour ne
    # pas alourdir `articles` : seuls les articles du pool d'éval y sont traduits.
    op.execute(
        """
        CREATE TABLE article_fr (
            pmid        BIGINT PRIMARY KEY,
            title_fr    TEXT,
            abstract_fr TEXT,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS article_fr")
