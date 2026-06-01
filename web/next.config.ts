import type { NextConfig } from "next";

// L'API FastAPI tourne en local dans le même conteneur (port 8000). On la relaie via
// le serveur Next pour que le navigateur n'ait jamais à joindre l'API directement
// (sinon "localhost" pointerait sur la machine du client, pas le serveur).
const API_INTERNAL = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Next 16 bloque les requêtes de dev venant d'une autre origine que localhost.
  // On autorise l'accès distant (IP publique du serveur) en mode dev.
  allowedDevOrigins: ["65.108.202.130"],
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
