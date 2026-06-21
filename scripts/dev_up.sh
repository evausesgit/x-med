#!/usr/bin/env bash
# Démarre toute la stack X-Med en dev :
#   - Postgres + Redis (docker compose)
#   - API FastAPI sur :8800 — exposée en 0.0.0.0 pour que le site DÉPLOYÉ
#     (conteneur Coolify, réseau 10.0.1.0/24) la joigne via 10.0.1.1:8800.
#     L'accès au port 8800 est restreint à ce sous-réseau par ufw.
#   - Frontend Next (build de prod) sur :3003 (exposé en 0.0.0.0)
#
# Idempotent : relancer ne crée pas de doublons. On tue l'ancien process PAR LE
# PORT (et pas par un motif `pkill -f next…`) : la vraie ligne de commande de Next
# contient plusieurs `-p`, donc un motif ne matche pas de façon fiable et l'ancien
# serveur survit (le nouveau échoue alors en EADDRINUSE et on reste sur l'ancien build).
# Usage : bash scripts/dev_up.sh
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# `codex` (CLI GPT-5.4 utilisé par la recherche PubMed + IA)
# est installé via npm GLOBAL dans ~/.npm-global/bin. Quand ce script est lancé par
# un terminal interactif, ce dossier est déjà dans le PATH. Mais lancé par un AGENT
# (arbre `systemd --user` → hermes gateway), le PATH hérité est minimal et N'inclut
# PAS ~/.npm-global/bin → uvicorn ne trouve pas `codex` et /search/pubmed/deep renvoie
# « 502 codex introuvable ». On force donc le dossier dans le PATH, quel que soit le
# lanceur, pour que le backend trouve toujours codex.
export PATH="$HOME/.npm-global/bin:$PATH"
command -v codex >/dev/null 2>&1 \
  || echo "⚠ codex introuvable dans le PATH — la recherche PubMed (mode abstracts) échouera"

# Tue le process qui écoute sur le port donné (par PID), puis attend la libération.
kill_port() {
  local port="$1"
  local pid
  pid=$(ss -ltnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | head -1)
  if [ -n "$pid" ]; then
    echo "  · port ${port} occupé par PID ${pid} → kill"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 15); do
      ss -ltn 2>/dev/null | grep -q ":${port} " || return 0
      sleep 1
    done
    # toujours occupé après 15 s → on insiste
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
}

# Attend qu'une URL réponde (HTTP 2xx/3xx). 0 = OK, 1 = timeout.
wait_http() {
  local url="$1" tries="${2:-30}"
  for _ in $(seq 1 "$tries"); do
    curl -sf -o /dev/null "$url" && return 0
    sleep 1
  done
  return 1
}

echo "→ Postgres + Redis"
docker compose up -d db redis
# attendre que la base soit prête
until docker compose exec -T db pg_isready -U xmed -d xmed >/dev/null 2>&1; do sleep 1; done

echo "→ Migrations"
uv run alembic upgrade head

echo "→ API FastAPI :8800"
kill_port 8800
setsid nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8800 \
  --log-level warning >/tmp/xmed-api.log 2>&1 < /dev/null &

echo "→ Frontend Next :3003 (build)"
# Le build se fait AVANT de tuer l'ancien serveur : si le build échoue (set -e),
# on sort sans coupure et l'ancien site reste en ligne.
( cd web && npm run build >/tmp/xmed-web-build.log 2>&1 )
kill_port 3003
( cd web && setsid nohup env PORT=3003 npm run start -- -H 0.0.0.0 \
  >/tmp/xmed-web.log 2>&1 < /dev/null & )

# Health-checks : un déploiement qui « réussit » mais laisse un service KO est pire
# que pas de déploiement. On vérifie explicitement et on sort en erreur sinon.
echo
fail=0
if wait_http "http://localhost:8800/health"; then
  echo "✓ API  : http://localhost:8800/health"
else
  echo "✗ API KO — voir /tmp/xmed-api.log"; fail=1
fi
if wait_http "http://localhost:3003/"; then
  echo "✓ Web  : http://localhost:3003  (ou http://<IP-serveur>:3003)"
else
  echo "✗ Web KO — voir /tmp/xmed-web.log"; fail=1
fi
echo "Logs : /tmp/xmed-api.log  /tmp/xmed-web.log  /tmp/xmed-web-build.log"
exit "$fail"
