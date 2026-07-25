// Résolution de la langue côté SERVEUR (layout + pages statiques).
//
// Fichier séparé de lib/locale.ts : `next/headers` n'existe que sur le serveur,
// alors que lib/locale.ts est aussi importé par des composants client.
//
// Lire le cookie ici (plutôt qu'à l'hydratation) évite un « flash » d'anglais
// chez un utilisateur francophone et donne le bon `<html lang>`. Le profil du
// médecin reste la source de vérité : le provider corrige au montage si le
// compte dit autre chose (voir lib/i18n.tsx).
import { cookies } from "next/headers";
import { DEFAULT_LOCALE, isLocale, LOCALE_COOKIE, type Locale } from "./locale";

export async function requestLocale(): Promise<Locale> {
  const value = (await cookies()).get(LOCALE_COOKIE)?.value;
  return isLocale(value) ? value : DEFAULT_LOCALE;
}
