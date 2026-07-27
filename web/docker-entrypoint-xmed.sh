#!/bin/sh
# Garde d'isolation FAIL-CLOSED du front (incident du 2026-07-27).
#
# Les rewrites /api/* de Next sont FIGÉS AU BUILD avec l'hôte de
# API_INTERNAL_URL. Si l'image a été construite pour un autre déploiement que
# celui où elle démarre (ex. build-arg figé côté prod par le parser Coolify,
# démarré dans une preview), le front relayerait les requêtes — POST compris —
# vers l'API d'UN AUTRE déploiement : violation d'isolation, pas une
# « dégradation ». Donc : SERVICE_NAME_API présente (contexte Coolify) et
# différente de l'hôte figé → refus de démarrer, exit 1.
#
# Hors Coolify (SERVICE_NAME_API absente — dev local, compose local) : no-op.
set -eu

if [ -n "${SERVICE_NAME_API:-}" ]; then
  # Hôte figé au build : http://<hôte>:8800 → <hôte> (POSIX pur, pas de node).
  baked="${API_INTERNAL_URL:-http://api:8800}"
  baked="${baked#*://}"   # retire le schéma
  baked="${baked%%/*}"    # retire un éventuel chemin
  baked="${baked%%:*}"    # retire le port
  if [ "$baked" != "$SERVICE_NAME_API" ]; then
    echo "FATAL [web] : l'image fige API_INTERNAL_URL='${API_INTERNAL_URL:-}'" \
      "(hôte '${baked}') mais ce déploiement est SERVICE_NAME_API='${SERVICE_NAME_API}'." \
      "Un front qui pointe l'API d'un autre déploiement est une violation" \
      "d'isolation (POST possibles vers la prod depuis une preview) — refus" \
      "de démarrer. Rebuilder l'image web avec le bon build-arg" \
      "API_INTERNAL_URL (cf. docker-compose.app.yml, service web)." >&2
    exit 1
  fi
fi

exec "$@"
