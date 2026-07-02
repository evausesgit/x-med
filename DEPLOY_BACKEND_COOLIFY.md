# Plan — déployer le backend dans Coolify (stabilisation)

But : sortir le backend du mode « uvicorn lancé à la main sur l'hôte » et le faire
**gérer par Coolify** (restart auto, healthchecks, services managés), comme le front.
Motivation : à chaque redémarrage/suspension de l'hôte, le uvicorn meurt et Postgres
crashe (recovery WAL, base indisponible) → recherche du site fragile, chargements
interrompus. Un backend managé supprime cette classe de pannes.

## 1. État actuel (relevé le 2026-07)

| Composant | Comment il tourne aujourd'hui | Géré par Coolify ? |
|---|---|---|
| **Postgres** (pgvector/pg16) | `docker compose` (service `db`, volume `pgdata`) | ❌ compose à la main |
| **Redis** (7-alpine) | `docker compose` (service `redis`) | ❌ |
| **API FastAPI** (`:8800`) | `uv run uvicorn` en `setsid nohup` via `scripts/dev_up.sh` | ❌ hôte nu |
| **Front Next** (`:3003`) | build + `next start` via dev_up.sh **ET** conteneur Coolify public | ✅ (public) |
| **Cron PubMed quotidien** | `scripts/pubmed_daily.py` via cron système 05:00 UTC | ❌ |

- `docker-compose.yml` : seuls `db` + `redis` sont définis ; `api:` et `web:` sont
  **commentés** (« à ajouter »). Pas de `Dockerfile` pour l'API.
- Le front Coolify (réseau `10.0.1.0/24`) joint l'API via **`10.0.1.1:8800`** (IP hôte).
- **Celery/Beat pas encore implémentés** — l'ordonnancement est un cron système. Redis
  est là mais peu/pas utilisé.
- ⚠️ **Piège `codex`** : l'API shelle le binaire `codex` (CLI GPT-5.4, installé en **npm
  global** dans `~/.npm-global/bin`) pour la recherche. Dans un conteneur, il faut
  l'**installer au build** ET gérer son **authentification** (voir §5).

## 2. Cible

Tout en services Coolify, sur un réseau interne :

```
Coolify
 ├── db     : pgvector/pgvector:pg16   (volume persistant pgdata)
 ├── redis  : redis:7-alpine
 ├── api    : image X-Med (FastAPI + uv + codex)   ← NOUVEAU, conteneurisé
 │             volumes : données PubMed (60 Go), cache codex/auth
 ├── worker : (plus tard) Celery/Beat pour le cron quotidien
 └── web    : Next (déjà en Coolify) → appelle api via le réseau interne
```

## 3. Étapes

1. **Dockerfile de l'API** (`Dockerfile`, base `python:3.12-slim`) :
   - installer `uv`, dépendances Python (`uv sync`), `lxml`/libs système ;
   - installer **Node + le paquet npm `codex`** dans l'image (le binaire doit être dans
     le `PATH` du conteneur) ;
   - commande : `uv run uvicorn app.main:app --host 0.0.0.0 --port 8800` ;
   - `HEALTHCHECK` → `/health`.
2. **Compose / services Coolify** : dé-commenter/ajouter `api` (et `worker` plus tard),
   les brancher sur `db` + `redis` par le réseau interne (plus de `10.0.1.1:8800` :
   le front appelle `http://api:8800`).
3. **Volumes persistants** :
   - `pgdata` (Postgres, ~11–25 Go, croissant) — **ne pas perdre** à la migration ;
   - **données PubMed** `/home/geekette/data/pubmed` (**60 Go**) → volume monté (ou
     bind-mount) accessible par l'API/worker pour l'ingestion ;
   - cache/auth `codex` (voir §5).
4. **Env & secrets** dans Coolify : `DATABASE_URL`, `REDIS_URL`, clés API (Claude,
   Resend, NIH E-utilities), `DATA_DIR`, etc. (cf. `app/config.py`, `ARCHITECTURE.md`).
5. **Front → API en interne** : passer `API_INTERNAL_URL` (rewrite `/api/*` de Next) de
   `10.0.1.1:8800` à `http://api:8800` (réseau Coolify). Le proxy garde le SSE (déjà
   géré : `X-Accel-Buffering: no`, keep-alives).
6. **Ordonnancement** : à terme, `worker` Celery/Beat pour `pubmed_daily` ; en
   transition, garder le cron système.

## 4. Migration des données (sans perte)

- **Postgres** : soit réutiliser le volume `pgdata` existant tel quel (si Coolify peut
  l'adopter), soit `pg_dump`/`pg_restore` vers le nouveau service. Vu la taille (et les
  ~30 M lignes si on recharge la baseline), **préférer réutiliser le volume**.
- **Données PubMed 60 Go** : bind-mount du dossier existant → **rien à re-télécharger**.

## 5. Le point dur : `codex` dans le conteneur

C'est probablement **ce qui avait bloqué « à l'époque »** — à confirmer :
- installer le binaire au build (npm global) → le mettre dans le `PATH` ;
- **authentification** : `codex` utilise un login OAuth (fichier de session). Il faut
  soit monter le fichier d'auth en volume/secret, soit un token de service. À vérifier :
  l'auth codex survit-elle en conteneur headless ?
- alternative de repli : si l'auth codex en conteneur est trop fragile, garder **codex
  sur l'hôte** et faire appeler l'API… non — ça recrée la dépendance hôte. Mieux vaut
  résoudre l'auth conteneur.

## 6. Risques / à re-investiguer avant de lancer

- **Pourquoi ça avait échoué avant ?** (ressources ? auth codex ? volumes ? réseau ?) →
  à documenter en premier, sinon on refait la même erreur.
- **Ressources** : l'ingestion baseline sature déjà Postgres (crashes OOM observés) →
  fixer des **limites mémoire** correctes au conteneur `db` (et surveiller).
- **Downtime** de bascule : prévoir une fenêtre ; garder le uvicorn hôte en **repli**
  jusqu'à validation.
- **`codex` = dépendance externe forte** : si l'auth conteneur ne tient pas, tout le
  mode PubMed+IA tombe. Prévoir le repli « fallback » (déjà géré côté code : `builder=
  fallback`, `judge=skipped`) mais c'est dégradé.

## 7. Rollout proposé (progressif, réversible)

1. Écrire le `Dockerfile` API + le faire tourner **en local** (`docker compose up api`),
   valider `/health` **et** une recherche PubMed+IA (donc codex OK en conteneur).
2. Résoudre l'auth codex en conteneur (le vrai verrou).
3. Ajouter `api` dans Coolify, réseau interne, volumes, env → déployer **en parallèle**
   du uvicorn hôte (port distinct), tester.
4. Basculer le front sur l'API Coolify (`API_INTERNAL_URL`), garder l'hôte en repli.
5. Une fois stable : couper le uvicorn hôte, migrer le cron vers un worker Coolify.

> Décision préalable pour Eva : on vise **tout dans Coolify** (db+redis+api+worker), ou
> on **garde db/redis en compose** et on ne conteneurise que l'API ? (Le plus stable =
> tout dans Coolify, mais plus de travail de migration des volumes.)
