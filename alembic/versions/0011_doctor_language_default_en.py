"""doctors.language : l'anglais devient la langue par défaut

L'interface est bilingue (anglais principal, français au choix) et la langue
du compte pilote à la fois l'interface et la traduction automatique des
articles. Les NOUVEAUX comptes démarrent donc en anglais.

Les comptes existants ne sont PAS touchés : ils gardent le français, choisi
(implicitement) quand le produit était francophone. Personne ne voit son
interface changer de langue du jour au lendemain ; chacun bascule quand il
veut depuis la barre de navigation ou sa page profil.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-25
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE doctors ALTER COLUMN language SET DEFAULT 'en'")


def downgrade() -> None:
    op.execute("ALTER TABLE doctors ALTER COLUMN language SET DEFAULT 'fr'")
