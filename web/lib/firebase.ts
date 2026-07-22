// Client Firebase (SDK web) — authentification Google uniquement.
// La config ci-dessous est publique par conception (elle identifie le projet
// Firebase « xmed-veille », elle ne confère aucun droit) : la protection réelle
// vient de la vérification du jeton côté serveur (proxy.ts). Les valeurs sont
// surchargeables par variables d'env NEXT_PUBLIC_* si le projet Firebase change.
import { getApps, initializeApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

const config = {
  apiKey:
    process.env.NEXT_PUBLIC_FIREBASE_API_KEY ??
    "AIzaSyD9hn0rmJ8Avr5MpvlyaxnrK_HqBcy0dqo",
  authDomain:
    process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "xmed-veille.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "xmed-veille",
  appId:
    process.env.NEXT_PUBLIC_FIREBASE_APP_ID ??
    "1:804073128410:web:00765b2a50ef91c34180e3",
};

// Initialisation paresseuse : à n'appeler que côté navigateur (dans un effet ou
// un gestionnaire d'événement), jamais au chargement d'un module rendu en SSR.
export function getFirebaseAuth(): Auth {
  const app = getApps()[0] ?? initializeApp(config);
  return getAuth(app);
}

// Cookie de session lu par proxy.ts : il transporte l'ID token Firebase courant.
// Durée de vie 55 min < validité du jeton (60 min) pour que le serveur ne voie
// (presque) jamais un jeton expiré ; le SDK et l'AuthProvider le renouvellent.
export const SESSION_COOKIE = "xmed_session";

export function setSessionCookie(token: string | null) {
  if (typeof document === "undefined") return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = token
    ? `${SESSION_COOKIE}=${token}; path=/; max-age=3300; SameSite=Lax${secure}`
    : `${SESSION_COOKIE}=; path=/; max-age=0; SameSite=Lax${secure}`;
}
