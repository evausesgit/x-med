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

### 1.a Provenance réelle des conteneurs (relevé 2026-07)

Docker est **rootful** : démon `dockerd` en **root**, socket `/var/run/docker.sock` en
`root:docker` (0660). L'utilisateur `geekette` (uid 1001) est dans `sudo` mais **pas dans
le groupe `docker`** → il ne pilote Docker qu'en `sudo`. (Reco confort : `sudo usermod
-aG docker geekette`.)

Trois conteneurs Postgres distincts coexistent sur l'hôte :

| Conteneur | Base | Géré par |
|---|---|---|
| `docker-3daeda…` | `legiradar` | autre projet |
| `docker-98508e…` | `coolify` | **Postgres interne de Coolify** (son propre état) |
| `docker-ead35a9…` | **`xmed`** (publié `:5432`) | **`docker compose` à la main (dev_up.sh), en root — PAS Coolify** |

⇒ Constat clé : le `db` (et le `redis`) X-Med sont des conteneurs **compose artisanaux,
hors radar de Coolify** — Coolify ne les redémarre pas, ne les surveille pas, ne les
soigne pas. C'est **la cause racine** de la fragilité (à chaque restart de l'hôte,
personne ne relève proprement le `db` → crash/recovery). Coolify, lui, tourne et est
sain (`/data/coolify`, uid 9999) : il gère sa propre base, son proxy Traefik et le
**front** déployé, mais **ni `db`, ni `redis`, ni l'API X-Med**. → Il peut tout à fait
**adopter ces services comme ressources managées** (cible §2).

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

## 7. Rollout — décidé et en cours (2026-07-05)

**Décisions prises** : périmètre = **API seule dans Coolify** (db/redis restent en
compose : `restart: always` suffit, et migrer le volume pgdata de 63 Go est un risque
pour peu de gain). Transition = **parallèle puis bascule**.

### 7.1 L'image (`Dockerfile` à la racine — livré)

- `python:3.12-slim` + uv, `uv sync --frozen --no-dev --group ml` (la recherche
  sémantique MedCPT/bge-m3 tourne dans l'API → torch **CPU** requis ; l'index
  `download.pytorch.org/whl/cpu` est épinglé dans `pyproject.toml`, ce qui retire
  ~7 Go de wheels NVIDIA inutiles — l'hôte n'a pas de GPU).
- Node 22 (NodeSource) + `@openai/codex` npm global, **version épinglée** (le format
  d'événements `codex exec --json` est parsé par `app/services/codex_cli.py`).
- `USER` uid 1001 (= `geekette` côté hôte, même convention que `Dockerfile.worker`).
- `HF_HOME=/data/hf-cache` : les modèles d'embedding (~5 Go) vivent dans un **volume
  persistant**, téléchargés au premier chargement puis réutilisés entre déploiements.
- `CMD` : `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8800`
  (les migrations, jusqu'ici jouées par `dev_up.sh`, suivent le déploiement).

### 7.2 Auth codex : bind-mount du `~/.codex` vivant de geekette (pattern legiradar)

Décision d'Eva (2026-07-05) : le conteneur utilise **le login codex de geekette**, sur
le modèle éprouvé de legiradar (son worker Coolify monte `/home/jack/.codex` en rw avec
`CODEX_HOME=/codex-home`, en prod depuis des jours sans incident).

Concrètement : bind-mount **`/home/geekette/.codex` → `/codex-home`** (rw) + variable
d'env **`CODEX_HOME=/codex-home`**. Le conteneur tourne en uid 1001 = geekette, les
droits collent des deux côtés, et l'état d'auth reste unique (un re-login de geekette
sur l'hôte profite immédiatement au conteneur — pas de copie qui périme).

Risque résiduel assumé (revue Codex) : pendant la phase parallèle, le uvicorn hôte et
le conteneur partagent le même state dir — rotation du token en last-write-wins et
versions CLI différentes qui écrivent leurs métadonnées au même endroit. Le précédent
legiradar montre que ça tient en pratique ; la phase parallèle est de toute façon
courte.

### 7.3 Bascule sans rebuild du front (remap de port)

Next 16 fige la destination du rewrite `/api` **au build** (`http://10.0.1.1:8800`).
Plutôt que rebuilder le front : l'app Coolify publie d'abord **`8810:8800`** (phase
parallèle), puis à la bascule on remappe **`8800:8800`**. Le front continue de taper
`10.0.1.1:8800` sans rebuild. C'est une **mini-coupure assumée** (le remap redéploie le
conteneur), pas un hot-swap. À terme, l'état propre reste un rebuild front vers l'API
en réseau interne Coolify — le remap est la bascule pragmatique, pas l'architecture
finale.

Séquence :

1. Déployer l'app API Coolify en `8810:8800` + `ufw allow from 10.0.1.0/24 to any
   port 8810 proto tcp`.
2. Tester **depuis le conteneur web** : `curl http://10.0.1.1:8810/health`, puis une
   recherche PubMed+IA complète (valide codex en conteneur — le vrai verrou).
3. Stopper le uvicorn hôte ; vérifier `ss -ltnp | grep ':8800'` vide.
4. Remapper l'app Coolify en `8800:8800`, accepter le redéploiement.
5. Re-tester depuis le conteneur web : `curl http://10.0.1.1:8800/health` + recherche.
6. **Rollback** si problème : remettre `8810:8800` et relancer le uvicorn hôte
   (`scripts/dev_up.sh`).

## 8. Étape isolée — sortir le **cron PubMed quotidien** du crontab système vers Coolify

Premier pas concret, indépendant de la migration complète de l'API : faire gérer la
mise à jour quotidienne PubMed (`scripts/pubmed_daily.py`) par une **Scheduled Task
Coolify** au lieu de la crontab de `geekette`. Bénéfice : plus de tâche invisible sur
l'hôte, logs + historique d'exécution dans l'UI Coolify, redémarrage géré.

### Comment ça marche dans Coolify

Une *Scheduled Task* Coolify s'attache à une **application** et fait un `docker exec`
d'une commande dans son conteneur, selon un cron. Il faut donc une petite application
worker **qui reste vivante** (`sleep infinity`) ; le cron, lui, lance la commande dedans.

### Pièces livrées dans le repo (cette PR)

- **`Dockerfile.worker`** — image minimale (`python:3.12-slim` + `uv sync --no-dev`),
  sans FastAPI servie, sans torch, sans codex (l'ingestion n'en a pas besoin). Le
  conteneur ne fait que `sleep infinity` ; la Scheduled Task exécute le script.
- **`requests`** ajouté aux dépendances cœur de `pyproject.toml` (le download des
  updatefiles l'utilise ; il n'était que transitif → une install `--no-dev` cassait).

### À créer côté Coolify (via API, une fois le token fourni)

1. **Application** (build pack *Dockerfile*), repo `github.com/evausesgit/x-med`,
   branche `main`, `Dockerfile.worker`. Pas de domaine, pas de port exposé.
2. **Variables d'environnement** :
   - `DATABASE_URL=postgresql+psycopg://xmed:xmed@10.0.1.1:5432/xmed`
     (le Postgres X-Med tourne en compose sur l'hôte ; `10.0.1.1` = passerelle du
     réseau Docker « coolify » vers l'hôte, comme pour l'API `:8800`).
   - `DATA_DIR=/data/pubmed`
3. **Bind-mount (Storage)** : hôte `/home/geekette/data/pubmed` → conteneur
   `/data/pubmed`. Les updatefiles téléchargés y persistent et restent lisibles par
   l'hôte (le conteneur tourne en **uid 1001 = `geekette`**).
4. **Scheduled Task** : commande `python -m scripts.pubmed_daily`, cron `0 5 * * *`
   (05:00 UTC, à l'identique de la crontab actuelle).
5. **Pare-feu** : autoriser le réseau coolify vers Postgres si besoin —
   `ufw allow from 10.0.1.0/24 to any port 5432 proto tcp` (analogue à la règle `:8800`).

### Bascule

Déployer, **déclencher la tâche une fois à la main** dans l'UI et vérifier les logs
(download + ingestion OK, `ftp_state` avance). Une fois validée, **retirer la ligne
`pubmed_daily` de la crontab** de `geekette` (garder le cron LinkedIn 6h, hors périmètre).

> Le worker est aussi le point d'accroche naturel pour les futurs crons (embedding des
> nouveaux articles pour combler le trou 2025-2026, LinkedIn, etc.) : une app, N tâches.
