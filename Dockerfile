# API X-Med — image FastAPI complète pour Coolify (DEPLOY_BACKEND_COOLIFY.md § 3.1).
#
# Contenu : uv + dépendances cœur ET groupe ml (torch CPU, transformers — la
# recherche sémantique MedCPT/bge-m3 tourne dans l'API), plus Node 22 + le CLI
# `codex` (npm global) que l'API shelle pour la recherche PubMed+IA.
#
# Ce qui N'est PAS dans l'image (fourni au runtime par Coolify) :
#   - l'auth codex : bind-mount de /home/geekette/.codex → /home/api/.codex
#     (uid 1001 dans le conteneur = geekette sur l'hôte, mêmes droits) ;
#   - le cache des modèles HF (~5 Go) : volume persistant monté sur $HF_HOME,
#     téléchargés au premier chargement puis réutilisés entre déploiements ;
#   - la config : DATABASE_URL, CORS_ORIGINS, etc. en variables d'env Coolify.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# Node 22 (NodeSource — le nodejs de bookworm est trop vieux pour codex) puis le
# CLI codex, épinglé : son format d'événements `exec --json` est parsé par
# app/services/codex_cli.py, une montée de version silencieuse pourrait le casser.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @openai/codex@0.142.5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uid 1001 = geekette sur l'hôte : les bind-mounts (auth codex) restent
# lisibles/inscriptibles des deux côtés. Même convention que Dockerfile.worker.
RUN useradd -m -u 1001 api \
 && mkdir -p /data/hf-cache \
 && chown api:api /data/hf-cache

# Dépendances d'abord (cache de layer), code ensuite.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group ml --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/data/hf-cache

USER api

EXPOSE 8800

# --start-period large : le premier démarrage télécharge les modèles d'embedding
# si le cache HF est vide.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8800/health || exit 1

# Migrations puis serveur : idempotent, aligne le schéma à chaque déploiement
# (c'était le rôle de scripts/dev_up.sh sur l'hôte).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8800"]
