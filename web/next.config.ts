import type { NextConfig } from "next";

// L'API FastAPI tourne en local sur le port 8800 (cf. CLAUDE.md ; le port 8000
// est pris par un autre service). On la relaie via le serveur Next pour que le
// navigateur n'ait jamais à joindre l'API directement (sinon "localhost"
// pointerait sur la machine du client, pas le serveur).
const API_INTERNAL = process.env.API_INTERNAL_URL || "http://127.0.0.1:8800";

const nextConfig: NextConfig = {
  // Next 16 bloque les requêtes de dev venant d'une autre origine que localhost.
  // On autorise l'accès distant (IP publique du serveur) en mode dev.
  allowedDevOrigins: ["65.108.202.130"],
  // `next start` gzippe les réponses par défaut. La compression doit accumuler
  // le flux avant d'émettre, ce qui BUFFERISE le SSE de /search/.../stream : le
  // navigateur ne voit alors que la roue, puis tout le déroulé d'un coup à la fin.
  // On laisse le reverse-proxy (Traefik/Coolify) compresser le reste à la place.
  compress: false,
  async headers() {
    // Empêche un proxy (nginx/Traefik) de bufferiser les réponses streamées.
    // FastAPI pose déjà cet en-tête côté API ; on le repose ici pour qu'il
    // survive au passage par le serveur Next (rewrites /api/* → FastAPI).
    return [
      {
        source: "/api/:path*",
        headers: [{ key: "X-Accel-Buffering", value: "no" }],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_INTERNAL}/:path*`,
      },
    ];
  },
  async redirects() {
    // La visite guidée est une page statique (public/recherche-guidee/index.html).
    // Next sert les fichiers publics par chemin exact et, trailingSlash=false oblige,
    // renvoie un 308 sur le dossier /recherche-guidee/ → 404. On redirige donc
    // l'URL « dossier » vers index.html (les assets relatifs s'y résolvent bien).
    return [
      {
        source: "/recherche-guidee",
        destination: "/recherche-guidee/index.html",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
