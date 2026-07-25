// Noyau i18n SANS React ni appel réseau : types, catalogues, résolution des
// clés, et « langue active » de module.
//
// Ce fichier est volontairement indépendant de React et de lib/api : la couche
// React (lib/i18n.tsx) et les fonctions d'API (lib/api.ts) l'importent toutes
// les deux, et un import croisé entre elles créerait un cycle.
//
// L'anglais est la langue PRINCIPALE : c'est le catalogue de référence (en.ts)
// et le repli quand une clé manque.

import { en, type Messages } from "./messages/en";
import { fr } from "./messages/fr";

export const LOCALES = ["en", "fr"] as const;
export type Locale = (typeof LOCALES)[number];

/** Langue du produit par défaut (nouveaux comptes, visiteur sans préférence). */
export const DEFAULT_LOCALE: Locale = "en";

/** Cookie de préférence : lu côté serveur (layout) ET écrit côté client. */
export const LOCALE_COOKIE = "xmed.locale";

const CATALOGS: Record<Locale, Messages> = { en, fr };

export function isLocale(v: unknown): v is Locale {
  return typeof v === "string" && (LOCALES as readonly string[]).includes(v);
}

/** Locale BCP-47 pour Intl (dates, nombres). */
export function localeTag(locale: Locale): string {
  return locale === "fr" ? "fr-FR" : "en-US";
}

/** Étiquette de langue pour la synthèse vocale du navigateur. */
export const speechTag = localeTag;

// ---------- Clés typées ----------

/** Libellé qui varie au pluriel (voir `tp`). */
export interface PluralForms {
  one: string;
  other: string;
}

type StringPaths<T> = {
  [K in keyof T & string]: T[K] extends string
    ? K
    : T[K] extends PluralForms
      ? never
      : `${K}.${StringPaths<T[K]>}`;
}[keyof T & string];

type PluralPaths<T> = {
  [K in keyof T & string]: T[K] extends string
    ? never
    : T[K] extends PluralForms
      ? K
      : `${K}.${PluralPaths<T[K]>}`;
}[keyof T & string];

/** Clés pointant sur un texte simple, ex. `"search.hero"`. */
export type MessageKey = StringPaths<Messages>;
/** Clés pointant sur un libellé au pluriel, ex. `"saved.count"`. */
export type PluralKey = PluralPaths<Messages>;

export type Vars = Record<string, string | number>;

/**
 * Signature de la fonction de traduction (`t` du hook `useT`). Sert aux
 * fonctions utilitaires pures qui produisent du texte visible : plutôt que
 * d'appeler un hook (impossible hors composant), elles reçoivent `t` en
 * argument depuis leur appelant.
 */
export type Translate = (key: MessageKey, vars?: Vars) => string;

// ---------- Résolution ----------

function lookup(locale: Locale, key: string): unknown {
  let node: unknown = CATALOGS[locale];
  for (const part of key.split(".")) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

/** Remplace les variables `{nom}` ; une variable absente est laissée telle quelle. */
function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

function missing(locale: Locale, key: string): string {
  if (process.env.NODE_ENV !== "production") {
    console.warn(`[i18n] clé manquante « ${key} » (${locale})`);
  }
  return key;
}

/** Traduit une clé simple. Repli sur l'anglais si la clé manque dans la langue. */
export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  const value = lookup(locale, key) ?? lookup(DEFAULT_LOCALE, key);
  if (typeof value !== "string") return missing(locale, key);
  return interpolate(value, vars);
}

/**
 * Traduit un libellé au pluriel. Règle volontairement simple (anglais et
 * français se comportent pareil ici : « 0 » et « 1 » au singulier en français,
 * seul « 1 » en anglais — d'où le test sur la langue).
 * `count` est injecté automatiquement comme variable `{count}`.
 */
export function translatePlural(
  locale: Locale,
  key: PluralKey,
  count: number,
  vars?: Vars,
): string {
  const value = lookup(locale, key) ?? lookup(DEFAULT_LOCALE, key);
  if (value === null || typeof value !== "object") return missing(locale, key);
  const forms = value as PluralForms;
  const singular = locale === "fr" ? Math.abs(count) < 2 : Math.abs(count) === 1;
  return interpolate(singular ? forms.one : forms.other, { count, ...vars });
}

// ---------- Langue active de module ----------
//
// Certaines fonctions non-React ont besoin de traduire (messages d'erreur de
// lib/api.ts, par exemple). Elles n'ont pas accès au contexte React : le
// provider tient donc à jour cette valeur de module, qui n'est qu'un MIROIR de
// l'état React — jamais la source de vérité.

let activeLocale: Locale = DEFAULT_LOCALE;

export function getActiveLocale(): Locale {
  return activeLocale;
}

export function setActiveLocale(locale: Locale): void {
  activeLocale = locale;
}

/** Traduction hors composant React (voir `getActiveLocale`). */
export function tr(key: MessageKey, vars?: Vars): string {
  return translate(activeLocale, key, vars);
}

// ---------- Cookie (client) ----------

/** Lit la préférence depuis le cookie du navigateur (null si absent/inconnu). */
export function readLocaleCookie(): Locale | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${LOCALE_COOKIE}=([^;]*)`),
  );
  const value = match ? decodeURIComponent(match[1]) : null;
  return isLocale(value) ? value : null;
}

/** Persiste la préférence : le layout serveur la relira au prochain rendu. */
export function writeLocaleCookie(locale: Locale): void {
  if (typeof document === "undefined") return;
  const oneYear = 60 * 60 * 24 * 365;
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${oneYear}; SameSite=Lax`;
}

// ---------- Langue d'affichage des articles (dérogation ponctuelle) ----------
//
// Par défaut, titres et résumés s'affichent dans la langue du compte : c'est la
// préférence de profil qui décide, et la traduction est automatique. La bascule
// présente sur chaque carte de résultat est une dérogation « à la demande » —
// mémorisée pour ne pas la reposer à chaque page, mais effacée dès que
// l'utilisateur change la langue de son compte (son intention est alors nette).

const DISPLAY_LANG_KEY = "xmed.displayLang";

export function readDisplayLangOverride(): Locale | null {
  try {
    const saved = localStorage.getItem(DISPLAY_LANG_KEY);
    return isLocale(saved) ? saved : null;
  } catch {
    // localStorage indisponible (SSR, navigation privée) : pas de dérogation.
    return null;
  }
}

export function writeDisplayLangOverride(locale: Locale): void {
  try {
    localStorage.setItem(DISPLAY_LANG_KEY, locale);
  } catch {
    // ignore : la dérogation ne sera juste pas mémorisée.
  }
}

export function clearDisplayLangOverride(): void {
  try {
    localStorage.removeItem(DISPLAY_LANG_KEY);
  } catch {
    // ignore.
  }
}
