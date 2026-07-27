# Exécution — compose unifié (front + API + db backoffice) & previews de MR

> **Document de suivi vivant.** Mis à jour à chaque étape livrée. Le plan de fond est
> [`docs/plans/2026-07-24-infra-deux-composes-previews.md`](docs/plans/2026-07-24-infra-deux-composes-previews.md)
> (co-élaboré Claude + Codex) ; ce fichier trace ce qui est FAIT et ce qui RESTE.
>
> Méthode : une PR par étape, revue croisée Codex avant chaque merge, tests verts à
> chaque commit (`uv run --group dev pytest -q` + `cd web && npm run build`).

## Décisions figées (ne pas rediscuter sans l'utilisateur)

- **Jamais d'écriture destructive sur `x-med-db-1`** — ni pendant, ni après la bascule.
  Les 7 tables backoffice y resteront inertes une fois la nouvelle base app en service.
- **`x-med-db-1` devient la base corpus AS-IS** — sa conteneurisation Coolify est
  reportée (phase ultérieure, hors périmètre de ce chantier).
- **Previews : volume par-PR + re-seed à chaque déploiement.** Un compose unique ne
  peut pas conditionner un mount par environnement ; Coolify suffixe les volumes par
  PR (vérifié sur cet hôte) et les détruit avec la MR. L'init drop/recrée + re-seed la
  base à chaque déploiement de preview → données jetables de fait.
- **Réseau : rien d'exposé.** Aucun `ports:` dans le compose app ; seul `web` a un
  domaine ; l'API n'existe que comme `http://api:8800` interne. Accès corpus via un
  réseau Docker externe dédié (`xmed-corpus-access`) puis suppression du `5432:5432`.
- **Pas de Redis, pas de Resend** dans le compose : vérifié inutilisés dans le code
  (commentaires seulement). À réintroduire le jour où un vrai usage existe.
- **npm (pas bun)** pour le Dockerfile web — changement d'outillage hors migration.
- **Bascule prod (étape 10) supervisée par l'utilisateur**, jamais en autonome.

## Sauvegarde de référence

`~/backups/xmed/backoffice_2026-07-27_1128.dump` — pg_dump -Fc des 7 tables
backoffice, vérifié (`pg_restore --list`, comptes : 3 doctors, 43 saved_searches,
948 article_fr). Fait AVANT tout changement de code.

## Les étapes

| # | Étape | État | Réf |
|---|---|---|---|
| 1 | Frontière figée + backup + rôles SQL | 🔶 backup fait, rôles à créer | dump ci-dessus |
| 2 | Split runtime : deux moteurs, sessions routées | ✅ | [PR #45](https://github.com/evausesgit/x-med/pull/45) |
| 3 | Historique Alembic app (`alembic_version_app`, baseline 7 tables) | ✅ | PR 2 |
| 4 | Script de seed durci (dump quotidien → prod backup + seed previews) | 🔶 script fait ; cron + copie hors machine → étape 9 | PR 2 |
| 5 | Images : Dockerfile web (npm), CMD API sans migrations, target `init` | ✅ | PR 3 |
| 6 | Compose app : db (volume nommé sans `name:`) + init + api + web | ✅ | PR 3 |
| 7 | Init bi-mode (`XMED_DEPLOYMENT_MODE=production\|preview`) | ✅ | PR 3 |
| 8 | Validation locale des deux modes (checklist ci-dessous) | ✅ déroulée en réel | PR 3 |
| 9 | Ressource Coolify + previews + MR jetable de recette + Firebase auto | 🔶 ressource en ligne ([next.x-med.ia-do-it.com](https://next.x-med.ia-do-it.com)) ; recette previews en cours | |
| 10 | Bascule prod (domaine temporaire → copie finale → bascule Traefik) | ⬜ supervisée | |

### Détail de ce qui reste par étape

**Étape 1 (reliquat)** — créer les rôles Postgres sur le corpus : `xmed_api_ro`
(SELECT seul + `statement_timeout` + limite de connexions) et `xmed_preview_ro`
(plus contraint). Création de rôle = non destructif. À faire au plus tard avec la PR 3.

**Étape 3 (PR 2)** — `alembic/app/` : baseline squashée = exactement les 7 tables,
`version_table="alembic_version_app"`, aucune trace vector/bench/eval/corpus.
Test : `upgrade head` sur un Postgres vide → 7 tables + `alembic_version_app`, rien
d'autre. Ne JAMAIS jouer l'ancien historique monolithique sur la base app neuve.

**Étape 4 (PR 2)** — script de dump : les 7 tables, SANS l'ancien `alembic_version` ;
publication atomique (`.tmp` → vérif → rename), rétention N générations, copie hors
machine. Bootstrap : `template0` → `pg_restore --exit-on-error --single-transaction
--no-owner --no-acl` → vérif → `alembic stamp <baseline>` → `upgrade head`.

**Étapes 5–8 (PR 3)** — cf. plan de fond § 5 phase 3. Points durs actés : client
PostgreSQL **16** explicite dans la target `init` (pas le paquet distro) ; healthcheck
de l'image API désactivé pour l'init ; `API_INTERNAL_URL=http://api:8800` posé AVANT
`npm run build` (les rewrites Next sont figés au build) ; volume `backoffice_pgdata`
**sans champ `name:`** (Coolify doit pouvoir préfixer par projet/PR) ; chaîne
`db healthy → init completed → api healthy → web`.

Checklist de validation locale (étape 8) :
1. `docker compose config` : aucun port hôte publié.
2. Mode production : seed initial → restart → données conservées.
3. Redéploiement production : données conservées, migrations rejouées.
4. Mode preview : modifier une donnée → redéployer → elle a disparu.
5. Migration volontairement cassée : ni api ni web ne démarrent.
6. Recherche complète web → api → corpus.
7. Écritures (profil, traduction) : uniquement dans la base app (test de frontière).

**Étape 9** — ressource Coolify compose, previews activées, variables scopées preview
(`XMED_DEPLOYMENT_MODE`, credential corpus ro, JAMAIS le `~/.codex` prod ni de secret
prod), seed monté `:ro`, domaine sur `web` seul, automatisation Firebase (skill
`firebase-preview-domains`). Recette sur MR jetable : ouvrir → seed+migrations →
push → re-seed → fermer → **vérifier la destruction réelle des volumes**.

Points ajoutés par la revue Codex de la PR 3 (à valider à cette étape) :
- l'init doit être **recréé/réexécuté à chaque déploiement** (un one-shot inchangé
  peut ne pas être relancé par `compose up` — nonce, `--force-recreate`, ou le
  mécanisme Coolify équivalent + `exclude_from_hc`) — à PROUVER sur la MR jetable ;
- rendre la connexion de `x-med-db-1` au réseau `xmed-corpus-access` **persistante**
  (dans son docker-compose hôte, pas un `docker network connect` manuel qui saute
  à la recréation du conteneur) ;
- jouer `scripts/create_corpus_roles.sql` sur le corpus et brancher les URLs ro ;
- planifier `scripts/backup_backoffice.py` (Scheduled Task) + copie hors machine ;
- post-bascule : passer le défaut `RUN_MIGRATIONS_ON_BOOT` à 0 (opt-in explicite) et
  épingler `python:3.12-slim` par digest.

**Étape 10** — nouvelle stack sur domaine temporaire → tests complets → courte
maintenance (gel des écritures ancien backend) → dump final → seed de la base app
prod → vérifs (comptes, recherches, traductions) → bascule du domaine → ancienne
stack conservée pour rollback. AUCUN `DROP` côté corpus. Ensuite : retirer le
`8800:8800` de l'ancien conteneur API, backups quotidiens depuis la nouvelle base,
restreindre l'exposition du `5432` corpus (réseau dédié ou bind `10.0.1.1` + firewall).

## Journal

- **2026-07-27** — Backup backoffice vérifié. PR #45 (étape 2) : split runtime,
  revue Codex intégrée (fix transaction `SET LOCAL` du FTS, test de frontière
  app/corpus par listeners SQL, warning de repli d'URL). 55 tests verts avec et
  sans `CORPUS_DATABASE_URL`. **Mergée.**
- **2026-07-27** — PR 2 (étapes 3+4) : `alembic/app` (baseline `app0001` squashée,
  byte-identique au DDL prod, `alembic_version_app`, schéma `public` explicite,
  autogenerate désactivé tant que la Base n'est pas scindée) +
  `scripts/backup_backoffice.py` (verrou flock, dump -Fc transactionnel, sha256,
  manifeste atomique `latest.json` = source de vérité du seed, `--allow-unversioned`
  requis pour la base monolithique, rétention qui préserve le dump référencé).
  Revue Codex intégrée (verrou, échappement `%` ConfigParser, `%(here)s`,
  version_table_schema, manifeste, fsync, test offline). 61 tests verts.
  Contrat de bootstrap acté pour la PR 3 : restore → vérif → `stamp app0001` si
  dump non versionné (jamais de stamp opportuniste : marqueur `bootstrap_complete`
  posé après `upgrade head` seulement) → `upgrade head` ; révision inconnue =
  rebase imposé. Ne JAMAIS stamper `x-med-db-1`.
- **2026-07-27** — PR 3 (étapes 5–8) : Dockerfile 3 stages (base/init/api — api en
  dernier = cible par défaut, la prod monolithique Coolify continue de builder sans
  --target ; migrations au boot gated `RUN_MIGRATIONS_ON_BOOT`, défaut 1 inchangé),
  `web/Dockerfile` (npm, `API_INTERNAL_URL` posé avant build, non-root), compose app
  (db/init/api/web, zéro port, volume sans `name:`, réseau `xmed-corpus-access`
  external sur api seul), `scripts/bootstrap_app_db.py` (manifeste+sha256, preview
  drop/recreate WITH FORCE à chaque run, prod sans stamp opportuniste, matrice
  manifeste↔base, advisory lock, marqueur `xmed_ops` après upgrade seulement, rôle
  `xmed_app_runtime` DML-only réaligné après chaque upgrade — l'API ne voit jamais
  l'admin), `scripts/create_corpus_roles.sql` (livré, NON exécuté — étape 9).
  Checklist étape 8 déroulée en réel : seed prod restauré (3/43/986), persistance
  après down/up, re-seed preview, init cassé → api/web jamais démarrés, lecture
  corpus via alias `corpus-db`, écritures app seules (app 3→4, corpus 3→3), DDL
  refusé au runtime, verrou prouvé. Revue Codex intégrée (2 bloquants : rôle
  superuser API, recoupement manifeste↔base ; + durcissements). 61 tests verts.
  ⚠️ Observation pour l'étape 9 : sur un REdéploiement dont l'init échoue, api/web
  déjà lancés continuent sur l'ancienne version (le blocage total ne vaut qu'au
  premier déploiement) — comportement Coolify à valider sur la MR jetable.
- **2026-07-27** — Étape 9, ressource en ligne : compose `x-med-app` créé dans
  Coolify (uuid `oy7orijsvx37277mtq8incqo`), domaine `next.x-med.ia-do-it.com`
  (TLS Let's Encrypt, wildcard DNS existant, domaine autorisé Firebase — **login
  Google validé par l'utilisateur**). Seed prod restauré (3/43/986), init re-run
  prouvé à chaque redéploiement (« marqueur présent : migrations seules »),
  recherche PubMed+IA réelle réussie de bout en bout (builder+judge codex, 4
  résultats). Rôles `xmed_api_ro`/`xmed_preview_ro` créés et prouvés (SELECT
  corpus OK, DELETE refusé, backoffice invisible) ; réseau `xmed-corpus-access`
  actif (alias `corpus-db`) ; API sous `xmed_app_runtime`. Pièges Coolify
  résolus : volumes `${VAR}` refusés en syntaxe courte → syntaxe longue (PR #49) ;
  suffixe `-pr-N` des binds en preview → désactivé pour `${SEED_DIR}`
  (`local_file_volumes.is_preview_suffix_enabled=false`) ; template d'URL preview
  forcé à `{{pr_id}}.x-med.ia-do-it.com` (le défaut `{{pr_id}}.{{domain}}` aurait
  donné 2 niveaux sous le wildcard DNS). ⚠️ La #47 avait été mergée dans sa
  branche de base (`gh pr edit --base` échoué silencieusement) — relivrée sur
  main par la #48. Secrets : `~/.config/xmed/{appdb-admin,appdb-runtime,
  corpus-api-ro,corpus-preview-ro}-password`. Cette PR-ci sert de MR jetable de
  recette du cycle preview.
- **2026-07-27 (incident + recette previews)** — La MR jetable #51 a rempli son
  rôle en révélant QUATRE limites Coolify, dont une par incident : (1) le parser
  fige les variables du bloc `environment` avec les valeurs du scope PRODUCTION
  dans le compose généré des previews — le scoping preview est inopérant pour
  toute variable référencée par le compose → fail-safe dans le bootstrap (mode
  preview FORCÉ dès qu'un marqueur de contexte PR est présent :
  SERVICE_NAME_INIT/COOLIFY_BRANCH) ; (2) les binds de preview sont suffixés
  `-pr-N` sans opt-out fiable → pool de symlinks `~/backups/xmed-pr-{51..300}`
  → `xmed` (docker résout les symlinks au montage) ; (3) la `.env`
  d'interpolation est PARTAGÉE entre déploiements prod/preview d'une même
  ressource (course si merge et push simultanés) ; (4) **INCIDENT** : un réseau
  compose nommé (mon `default` explicite + alias) est PARTAGÉ entre prod et
  previews (même nom de projet) → l'alias `appdb` résolvait vers les DEUX bases
  et l'init d'une preview a drop/re-seedé la base de la stack prod. Impact :
  ~15 min de dégradation de next.x-med, ZÉRO perte (la base monolithique,
  source de vérité, sert x-med.ia-do-it.com et n'a jamais été touchée) ;
  rétabli par drop/recreate + re-bootstrap depuis le seed. Leçons gravées :
  l'isolation prod/preview EST le réseau par-déploiement de Coolify — aucun
  réseau nommé partagé (hors corpus-access, partagé à dessein en lecture
  seule) ; hostnames internes résolus AU RUNTIME via SERVICE_NAME_DB
  (bootstrap + entrypoint API) ; usage local via docker-compose.app.local.yml.
  Recette encore à terminer sur une nouvelle MR jetable après merge du fix.
