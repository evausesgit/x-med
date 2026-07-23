"""digest_runs (générations de digest en arrière-plan + historique par jour)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-23
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Une ligne par génération de digest. Le digest « officiel » d'une journée
    # est le dernier run `complete` de cette digest_date (une régénération le
    # remplace donc sans effacer l'audit des tentatives échouées/arrêtées).
    # doctor_id ON DELETE CASCADE : le digest est personnel, il n'a aucun sens
    # sans son médecin (contrairement aux saved_searches, partagées).
    op.execute(
        """
        CREATE TABLE digest_runs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doctor_id   UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
            digest_date DATE NOT NULL,
            days        INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'running',
            logs        JSONB NOT NULL DEFAULT '[]',
            payload     JSONB,
            n_results   INTEGER NOT NULL DEFAULT 0,
            error       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            -- Heartbeat : touché à chaque jalon de progression. C'est LUI (pas
            -- created_at) qui sert à détecter les runs zombis.
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_digest_runs_doctor_date "
        "ON digest_runs (doctor_id, digest_date DESC, created_at DESC)"
    )
    # Exclusivité garantie par la base (pas par un SELECT puis INSERT, sujet aux
    # courses) : un seul run actif à la fois par médecin.
    op.execute(
        "CREATE UNIQUE INDEX uq_digest_runs_active ON digest_runs (doctor_id) "
        "WHERE status IN ('running', 'translating')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS digest_runs")
