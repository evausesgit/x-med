-- Rôles LECTURE SEULE de la base corpus (x-med-db-1, base `xmed`).
--
-- ⚠️ À jouer à l'ÉTAPE 9 du chantier compose (PLAN_EXECUTION_COMPOSE.md),
-- PAS avant. Création/altération de rôles + GRANT/REVOKE : non destructif.
--
-- Usage (mots de passe passés en variables psql, jamais en dur ici) :
--   docker exec -i x-med-db-1 psql -U xmed -d xmed \
--     -v api_password='...' -v preview_password='...' \
--     -f - < scripts/create_corpus_roles.sql
--
-- Idempotent : rejouable — CREATE seulement si absent, ALTER/REVOKE/GRANT
-- toujours (rejouer le script réaligne mots de passe, timeouts et droits).
--
-- ⚠️ PAS de default privileges automatiques : toute future migration corpus
-- qui crée une table/fonction destinée à l'API devra porter ses GRANT
-- explicites vers ces rôles — sinon l'objet leur restera invisible.
--
-- Deux rôles :
--   xmed_api_ro     — l'API du compose app en production.
--                     statement_timeout 130s (> local_search_timeout_ms=120s
--                     de app/config.py : c'est Postgres côté requête applicative
--                     qui borne, ce rôle n'est que le filet), 20 connexions.
--   xmed_preview_ro — les previews de MR. Plus contraint : 60s, 15 connexions.
--
-- Périmètre : CONNECT sur xmed, USAGE sur public, SELECT sur les 4 tables
-- corpus, EXECUTE sur article_search_min_year() (routage du pré-filtre FTS).
-- Rien d'autre — pas de SELECT sur les tables backoffice résiduelles, et
-- default_transaction_read_only = on (ceinture en plus des GRANT).

\set ON_ERROR_STOP on

-- Création conditionnelle (CREATE ROLE n'a pas de IF NOT EXISTS).
SELECT 'CREATE ROLE xmed_api_ro NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'xmed_api_ro')
\gexec

SELECT 'CREATE ROLE xmed_preview_ro NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'xmed_preview_ro')
\gexec

-- Attributs (toujours rejoués : le script réaligne l'état). Tous les
-- attributs de cluster explicitement refusés.
ALTER ROLE xmed_api_ro LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 20
    PASSWORD :'api_password';
-- CONNECTION LIMIT preview : le pool SQLAlchemy par défaut de l'API fait
-- 5 connexions + 10 d'overflow = 15 possibles pour UN process API ; une
-- limite à 5 étranglerait la preview dès la première rafale. 15 = le pool
-- entier d'une preview, sans marge pour une seconde (assumé).
ALTER ROLE xmed_preview_ro LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 15
    PASSWORD :'preview_password';

ALTER ROLE xmed_api_ro SET statement_timeout = '130s';
ALTER ROLE xmed_preview_ro SET statement_timeout = '60s';

-- Ceinture read-only : même un GRANT d'écriture accordé par erreur plus tard
-- resterait inopérant tant que la session ne le désactive pas explicitement.
ALTER ROLE xmed_api_ro SET default_transaction_read_only = on;
ALTER ROLE xmed_preview_ro SET default_transaction_read_only = on;

-- Remise à zéro des privilèges : on retire tout ce qui aurait pu être
-- accordé (directement, ou hérité de PUBLIC pour les fonctions), puis on
-- ne re-grante QUE le périmètre prévu.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM xmed_api_ro, xmed_preview_ro;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM xmed_api_ro, xmed_preview_ro;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public
    FROM xmed_api_ro, xmed_preview_ro;
-- L'EXECUTE par défaut de PUBLIC sur les fonctions du schéma couvrirait ces
-- rôles malgré les REVOKE ciblés : on le retire (les rôles qui en ont besoin
-- recevront leur EXECUTE explicite, comme ci-dessous).
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

-- Accès : base + schéma.
GRANT CONNECT ON DATABASE xmed TO xmed_api_ro, xmed_preview_ro;
GRANT USAGE ON SCHEMA public TO xmed_api_ro, xmed_preview_ro;

-- Les 4 tables corpus — la frontière figée (rien côté backoffice).
GRANT SELECT ON public.articles,
                public.article_search,
                public.mesh_descriptors,
                public.ftp_state
TO xmed_api_ro, xmed_preview_ro;

-- Fenêtre de la table étroite FTS (migration 0006) : le routage du pré-filtre
-- l'interroge à chaque recherche.
GRANT EXECUTE ON FUNCTION public.article_search_min_year()
TO xmed_api_ro, xmed_preview_ro;
