"""table étroite `article_search` (miroir FTS récent, fenêtre glissante)

Rend le pré-filtre plein-texte du pipeline PubMed rapide en permanence : au lieu de
trier `ts_rank` sur les 25 M lignes / 63 Go de `articles` (jusqu'à ~150 s à froid,
car les tsvectors relus depuis le heap ne tiennent pas en cache), on ne garde qu'une
fenêtre glissante des dernières années (~3,4 M lignes / ~7 Go) qui reste chaude en
RAM → ~0,4 s, classement `ts_rank` identique.

Cette migration crée UNIQUEMENT le schéma + la mécanique de maintenance (rapide et
sûre à jouer à chaque déploiement). Le **remplissage initial** (~20 min de lecture
sur `articles`) est volontairement hors migration : voir scripts/backfill_article_search.py,
à lancer une fois, puis activer `USE_NARROW_SEARCH=true`.

Maintenance automatique ensuite :
- entrée : trigger `trg_article_search_sync` sur `articles` (upsert des articles récents) ;
- sortie : `article_search_prune()` (tâche planifiée) supprime la queue hors fenêtre.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-05
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FK ON DELETE CASCADE : les suppressions PubMed (tasks/parse_articles.py fait
    # `DELETE FROM articles`) se propagent au miroir. Sans ça, des PMID fantômes
    # traîneraient dans article_search et grignoteraient les places du `LIMIT max_local`.
    op.execute(
        """
        CREATE TABLE article_search (
            pmid     BIGINT PRIMARY KEY REFERENCES articles(pmid) ON DELETE CASCADE,
            pub_year INTEGER,
            fts      TSVECTOR
        )
        """
    )
    op.execute("CREATE INDEX ix_article_search_fts ON article_search USING gin (fts)")
    op.execute("CREATE INDEX ix_article_search_year ON article_search (pub_year)")

    # Borne basse de la fenêtre glissante, source de vérité UNIQUE partagée par le
    # trigger et le prune. STABLE (pas IMMUTABLE) car dépend de now(). Le « - 2 »
    # garde 3 années civiles (courante + 2 précédentes) ; changer cette valeur =
    # changer la largeur de la fenêtre (garder cohérent avec settings.narrow_search_years).
    op.execute(
        """
        CREATE FUNCTION article_search_min_year() RETURNS integer
            LANGUAGE sql STABLE
            AS $$ SELECT extract(year from now())::int - 2 $$
        """
    )

    # Entrée : chaque upsert dans `articles` (voir tasks/parse_articles.py) se
    # répercute sur `article_search` si l'article est dans la fenêtre. AFTER trigger,
    # coût négligeable sur le batch quotidien (~15-20 k lignes/jour).
    op.execute(
        """
        CREATE FUNCTION article_search_sync() RETURNS trigger
            LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.pub_year IS NOT NULL AND NEW.pub_year >= article_search_min_year() THEN
                INSERT INTO article_search (pmid, pub_year, fts)
                VALUES (NEW.pmid, NEW.pub_year, NEW.fts)
                ON CONFLICT (pmid) DO UPDATE
                    SET pub_year = EXCLUDED.pub_year, fts = EXCLUDED.fts
                    -- Ne réécrit (WAL + index) que si quelque chose a changé : une
                    -- ré-ingestion à l'identique d'un article ne touche pas le miroir.
                    WHERE article_search.pub_year IS DISTINCT FROM EXCLUDED.pub_year
                       OR article_search.fts      IS DISTINCT FROM EXCLUDED.fts;
            ELSE
                -- L'article sort de la fenêtre (pub_year corrigé vers une année
                -- ancienne ou NULL) : retirer une éventuelle ligne périmée, sinon
                -- une recherche récente la remonterait avec un pub_year faux.
                DELETE FROM article_search WHERE pmid = NEW.pmid;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_article_search_sync
            AFTER INSERT OR UPDATE ON articles
            FOR EACH ROW EXECUTE FUNCTION article_search_sync()
        """
    )

    # Sortie : supprime les articles sortis de la fenêtre (quand l'année avance).
    # Renvoie le nombre de lignes purgées. Appelé par une tâche planifiée mensuelle
    # (scripts/prune_article_search.py). Sans ça, la table grossirait indéfiniment.
    op.execute(
        """
        CREATE FUNCTION article_search_prune() RETURNS bigint
            LANGUAGE plpgsql AS $$
        DECLARE n bigint;
        BEGIN
            DELETE FROM article_search WHERE pub_year < article_search_min_year();
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_article_search_sync ON articles")
    op.execute("DROP FUNCTION IF EXISTS article_search_sync()")
    op.execute("DROP FUNCTION IF EXISTS article_search_prune()")
    op.execute("DROP FUNCTION IF EXISTS article_search_min_year()")
    op.execute("DROP TABLE IF EXISTS article_search")
