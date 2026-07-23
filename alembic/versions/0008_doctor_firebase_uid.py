"""doctors.firebase_uid : rattache un médecin à son compte Google (Firebase)

Le compte connecté (vérifié par le proxy Next) est identifié par son UID
Firebase, stable même si l'email Google change. Colonne nullable : les
profils saisis à la main avant l'auth restent valides et sont rattachés
au premier passage sur /me/bootstrap (repli par email).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE doctors ADD COLUMN firebase_uid TEXT UNIQUE")


def downgrade() -> None:
    op.execute("ALTER TABLE doctors DROP COLUMN firebase_uid")
