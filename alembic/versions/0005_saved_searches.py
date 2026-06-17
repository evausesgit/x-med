"""recherches sauvegardées (snapshot d'un résultat associé à un profil)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-17
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Snapshot d'une recherche (requête + résultats) pour la relire/réutiliser
    # sans relancer codex. `payload` = réponse complète (forme DeepSearchResponse).
    # doctor_id ON DELETE SET NULL : la recherche survit à la suppression du profil.
    op.execute(
        """
        CREATE TABLE saved_searches (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doctor_id  UUID REFERENCES doctors(id) ON DELETE SET NULL,
            query      TEXT NOT NULL,
            method     TEXT NOT NULL DEFAULT 'v2',
            params     JSONB,
            payload    JSONB NOT NULL,
            n_results  INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_saved_searches_created_at ON saved_searches (created_at DESC)"
    )
    op.execute("CREATE INDEX ix_saved_searches_doctor ON saved_searches (doctor_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_searches")
