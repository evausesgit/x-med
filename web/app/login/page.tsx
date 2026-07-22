"use client";

/* X-Med — page de connexion (design system « X-Med App », variante Clinique).
   Seule page publique du site : proxy.ts redirige ici toute requête sans jeton
   valide. Connexion par compte Google uniquement (Firebase Auth). Une fois le
   jeton posé en cookie, on repart vers la page demandée (?next=…) en navigation
   complète pour repasser par la garde serveur. */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  GoogleAuthProvider,
  getRedirectResult,
  onIdTokenChanged,
  signInWithPopup,
  signInWithRedirect,
  signOut,
} from "firebase/auth";
import { getFirebaseAuth, setSessionCookie } from "@/lib/firebase";

// Ne suit que des chemins internes : évite les redirections ouvertes via ?next=.
function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function frenchError(e: unknown): string | null {
  const code = (e as { code?: string })?.code ?? "";
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") {
    return null; // fermeture volontaire : pas une erreur à afficher
  }
  if (code === "auth/network-request-failed") {
    return "Connexion impossible : vérifiez votre accès réseau puis réessayez.";
  }
  if (code === "auth/unauthorized-domain") {
    return "Ce domaine n'est pas autorisé dans la configuration Firebase du projet.";
  }
  if (code === "auth/operation-not-allowed") {
    return "La connexion Google n'est pas activée sur le projet Firebase.";
  }
  return "La connexion a échoué. Réessayez, ou contactez l'équipe X-Med.";
}

function GoogleMark() {
  // « G » Google officiel, en SVG inline (pas de requête externe).
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

// Coquille de la carte : partagée entre le fallback Suspense (HTML prérendu,
// évite un écran blanc avant hydratation) et la page interactive.
function LoginCard({ children }: { children: React.ReactNode }) {
  return (
    <main className="xm-login">
      <div className="xm-login-card">
        <span className="xm-login-logo" aria-hidden="true">
          ✕
        </span>
        <div className="xm-login-wordmark">X&#8209;Med</div>
        <p className="xm-login-tagline">Explorez la recherche médicale</p>
        {children}
      </div>
    </main>
  );
}

function LoginInner() {
  const params = useSearchParams();
  const nextUrl = safeNext(params.get("next"));
  const denied = params.get("denied") === "1";

  // « checking » couvre la restauration de session Firebase au chargement :
  // on n'affiche pas le bouton tant qu'une session existante peut rediriger.
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deniedEmail, setDeniedEmail] = useState<string | null>(null);

  useEffect(() => {
    const auth = getFirebaseAuth();
    // Récupère l'issue d'un éventuel signInWithRedirect (repli sans popup).
    getRedirectResult(auth).catch((e) => setError(frenchError(e)));
    const unsub = onIdTokenChanged(auth, async (u) => {
      if (u && !denied) {
        setSessionCookie(await u.getIdToken());
        window.location.replace(nextUrl);
        return; // on quitte la page : inutile de réafficher quoi que ce soit
      }
      if (u && denied) setDeniedEmail(u.email);
      setChecking(false);
    });
    return unsub;
  }, [nextUrl, denied]);

  async function signIn() {
    setBusy(true);
    setError(null);
    const auth = getFirebaseAuth();
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    try {
      const cred = await signInWithPopup(auth, provider);
      setSessionCookie(await cred.user.getIdToken());
      window.location.replace(nextUrl);
    } catch (e) {
      const code = (e as { code?: string })?.code ?? "";
      if (code === "auth/popup-blocked") {
        // Popup bloquée par le navigateur : on repart en redirection complète.
        await signInWithRedirect(auth, provider);
        return;
      }
      setError(frenchError(e));
      setBusy(false);
    }
  }

  // Compte connecté mais hors liste d'accès : proposer de changer de compte.
  async function switchAccount() {
    const auth = getFirebaseAuth();
    await signOut(auth);
    setSessionCookie(null);
    window.location.replace("/login");
  }

  return (
    <LoginCard>
      <>
        {checking ? (
          <p className="xm-login-sub">Vérification de la session…</p>
        ) : denied && deniedEmail ? (
          <>
            <p className="xm-login-sub">
              Le compte <strong>{deniedEmail}</strong> n&apos;a pas accès à
              X&#8209;Med. Contactez l&apos;équipe pour être ajouté, ou
              connectez-vous avec un autre compte.
            </p>
            <button type="button" className="xm-login-btn" onClick={switchAccount}>
              <GoogleMark />
              Changer de compte
            </button>
          </>
        ) : (
          <>
            <p className="xm-login-sub">
              Connectez-vous pour accéder à la recherche, à vos profils et à
              votre digest personnalisé.
            </p>
            <button
              type="button"
              className="xm-login-btn"
              onClick={signIn}
              disabled={busy}
            >
              <GoogleMark />
              {busy ? "Connexion…" : "Continuer avec Google"}
            </button>
          </>
        )}

        {error && <p className="xm-login-err">{error}</p>}

        <p className="xm-login-foot">
          Accès protégé — vos recherches et votre profil restent privés.
        </p>
      </>
    </LoginCard>
  );
}

export default function LoginPage() {
  // useSearchParams exige une frontière Suspense au prérendu (Next 16). Le
  // fallback reprend la carte pour que le HTML statique ne soit jamais vide.
  return (
    <Suspense
      fallback={
        <LoginCard>
          <p className="xm-login-sub">Vérification de la session…</p>
        </LoginCard>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
