# API X-Med — image FastAPI pour Coolify (DEPLOY_BACKEND_COOLIFY.md § 3.1).
#
# Trois stages :
#   - `base` : socle commun (uv + dépendances, Node 22 + CLI codex, code) ;
#   - `init` : base + postgresql-client-16 (PGDG) + scripts/ — le service
#     one-shot du compose app qui seed/migre la base backoffice
#     (`python -m scripts.bootstrap_app_db`, cf. docker-compose.app.yml) ;
#   - `api`  : le serveur uvicorn. DERNIER stage = cible par défaut d'un
#     `docker build` sans `--target` : Coolify (prod monolithique actuelle)
#     builde ce Dockerfile sans cible et doit obtenir l'API, pas l'init.
#
# Ce qui N'est PAS dans l'image (fourni au runtime) :
#   - l'auth codex : bind-mount d'un dossier hôte → /home/api/.codex
#     (uid 1001 dans le conteneur = geekette sur l'hôte, mêmes droits) ;
#   - la config : DATABASE_URL, CORPUS_DATABASE_URL, CORS_ORIGINS, etc.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# Node 22 (NodeSource — le nodejs de bookworm est trop vieux pour codex) puis le
# CLI codex, épinglé : son format d'événements `exec --json` est parsé par
# app/services/codex_cli.py, une montée de version silencieuse pourrait le casser.
# ⚠️ La version doit suivre les modèles de app/config.py. On reste en 0.145.0
# bien que le retour à gpt-5.4 ne l'exige plus (elle sert gpt-5.4 sans souci) :
# elle reste requise si on re-route un jour sur les slugs gpt-5.6-*, refusés par
# le backend OpenAI en dessous (« requires a newer version of Codex », 400).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @openai/codex@0.145.0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uid 1001 = geekette sur l'hôte : les bind-mounts (auth codex) restent
# lisibles/inscriptibles des deux côtés. Même convention que Dockerfile.worker.
RUN useradd -m -u 1001 api

# Dépendances d'abord (cache de layer), code ensuite.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini alembic_app.ini ./

ENV PATH="/app/.venv/bin:$PATH"

USER api

EXPOSE 8800


# ---------------------------------------------------------------------------
# Stage `init` — service one-shot du compose app (docker-compose.app.yml).
# Restaure le seed backoffice (pg_restore 16) puis joue les migrations app ;
# api/web ne démarrent que s'il sort en 0 (depends_on: service_completed_
# successfully). Voir scripts/bootstrap_app_db.py pour le contrat complet.
# ---------------------------------------------------------------------------
FROM base AS init

USER root

# postgresql-client-16 depuis le dépôt PGDG officiel, majeure épinglée = celle
# du serveur : le client de la distro suit SA version (15 sous bookworm, 17
# sous trixie), jamais forcément la nôtre, et un pg_restore d'une autre majeure
# que le pg_dump est un risque de compatibilité silencieux. Le codename de la
# suite PGDG est lu dans /etc/os-release : python:3.12-slim a déjà changé de
# base Debian (bookworm → trixie) sans préavis, un codename en dur casserait.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnupg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

COPY scripts ./scripts

USER api

# Un one-shot n'a pas d'état « healthy » : sans ça il hériterait du healthcheck
# HTTP du stage api et resterait éternellement « starting » aux yeux du compose.
HEALTHCHECK NONE

CMD ["python", "-m", "scripts.bootstrap_app_db"]


# ---------------------------------------------------------------------------
# Stage `api` (défaut) — le serveur uvicorn.
# ---------------------------------------------------------------------------
FROM base AS api

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8800/health || exit 1

# Migrations au boot : comportement historique (prod monolithique actuelle,
# où l'API aligne elle-même le schéma à chaque déploiement). Le compose app
# met RUN_MIGRATIONS_ON_BOOT=0 : là-bas, l'init est l'unique propriétaire des
# migrations app et l'API ne touche jamais au schéma.
ENV RUN_MIGRATIONS_ON_BOOT=1

# La résolution runtime de l'hôte db (previews Coolify : db-pr-N) et la
# validation d'identité api ↔ db vivent dans app/runtime_env.py, exécutées à
# l'import de app.db — PAS dans ce CMD : une substitution shell ici serait
# contournée par `docker compose exec` ou une Scheduled Task, qui ne passent
# pas par le CMD mais importent bien app.db.
CMD ["sh", "-c", "\
  if [ \"${RUN_MIGRATIONS_ON_BOOT:-1}\" = \"1\" ]; then alembic upgrade head; fi \
  && exec uvicorn app.main:app --host 0.0.0.0 --port 8800"]
