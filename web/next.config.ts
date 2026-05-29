import type { NextConfig } from "next";

// L'API FastAPI tourne en local sur le serveur (port 8800). On la relaie via
// le serveur Next pour que le navigateur n'ait jamais à joindre 8800 directement
// (sinon "localhost" pointerait sur la machine du client, pas le serveur).
const API_INTERNAL = process.env.API_INTERNAL_URL || "http://localhost:8800";

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
};

export default nextConfig;
