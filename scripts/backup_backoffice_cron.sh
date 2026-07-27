#!/usr/bin/env bash
# Cron quotidien du backup backoffice (PLAN_EXECUTION_COMPOSE.md, étapes 4, 9 et 10).
#
# Enrobe `scripts/backup_backoffice.py` pour un hôte SANS client PostgreSQL :
# pg_dump/pg_restore/psql sont shimés vers le conteneur Postgres source (docker
# exec, flux par stdin/stdout — c'est prévu par le script Python, qui n'écrit
# jamais via `-f`). Le manifeste `latest.json` produit est la source de vérité
# du seed des previews ET le backup de prod.
#
# Depuis la bascule du 2026-07-27 (étape 10), la source est la base app de la
# stack compose `x-med-app`. Contraintes qui dictent la forme de ce script :
#   - le nom du conteneur db change à CHAQUE déploiement
#     (`db-<uuid>-<timestamp>`) → résolution dynamique, en excluant les
#     previews (`…-pr-N`) par le motif « uuid puis timestamp numérique » ;
#   - la db ne publie AUCUN port hôte → la sonde SQLAlchemy du script Python
#     (qui tourne sur l'hôte) passe par l'IP Docker du conteneur, joignable
#     depuis l'hôte comme depuis le conteneur lui-même (donc la même URL sert
#     aux shims docker-exec) ;
#   - le dump est désormais VERSIONNÉ (`alembic_version_app`) : un dump non
#     versionné est redevenu un symptôme d'erreur, donc pas de
#     `--allow-unversioned`.
# Si la stack est en cours de redéploiement à 4h30 (conteneur absent), le run
# échoue proprement dans cron.log et le run suivant rattrape.
#
# Installation (crontab de jack) :
#   30 4 * * * /home/jack/projects/x-med/scripts/backup_backoffice_cron.sh >> /home/jack/backups/xmed/cron.log 2>&1

set -euo pipefail

REPO=/home/jack/projects/x-med
OUT_DIR=/home/jack/backups/xmed
APP_RESOURCE_UUID=oy7orijsvx37277mtq8incqo
ADMIN_PASSWORD_FILE="$HOME/.config/xmed/appdb-admin-password"

SOURCE_CONTAINER=$(docker ps --format '{{.Names}}' \
  | grep -E "^db-${APP_RESOURCE_UUID}-[0-9]+$" | head -1)
if [ -z "$SOURCE_CONTAINER" ]; then
  echo "ERREUR: conteneur db prod de x-med-app introuvable (redéploiement en cours ?)" >&2
  exit 1
fi

DB_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$SOURCE_CONTAINER")
if [ -z "$DB_IP" ]; then
  echo "ERREUR: pas d'IP pour $SOURCE_CONTAINER" >&2
  exit 1
fi

DB_URL=$(ADMIN_PW_FILE="$ADMIN_PASSWORD_FILE" DB_IP="$DB_IP" python3 - <<'PY'
import os, pathlib, urllib.parse
pw = pathlib.Path(os.environ["ADMIN_PW_FILE"]).read_text().strip()
print(f"postgresql://xmed_admin:{urllib.parse.quote(pw, safe='')}@{os.environ['DB_IP']}:5432/xmed_app")
PY
)

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
  --keep 14
