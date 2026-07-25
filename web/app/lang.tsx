"use client";

// Langue d'affichage des ARTICLES (titre + résumé), partagée par la vue de
// recherche (page.tsx) et les recherches sauvegardées (recherches/*).
//
// Deux niveaux, comme demandé côté produit :
//   • par défaut, les articles suivent la langue du COMPTE (préférence de
//     profil) — la traduction est donc automatique, sans rien demander ;
//   • la bascule présente sur chaque carte est une dérogation « à la demande »,
//     mémorisée localement et effacée dès qu'on change la langue du compte.
//
// L'anglais est la langue SOURCE des abstracts PubMed : l'afficher ne coûte
// aucun appel. Passer au français déclenche une traduction en un seul appel par
// lot, mise en cache globalement (table article_fr) pour les vues suivantes.
import { useCallback, useEffect, useState } from "react";
import { DeepHit, translateBatch, TranslationResult } from "@/lib/api";
import { useT } from "@/lib/i18n";
import {
  readDisplayLangOverride,
  writeDisplayLangOverride,
  type Locale,
} from "@/lib/locale";

export type DisplayLang = Locale;

// Le cache de traduction actuel (article_fr) ne stocke que le français ; en
// anglais on sert l'original. Ajouter une 3e langue demandera d'étendre le
// stockage ET l'endpoint /translate — d'où ce test explicite plutôt qu'un
// « tout sauf l'anglais » qui laisserait croire que ça marche déjà.
function isTranslatable(lang: DisplayLang): boolean {
  return lang === "fr";
}

/**
 * Langue d'affichage courante et façon d'en déroger ponctuellement.
 * Retourne `[lang, setLang]` : `lang` vaut la dérogation si elle existe,
 * sinon la langue du compte.
 */
export function useDisplayLang(): [DisplayLang, (l: DisplayLang) => void] {
  const { locale } = useT();
  const [override, setOverride] = useState<DisplayLang | null>(null);

  // Au montage : on récupère la dérogation éventuelle. Quand la langue du
  // compte change, le sélecteur de langue a déjà effacé cette dérogation
  // (lib/i18n.tsx) : relire donne `null`, donc on retombe sur le compte.
  useEffect(() => {
    setOverride(readDisplayLangOverride());
  }, [locale]);

  const setLang = useCallback((l: DisplayLang) => {
    setOverride(l);
    writeDisplayLangOverride(l);
  }, []);

  return [override ?? locale, setLang];
}

// Sélecteur Français / English d'une carte de résultat.
export function LanguageToggle({
  lang,
  onChange,
  busy = false,
}: {
  lang: DisplayLang;
  onChange: (l: DisplayLang) => void;
  busy?: boolean;
}) {
  const { t } = useT();
  return (
    <div className="xmr-langtoggle" role="group" aria-label={t("lang.groupLabel")}>
      <button
        type="button"
        className={lang === "fr" ? "on" : ""}
        disabled={busy}
        onClick={() => onChange("fr")}
      >
        {busy ? t("lang.translating") : t("lang.french")}
      </button>
      <button
        type="button"
        className={lang === "en" ? "on" : ""}
        disabled={busy}
        onClick={() => onChange("en")}
      >
        {t("lang.english")}
      </button>
    </div>
  );
}

export interface DisplayedHit {
  title: string;
  abstract: string | null;
  /** true si le texte affiché est bien une traduction (et pas un repli EN). */
  translated: boolean;
}

// Gère la traduction d'une liste d'articles selon la langue d'affichage : quand
// celle-ci demande une traduction, traduit (en un seul appel) ceux qui n'en ont
// pas encore, puis `resolve(hit)` rend le titre/résumé dans la bonne langue. En
// anglais, ne touche à rien (aucun appel). Idempotent : ce qui est déjà traduit
// (cache snapshot ou appel précédent) n'est jamais retraduit.
export function useTranslatedHits(hits: DeepHit[], lang: DisplayLang) {
  const { t } = useT();
  const [extra, setExtra] = useState<Record<number, TranslationResult>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!isTranslatable(lang)) return;
    const need = hits.filter(
      (h) =>
        h.abstract && // rien à traduire sans abstract source
        !h.abstract_fr &&
        !extra[h.pmid]?.abstract_fr,
    );
    if (need.length === 0) return;

    let alive = true;
    setBusy(true);
    setErr(null);
    // Petit délai avant de traduire : sur la page de recherche, le flux SSE
    // traduit déjà les premiers résultats côté serveur et pousse les `abstract_fr`
    // peu après. Attendre laisse ces traductions arriver et réduit `need`, ce qui
    // évite de retraduire en double les mêmes articles (coût). Sur les recherches
    // sauvegardées (pas de SSE), le délai est imperceptible.
    const timer = setTimeout(() => {
      translateBatch(
        need.map((h) => ({ pmid: h.pmid, title: h.title, abstract: h.abstract })),
      )
        .then((map) => {
          if (!alive) return;
          setExtra((prev) => {
            const next = { ...prev };
            for (const [pmid, tr] of Object.entries(map)) next[Number(pmid)] = tr;
            return next;
          });
        })
        .catch((e) => {
          if (alive)
            setErr(e instanceof Error ? e.message : t("lang.translationFailed"));
        })
        .finally(() => {
          if (alive) setBusy(false);
        });
    }, 500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // `extra` est volontairement hors deps : il évolue *après* la traduction et
    // on ne veut pas relancer l'effet en boucle. On dépend de la liste + la langue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, hits]);

  const resolve = useCallback(
    (h: DeepHit): DisplayedHit => {
      if (!isTranslatable(lang)) {
        return { title: h.title, abstract: h.abstract, translated: false };
      }
      const o = extra[h.pmid];
      const titleFr = h.title_fr || o?.title_fr || null;
      const abstractFr = h.abstract_fr || o?.abstract_fr || null;
      return {
        title: titleFr || h.title,
        abstract: abstractFr || h.abstract,
        translated: Boolean(abstractFr),
      };
    },
    [lang, extra],
  );

  return { resolve, busy, err };
}
