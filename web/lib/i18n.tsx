"use client";

// Couche React de l'i18n : contexte, hook `useT()` et sélecteur de langue.
//
// D'où vient la langue, par ordre d'autorité :
//   1. le PROFIL du médecin connecté (`doctors.language`) — la préférence suit
//      le compte, donc l'appareil n'a pas d'importance ;
//   2. le cookie `xmed.locale` — lu par le layout serveur, ce qui évite tout
//      « flash » d'anglais avant l'hydratation et donne le bon `<html lang>` ;
//   3. l'anglais, langue principale du produit.
//
// Changer de langue écrit le cookie ET pousse la préférence sur le profil.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getMe, updateMyLanguage } from "./api";
import { SESSION_COOKIE } from "./firebase";
import {
  clearDisplayLangOverride,
  DEFAULT_LOCALE,
  isLocale,
  localeTag,
  setActiveLocale,
  translate,
  translatePlural,
  writeLocaleCookie,
  type Locale,
  type MessageKey,
  type PluralKey,
  type Vars,
} from "./locale";

interface I18nState {
  locale: Locale;
  /** Locale BCP-47 (`fr-FR`, `en-US`) pour Intl et la synthèse vocale. */
  tag: string;
  /** Traduit une clé simple : `t("search.hero")`, `t("common.apiError", { status })`. */
  t: (key: MessageKey, vars?: Vars) => string;
  /** Traduit un libellé au pluriel : `tp("saved.count", n)`. */
  tp: (key: PluralKey, count: number, vars?: Vars) => string;
  setLocale: (locale: Locale) => void;
}

const I18nContext = createContext<I18nState | null>(null);

export function I18nProvider({
  initialLocale,
  children,
}: {
  /** Langue résolue côté serveur depuis le cookie (voir app/layout.tsx). */
  initialLocale: Locale;
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  // L'utilisateur a-t-il déjà choisi explicitement pendant cette visite ? Si
  // oui, la langue lue sur le profil ne doit plus lui passer devant (la requête
  // /me peut arriver après son clic).
  const chosenRef = useRef(false);

  // Miroir de module pour les traductions hors React (lib/api.ts).
  setActiveLocale(locale);

  const apply = useCallback((next: Locale) => {
    setLocaleState(next);
    setActiveLocale(next);
    writeLocaleCookie(next);
    if (typeof document !== "undefined") {
      document.documentElement.lang = next;
    }
  }, []);

  // Au montage : la préférence du compte fait foi (elle suit le médecin d'un
  // appareil à l'autre). Silencieux si personne n'est connecté (page de
  // connexion, session expirée) ou si aucun profil n'est rattaché.
  useEffect(() => {
    let alive = true;
    // Sans cookie de session, /api/me répondrait 401 à coup sûr (la page de
    // connexion est publique) : on s'épargne un aller-retour perdu.
    if (!document.cookie.includes(`${SESSION_COOKIE}=`)) return;
    getMe()
      .then((doctor) => {
        if (!alive || chosenRef.current || !doctor) return;
        if (isLocale(doctor.language) && doctor.language !== locale) {
          apply(doctor.language);
        }
      })
      .catch(() => {
        // Non connecté ou API indisponible : on garde cookie/défaut.
      });
    return () => {
      alive = false;
    };
    // Volontairement au montage seulement : `locale` est lu dans la closure
    // mais un changement de langue ne doit pas relancer la lecture du profil.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apply]);

  const setLocale = useCallback(
    (next: Locale) => {
      if (next === locale) return;
      chosenRef.current = true;
      apply(next);
      // Choisir sa langue de compte annule la dérogation d'affichage posée
      // ponctuellement sur les cartes de résultats.
      clearDisplayLangOverride();
      // Best-effort : la préférence est déjà appliquée localement, un échec
      // réseau ne doit pas bloquer l'interface.
      void updateMyLanguage(next).catch(() => {});
    },
    [locale, apply],
  );

  const value = useMemo<I18nState>(
    () => ({
      locale,
      tag: localeTag(locale),
      t: (key, vars) => translate(locale, key, vars),
      tp: (key, count, vars) => translatePlural(locale, key, count, vars),
      setLocale,
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): I18nState {
  const ctx = useContext(I18nContext);
  if (ctx) return ctx;
  // Repli si un composant est monté hors provider (test isolé, page d'erreur) :
  // l'anglais plutôt qu'un crash.
  return {
    locale: DEFAULT_LOCALE,
    tag: localeTag(DEFAULT_LOCALE),
    t: (key, vars) => translate(DEFAULT_LOCALE, key, vars),
    tp: (key, count, vars) => translatePlural(DEFAULT_LOCALE, key, count, vars),
    setLocale: () => {},
  };
}

/** Sélecteur de langue de l'interface (barre de navigation). */
export function LocaleSwitcher() {
  const { locale, setLocale, t } = useT();
  const next: Locale = locale === "fr" ? "en" : "fr";
  return (
    <button
      type="button"
      className="xm-lang"
      onClick={() => setLocale(next)}
      title={t(next === "fr" ? "nav.switchToFrench" : "nav.switchToEnglish")}
      aria-label={t("nav.language")}
    >
      {locale.toUpperCase()}
    </button>
  );
}
