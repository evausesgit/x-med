"""médecins + profil détaillé (digest personnalisé)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE doctors (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email            TEXT NOT NULL UNIQUE,
            name             TEXT NOT NULL,
            language         TEXT NOT NULL DEFAULT 'fr',
            digest_frequency TEXT NOT NULL DEFAULT 'daily',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE doctor_profiles (
            doctor_id           UUID PRIMARY KEY REFERENCES doctors(id) ON DELETE CASCADE,
            specialty_main      TEXT NOT NULL,
            subspecialties      TEXT[] NOT NULL DEFAULT '{}',
            pathologies         TEXT[] NOT NULL DEFAULT '{}',
            treatments          TEXT[] NOT NULL DEFAULT '{}',
            study_types         TEXT[] NOT NULL DEFAULT '{}',
            min_evidence_level  INTEGER,
            preferred_journals  TEXT[] NOT NULL DEFAULT '{}',
            mesh_terms_extra    TEXT[] NOT NULL DEFAULT '{}',
            keywords_extra      TEXT[] NOT NULL DEFAULT '{}',
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS doctor_profiles")
    op.execute("DROP TABLE IF EXISTS doctors")
