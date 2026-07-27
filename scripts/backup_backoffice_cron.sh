#!/usr/bin/env bash
# Cron quotidien du backup backoffice (PLAN_EXECUTION_COMPOSE.md, étapes 4 et 9).
#
# Enrobe `scripts/backup_backoffice.py` pour un hôte SANS client PostgreSQL :
# pg_dump/pg_restore sont shimés vers le conteneur Postgres source (docker exec,
# flux par stdin/stdout — c'est prévu par le script Python, qui n'écrit jamais
# via `-f`). Le manifeste `latest.json` produit est la source de vérité du seed
# des previews ET le backup de prod.
#
# Source AVANT bascule : x-med-db-1 (les 7 tables backoffice y vivent encore) →
# `--allow-unversioned` requis (pas d'alembic_version_app dans cette base).
# APRÈS bascule (étape 10) : pointer SOURCE_CONTAINER/DB_URL sur la base app du
# compose x-med-app et RETIRER --allow-unversioned (un dump non versionné
# redeviendra un symptôme d'erreur).
#
# Installation (crontab de jack) :
#   30 4 * * * /home/jack/projects/x-med/scripts/backup_backoffice_cron.sh >> /home/jack/backups/xmed/cron.log 2>&1

set -euo pipefail

REPO=/home/jack/projects/x-med
OUT_DIR=/home/jack/backups/xmed
SOURCE_CONTAINER=x-med-db-1
DB_URL="postgresql://xmed:xmed@localhost:5432/xmed"   # résolue DANS le conteneur source

SHIM_DIR=$(mktemp -d)
trap 'rm -rf "$SHIM_DIR"' EXIT
for tool in pg_dump pg_restore psql; do
  printf '#!/bin/sh\nexec docker exec -i %s %s "$@"\n' "$SOURCE_CONTAINER" "$tool" > "$SHIM_DIR/$tool"
  chmod +x "$SHIM_DIR/$tool"
done

cd "$REPO"
PATH="$SHIM_DIR:$PATH" uv run python -m scripts.backup_backoffice \
  --out-dir "$OUT_DIR" \
  --database-url "$DB_URL" \
  --allow-unversioned \
  --keep 14
