"use client";

// Contexte d'authentification global : écoute la session Firebase, maintient le
// cookie de session lu par proxy.ts, et expose l'utilisateur + la déconnexion.
// Monté une seule fois dans le layout racine.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { onIdTokenChanged, signOut, type User } from "firebase/auth";
import { getFirebaseAuth, setSessionCookie } from "@/lib/firebase";

interface AuthState {
  /** Utilisateur Firebase connecté, ou null. */
  user: User | null;
  /** false tant que Firebase n'a pas restauré (ou infirmé) la session locale. */
  ready: boolean;
  /** Déconnecte puis renvoie sur /login. */
  signOutUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  ready: false,
  signOutUser: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const auth = getFirebaseAuth();
    // Se déclenche à la connexion, à la déconnexion et à chaque renouvellement
    // du jeton par le SDK : le cookie suit toujours le jeton courant.
    const unsub = onIdTokenChanged(auth, async (u) => {
      setSessionCookie(u ? await u.getIdToken() : null);
      setUser(u);
      setReady(true);
    });
    // Filet de sécurité : le cookie expire à 55 min ; on redemande un jeton
    // (rafraîchi par le SDK s'il approche de l'expiration) avant cette échéance.
    const timer = setInterval(
      () => {
        auth.currentUser?.getIdToken().then(setSessionCookie);
      },
      45 * 60 * 1000,
    );
    return () => {
      unsub();
      clearInterval(timer);
    };
  }, []);

  const signOutUser = useCallback(async () => {
    await signOut(getFirebaseAuth());
    setSessionCookie(null);
    // Navigation complète (pas router.push) pour repasser par proxy.ts.
    window.location.href = "/login";
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, signOutUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
