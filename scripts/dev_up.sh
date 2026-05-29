#!/usr/bin/env bash
# Démarre toute la stack X-Med en dev :
#   - Postgres + Redis (docker compose)
#   - API FastAPI sur :8800 (proxiée par le front, donc en localhost)
#   - Frontend Next (build de prod) sur :3003 (exposé en 0.0.0.0)
#
# Idempotent : relancer ne crée pas de doublons (kill des anciens process X-Med).
# Usage : bash scripts/dev_up.sh
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "→ Postgres + Redis"
docker compose up -d db redis
# attendre que la base soit prête
until docker compose exec -T db pg_isready -U xmed -d xmed >/dev/null 2>&1; do sleep 1; done

echo "→ Migrations"
uv run alembic upgrade head

echo "→ API FastAPI :8800"
# ne tue que NOTRE uvicorn (port 8800), pas ceux des autres projets
pkill -f "uvicorn app.main:app .*8800" 2>/dev/null || true
sleep 1
setsid nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8800 \
  --log-level warning >/tmp/xmed-api.log 2>&1 < /dev/null &

echo "→ Frontend Next :3003 (build)"
( cd web && npm run build >/tmp/xmed-web-build.log 2>&1 )
# ne tue que NOTRE next-server sur 3003
pkill -f "next start -p 3003" 2>/dev/null || true
sleep 1
( cd web && setsid nohup npm run start -- -p 3003 -H 0.0.0.0 \
  >/tmp/xmed-web.log 2>&1 < /dev/null & )

sleep 4
echo
echo "API  : http://localhost:8800/health"
echo "Web  : http://localhost:3003  (ou http://<IP-serveur>:3003)"
echo "Logs : /tmp/xmed-api.log  /tmp/xmed-web.log"
