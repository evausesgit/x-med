// Page statique « Comment ça marche » : explication TECHNIQUE de la recherche
// PubMed + IA (v1 / v2), alignée sur docs/communication_recherche.md § 2 et
// ALGO_RECHERCHE.md. Server Component par défaut (aucun état, aucune
// interactivité) → rendu une fois, pas de JS côté client.
//
// Le contenu est de la prose technique dense (paragraphes + tableaux) : il vit
// dans deux composants complets (content.fr / content.en) plutôt que dans le
// catalogue de messages, où il aurait fallu le hacher en dizaines de clés au
// détriment de la relecture. La langue vient du cookie, comme partout ailleurs.
import type { Metadata } from "next";
import { translate } from "@/lib/locale";
import { requestLocale } from "@/lib/server-locale";
import ArchitectureEn from "./content.en";
import ArchitectureFr from "./content.fr";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await requestLocale();
  return {
    title: translate(locale, "meta.howItWorksTitle"),
    description: translate(locale, "meta.howItWorksDescription"),
  };
}

export default async function ArchitecturePage() {
  const locale = await requestLocale();
  return (
    <main className="container">
      {locale === "fr" ? <ArchitectureFr /> : <ArchitectureEn />}
    </main>
  );
}
