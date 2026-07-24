"""search_runs (recherches en arrière-plan + historique par utilisateur)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-24
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Une ligne par recherche lancée depuis la page d'accueil. Même modèle que
    # digest_runs : le run tourne dans un thread détaché de la requête HTTP,
    # le front polle — verrouiller son téléphone n'interrompt plus rien et le
    # résultat attend en base. Chaque run `complete` est une entrée de
    # l'historique de recherche du médecin (query + payload complets : c'est la
    # question que l'utilisateur a tapée, l'historique est fait pour la garder).
    op.execute(
        """
        CREATE TABLE search_runs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doctor_id   UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
            query       TEXT NOT NULL,
            date_from   DATE,
            date_to     DATE,
            params      JSONB NOT NULL DEFAULT '{}',
            status      TEXT NOT NULL DEFAULT 'running',
            logs        JSONB NOT NULL DEFAULT '[]',
            payload     JSONB,
            n_results   INTEGER NOT NULL DEFAULT 0,
            error       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            -- Heartbeat : touché à chaque jalon de progression (détection zombis).
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_search_runs_doctor_created "
        "ON search_runs (doctor_id, created_at DESC)"
    )
    # Une seule recherche active par médecin — index indépendant de celui du
    # digest : un digest et une recherche peuvent tourner en même temps.
    op.execute(
        "CREATE UNIQUE INDEX uq_search_runs_active ON search_runs (doctor_id) "
        "WHERE status IN ('running', 'translating')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_runs")
