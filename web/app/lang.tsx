"use client";

// Langue d'affichage des articles (titre + résumé), partagée par la vue de
// recherche (page.tsx) et les recherches sauvegardées (recherches/*). C'est une
// préférence de l'app, persistée dans localStorage — pas un état de page. Quand
// l'utilisateur choisit le français, on traduit à la demande, en un seul appel
// par lot, et le cache global (table article_fr) sert les vues suivantes.
import { useCallback, useEffect, useState } from "react";
import { DeepHit, translateBatch, TranslationResult } from "@/lib/api";

export type DisplayLang = "fr" | "en";

const STORAGE_KEY = "xmed.displayLang";

// Défaut : français (produit FR-first pour des médecins francophones). Bascule en
// anglais = afficher l'original, coût nul.
export function useDisplayLang(): [DisplayLang, (l: DisplayLang) => void] {
  const [lang, setLangState] = useState<DisplayLang>("fr");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "fr" || saved === "en") setLangState(saved);
    } catch {
      // localStorage indisponible (SSR, navigation privée) : on garde le défaut.
    }
  }, []);

  const setLang = useCallback((l: DisplayLang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore : la préférence ne sera juste pas mémorisée.
    }
  }, []);

  return [lang, setLang];
}

// Sélecteur Français / English. Réutilise le style `.xmr-langtoggle` existant.
export function LanguageToggle({
  lang,
  onChange,
  busy = false,
}: {
  lang: DisplayLang;
  onChange: (l: DisplayLang) => void;
  busy?: boolean;
}) {
  return (
    <div className="xmr-langtoggle" role="group" aria-label="Langue d'affichage">
      <button
        type="button"
        className={lang === "fr" ? "on" : ""}
        disabled={busy}
        onClick={() => onChange("fr")}
      >
        {busy ? "Traduction…" : "Français"}
      </button>
      <button
        type="button"
        className={lang === "en" ? "on" : ""}
        disabled={busy}
        onClick={() => onChange("en")}
      >
        English
      </button>
    </div>
  );
}

export interface DisplayedHit {
  title: string;
  abstract: string | null;
  /** true si le texte FR affiché est bien une traduction (et pas un repli EN). */
  translated: boolean;
}

// Gère la traduction FR d'une liste d'articles selon la langue choisie : quand on
// passe en FR, traduit (en un seul appel) ceux qui n'ont pas encore de version FR,
// puis `resolve(hit)` rend le titre/résumé dans la bonne langue. En EN, ne touche
// à rien (aucun appel). Idempotent : ce qui est déjà traduit (cache snapshot ou
// appel précédent) n'est jamais retraduit.
export function useTranslatedHits(hits: DeepHit[], lang: DisplayLang) {
  const [extra, setExtra] = useState<Record<number, TranslationResult>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (lang !== "fr") return;
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
          if (alive) setErr(e instanceof Error ? e.message : "Échec de la traduction.");
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
      if (lang !== "fr") {
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
