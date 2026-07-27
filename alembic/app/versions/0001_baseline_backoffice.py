"""Baseline backoffice — les 7 tables métier, squashées en une révision.

Revision ID: app0001
Revises:
Create Date: 2026-07-27

Reproduit EXACTEMENT le schéma backoffice extrait de la prod le 2026-07-27
(pg_dump --schema-only des 7 tables) : colonnes, defaults, contraintes, FK,
index — y compris les index uniques partiels « un seul run actif par médecin ».

Baseline SQUASHÉE : elle remplace, pour la base app, les révisions 0001→0011 de
l'historique monolithique. Ne JAMAIS jouer l'historique monolithique (`alembic/`,
table `alembic_version`) sur une base app — il créerait les tables corpus
(articles, article_search, …) et des tables abandonnées. Cet historique-ci
versionne dans `alembic_version_app` (voir alembic/app/env.py).
"""

from alembic import op

revision = "app0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schéma `public` épinglé : une URL portant des options de search_path ne
    # doit pas pouvoir créer les tables ailleurs (le backup ne sonde que public).
    op.execute("SET search_path TO public")

    # Médecins — le pivot : toutes les autres tables (sauf article_fr et
    # usage_events) s'y rattachent par FK.
    op.execute(
        """
        CREATE TABLE doctors (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email            TEXT NOT NULL UNIQUE,
            name             TEXT NOT NULL,
            language         TEXT NOT NULL DEFAULT 'fr',
            digest_frequency TEXT NOT NULL DEFAULT 'daily',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            firebase_uid     TEXT UNIQUE
        )
        """
    )

    # Profil de veille (1-1 avec doctors) : la matière du pré-filtre et du
    # prompt de scoring.
    op.execute(
        """
        CREATE TABLE doctor_profiles (
            doctor_id          UUID PRIMARY KEY REFERENCES doctors(id) ON DELETE CASCADE,
            specialty_main     TEXT NOT NULL,
            subspecialties     TEXT[] NOT NULL DEFAULT '{}',
            pathologies        TEXT[] NOT NULL DEFAULT '{}',
            treatments         TEXT[] NOT NULL DEFAULT '{}',
            study_types        TEXT[] NOT NULL DEFAULT '{}',
            min_evidence_level INTEGER,
            preferred_journals TEXT[] NOT NULL DEFAULT '{}',
            mesh_terms_extra   TEXT[] NOT NULL DEFAULT '{}',
            keywords_extra     TEXT[] NOT NULL DEFAULT '{}',
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Recherches sauvegardées (payload complet pour ré-affichage). doctor_id
    # nullable + SET NULL : la sauvegarde survit à la suppression du compte.
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

    # Recherches en arrière-plan + historique par utilisateur (cf. monolithe 0010).
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
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_search_runs_doctor_created "
        "ON search_runs (doctor_id, created_at DESC)"
    )
    # Une seule recherche active par médecin.
    op.execute(
        "CREATE UNIQUE INDEX uq_search_runs_active ON search_runs (doctor_id) "
        "WHERE status IN ('running', 'translating')"
    )

    # Digests à la demande (cf. monolithe 0009) — même modèle de run que
    # search_runs, index d'activité indépendant (un digest et une recherche
    # peuvent tourner en même temps).
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
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_digest_runs_doctor_date "
        "ON digest_runs (doctor_id, digest_date DESC, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_digest_runs_active ON digest_runs (doctor_id) "
        "WHERE status IN ('running', 'translating')"
    )

    # Journal d'usage (audit minimal, pas de FK : survit à tout).
    # BIGSERIAL crée la séquence usage_events_id_seq (OWNED BY), comme en prod.
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
    op.execute("CREATE INDEX ix_usage_events_created ON usage_events (created_at DESC)")
    op.execute(
        "CREATE INDEX ix_usage_events_email_created "
        "ON usage_events (email, created_at DESC)"
    )

    # Cache de traduction FR des articles (pmid = clé PubMed, pas de FK : le
    # corpus vit dans une autre base).
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
    # Même épinglage de schéma qu'à l'upgrade.
    op.execute("SET search_path TO public")

    # Ordre inverse des FK : les tables qui référencent doctors d'abord.
    op.execute("DROP TABLE IF EXISTS article_fr")
    op.execute("DROP TABLE IF EXISTS usage_events")
    op.execute("DROP TABLE IF EXISTS digest_runs")
    op.execute("DROP TABLE IF EXISTS search_runs")
    op.execute("DROP TABLE IF EXISTS saved_searches")
    op.execute("DROP TABLE IF EXISTS doctor_profiles")
    op.execute("DROP TABLE IF EXISTS doctors")
