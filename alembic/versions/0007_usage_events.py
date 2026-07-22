"""table usage_events : journal « quel compte fait quelle recherche »

L'email (compte Google vérifié par le proxy Next, header X-User-Email) est
journalisé avec l'action, le texte de recherche et les paramètres. Consultation
en SQL, ex. : SELECT email, query, created_at FROM usage_events
ORDER BY created_at DESC LIMIT 50;

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-22
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE usage_events (
            id         BIGSERIAL PRIMARY KEY,
            email      TEXT,
            action     TEXT NOT NULL,
            query      TEXT,
            params     JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Les deux lectures attendues : « qu'a fait tel compte » et « quoi de neuf ».
    op.execute(
        "CREATE INDEX ix_usage_events_email_created ON usage_events (email, created_at DESC)"
    )
    op.execute("CREATE INDEX ix_usage_events_created ON usage_events (created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE usage_events")
