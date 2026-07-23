// Garde d'authentification globale (convention Next 16 : proxy.ts, ex-middleware).
// Toutes les requêtes — pages ET relais /api/* vers FastAPI — doivent porter un
// ID token Firebase valide dans le cookie de session, vérifié cryptographiquement
// contre les clés publiques de Google (aucun appel Firebase Admin nécessaire).
// Seuls /login et les assets du framework restent publics.
import { NextResponse, type NextRequest } from "next/server";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { SESSION_COOKIE } from "@/lib/firebase";

const PROJECT_ID = process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "xmed-veille";

// Clés publiques de signature des ID tokens Firebase (mises en cache par jose).
const JWKS = createRemoteJWKSet(
  new URL(
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
  ),
);

// Optionnel : restreindre l'accès à une liste de comptes Google (emails séparés
// par des virgules dans XMED_ALLOWED_EMAILS). Vide = tout compte Google accepté.
const ALLOWED_EMAILS = (process.env.XMED_ALLOWED_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

type Session =
  | { verdict: "ok"; email: string; uid: string; name: string }
  | { verdict: "anonymous" | "forbidden" };

async function checkSession(req: NextRequest): Promise<Session> {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return { verdict: "anonymous" };
  try {
    const { payload } = await jwtVerify(token, JWKS, {
      issuer: `https://securetoken.google.com/${PROJECT_ID}`,
      audience: PROJECT_ID,
      algorithms: ["RS256"],
    });
    if (!payload.sub) return { verdict: "anonymous" };
    const email = String(payload.email ?? "").toLowerCase();
    if (ALLOWED_EMAILS.length > 0 && !ALLOWED_EMAILS.includes(email)) {
      return { verdict: "forbidden" };
    }
    return {
      verdict: "ok",
      email,
      uid: payload.sub,
      name: String(payload.name ?? ""),
    };
  } catch {
    // Jeton absent/expiré/falsifié : on retombe sur le parcours de connexion.
    return { verdict: "anonymous" };
  }
}

export async function proxy(req: NextRequest) {
  const session = await checkSession(req);
  const verdict = session.verdict;
  if (session.verdict === "ok") {
    // Identité vérifiée transmise à l'API (journal d'usage : qui fait quoi).
    // On ÉCRASE toujours le header : une valeur venue du navigateur serait de
    // l'usurpation, jamais relayée.
    const headers = new Headers(req.headers);
    headers.set("x-user-email", session.email);
    // UID Firebase : clé de rattachement du profil médecin (endpoints /me).
    headers.set("x-user-uid", session.uid);
    // Nom Google encodé (les headers HTTP ne transportent pas les accents).
    headers.set("x-user-name", encodeURIComponent(session.name));
    return NextResponse.next({ request: { headers } });
  }

  const { pathname, search } = req.nextUrl;

  // Les appels API reçoivent une erreur JSON (pas une page de login HTML).
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { detail: "Authentification requise." },
      { status: verdict === "forbidden" ? 403 : 401 },
    );
  }

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (verdict === "forbidden") {
    // Compte Google valide mais hors liste : la page de login affiche le refus.
    url.searchParams.set("denied", "1");
  } else {
    const next = pathname + search;
    if (next !== "/") url.searchParams.set("next", next);
  }
  return NextResponse.redirect(url);
}

export const config = {
  // Tout est protégé sauf la page de login, les assets Next (_next/) et la favicon.
  matcher: ["/((?!login|_next/|favicon\\.ico).*)"],
};
