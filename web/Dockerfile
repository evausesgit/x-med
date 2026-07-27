# Front X-Med (Next 16) — image pour le compose app (docker-compose.app.yml).
#
# npm (pas bun) : décision figée de PLAN_EXECUTION_COMPOSE.md — pas de
# changement d'outillage pendant la migration d'infra.
#
# Port interne : 3000 — `npm run start` lance `next start -H 0.0.0.0 -p
# ${PORT:-3000}` (web/package.json). C'est le port que Coolify route ; aucun
# port n'est publié sur l'hôte.
#
# ⚠️ API_INTERNAL_URL doit être posée AVANT `npm run build` : les rewrites de
# next.config.ts (`/api/* → ${API_INTERNAL_URL}/*`) sont FIGÉS au build dans
# le routes-manifest. Dans le compose, `api` est un nom DNS stable — la même
# image pointe vers « son » API en prod comme dans chaque preview.

FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

ENV API_INTERNAL_URL=http://api:8800 \
    NEXT_TELEMETRY_DISABLED=1

COPY . .
RUN npm run build


# Runtime : mêmes node_modules que le build (réutilisés tels quels — les
# devDependencies du projet se réduisent à typescript + @types, quelques Mo ;
# pas d'`output: standalone` ni de second `npm ci`, sobriété sans acrobatie).
FROM node:22-bookworm-slim

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    API_INTERNAL_URL=http://api:8800 \
    NEXT_TELEMETRY_DISABLED=1

# --chown=node:node sur ce que le serveur Next doit pouvoir écrire au
# runtime (.next/cache notamment) — le process tourne en `node`, pas root.
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
COPY --chown=node:node package.json next.config.ts tsconfig.json proxy.ts ./

# Utilisateur non-root fourni par l'image node (uid 1000).
USER node

EXPOSE 3000

CMD ["npm", "run", "start"]
