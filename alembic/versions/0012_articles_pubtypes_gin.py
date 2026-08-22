"""Index GIN sur articles.publication_types (recherche par type de document)

Sans cet index, isoler les recommandations de sociétés savantes du corpus
(`publication_types && ARRAY['Practice Guideline','Guideline']`) impose un scan
séquentiel des ~25 M de lignes / 30 Go de heap de `articles` : plusieurs minutes,
et surtout l'éviction du cache Postgres dont dépend la latence de `article_search`
(8 Go de `shared_buffers` déjà justes, cf. docker-compose.yml).

L'index rend possible le filtre « Recommandations » de la recherche, et plus
généralement tout filtre par `PublicationType` (RCT, méta-analyses…) que la
grille `evidence_level` seule ne sait pas exprimer.

⚠️ Création en CONCURRENTLY : pas de verrou d'écriture, donc le worker
d'ingestion nocturne peut continuer — mais la construction lit toute la table et
prend du temps sur 25 M de lignes. **À lancer hors de la fenêtre d'ingestion.**
En cas d'interruption, Postgres laisse un index INVALID : le DROP du downgrade
puis un nouvel upgrade repartent proprement.

Coût disque estimé : quelques centaines de Mo (tableaux courts, forte
répétition des valeurs → dictionnaire GIN compact).
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_articles_pubtypes "
            "ON articles USING gin (publication_types)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_articles_pubtypes")
