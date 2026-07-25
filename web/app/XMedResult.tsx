"use client";

/* X-Med — carte de résultat partagée (design system « X-Med App »).
   Portée depuis XMedResult.dc.html. Sert la page de recherche ET le digest pour
   qu'ils parlent le même langage : anneau de pertinence, badge de preuve, chips
   MeSH, barre d'action (résumé/abstract, PubMed, écouter), zone repliée.

   Les données réelles (DeepHit, résultats sémantiques…) n'ont pas toujours
   d'anneau (mode mots-clés), de temps de lecture, ni de « pourquoi » : ces
   éléments sont OPTIONNELS et la carte se dégrade proprement. Le contenu de la
   zone repliée (abstract, traduction à la demande FR/EN) est fourni en
   `children` pour que chaque appelant garde sa logique. */

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";
import { localeTag, type Locale, type Translate } from "@/lib/locale";

export type Tier = "high" | "mid" | "low" | "off";

/** Pertinence d'un résultat. Absente en mode « Mots-clés / MeSH » : pas d'anneau. */
export interface Relevance {
  /** remplissage de l'anneau, 0–100 */
  pct: number;
  tier: Tier;
  /** libellé de la pastille (« Très pertinent »…) */
  label: string;
  /** texte affiché au centre de l'anneau (« 83 % »…) — défaut : pct + % */
  text?: string;
  /** infobulle (détail du score) */
  title?: string;
}

export interface XMedResultProps {
  rank: number;
  title: string;
  journal?: string | null;
  year?: number | null;
  level?: number | null;
  relevance?: Relevance;
  /** « apport » de l'article (ce qu'il apporte au lecteur). Affiché en ligne
      surlignée sous le journal, sans rétrograder le titre (qui reste le héros). */
  contribution?: string | null;
  /** actions supplémentaires injectées dans la barre d'action (ex. « Analyse
      critique »). Rendues avant les actions standard. */
  extraActions?: React.ReactNode;
  /** étiquette de provenance (« A · PubMed + B · local »…) */
  sourceTag?: string | null;
  pubmedUrl: string;
  /** termes MeSH (chips toujours visibles) */
  mesh?: string[];
  /** titre source (EN) affiché en tête de la zone repliée */
  sourceTitle?: string | null;
  /** temps de lecture estimé, ex. « 4 min » (omis si absent) */
  readTime?: string | null;
  /** légende sous l'anneau */
  ringCaption?: string;
  /** met la carte en avant (liseré or « ★ Le plus pertinent ») */
  featured?: boolean;
  /** puces « Résumé IA » (panneau latéral dans la zone repliée) */
  why?: string[];
  /** texte lu à voix haute (bouton « Écouter ») — omis si absent */
  spoken?: string | null;
  /** langue du texte lu (défaut : langue de l'interface) */
  spokenLang?: Locale;
  /** libellé de la zone repliée (défaut « Résumé & abstract ») */
  revealLabel?: string;
  /** nœud supplémentaire dans l'en-tête replié (ex. bascule FR/EN du digest) */
  revealHead?: React.ReactNode;
  /** classe du conteneur du corps replié : « xmr-abstract » (défaut, texte brut)
      ou « xmr-sections » (résumé structuré Contexte/Méthodes/Résultats/Conclusion) */
  revealBodyClassName?: string;
  /** contenu de la zone repliée (abstract, sections, toggle FR/EN…) */
  children?: React.ReactNode;
}

const EV: Record<number, { labelKey: Parameters<Translate>[0]; cls: string }> = {
  1: { labelKey: "result.evidence1", cls: "xmr-ev1" },
  2: { labelKey: "result.evidence2", cls: "xmr-ev2" },
  3: { labelKey: "result.evidence3", cls: "xmr-ev3" },
  4: { labelKey: "result.evidence4", cls: "xmr-ev4" },
};

// Couleurs de la pastille de pertinence selon le palier (cf. design tier()).
// Variante « Clinique » : le palier « high » reprend le bleu de marque (comme
// l'accent vert le faisait dans la variante éditoriale) ; « mid » passe au
// sarcelle pour rester net à l'œil malgré la présence du bleu partout ailleurs
// (boutons, liens, anneau) ; « off » garde l'ambre, signal universel d'alerte.
const TIER_CHIP: Record<Tier, { bg: string; fg: string; dot: string }> = {
  high: { bg: "#dbe8fd", fg: "#1d4ed8", dot: "#2563eb" },
  mid: { bg: "#dcf3f2", fg: "#0e6377", dot: "#14919b" },
  low: { bg: "#eef1f6", fg: "#57647a", dot: "#94a3b8" },
  off: { bg: "#f6ead9", fg: "#8a5a1c", dot: "#c79a4e" },
};

const ARROW = (
  <svg viewBox="0 0 24 24">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
const PUB = (t: string) => "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(t);

// Synthèse vocale navigateur (réutilisée du digest). La voix suit la langue du
// texte AFFICHÉ, pas celle de l'interface : lire un abstract anglais avec une
// voix française le rendrait incompréhensible.
const TTS = {
  ok: typeof window !== "undefined" && "speechSynthesis" in window,
  speak(text: string, locale: Locale, onend: () => void) {
    if (!this.ok) {
      setTimeout(onend, 50);
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = localeTag(locale);
    const v = (window.speechSynthesis.getVoices() || []).find((x) =>
      x.lang?.toLowerCase().startsWith(locale),
    );
    if (v) u.voice = v;
    u.onend = onend;
    u.onerror = onend;
    window.speechSynthesis.speak(u);
  },
  stop() {
    if (this.ok) window.speechSynthesis.cancel();
  },
};

// Pertinence codex → format de carte. Le palier vient du score 0–3 (stable) ;
// l'anneau affiche le pourcentage fin `relevancePct` 0–100 quand il est dispo
// (sinon repli sur le 0–3 — recherches sauvegardées antérieures sans ce champ).
export function deepRelevance(
  score: number,
  relevancePct: number | null | undefined,
  // `t` est passé par l'appelant : cette fonction est pure (pas un composant),
  // elle ne peut donc pas lire le contexte i18n elle-même.
  t: Translate,
): Relevance {
  const pct =
    relevancePct != null
      ? Math.max(0, Math.min(100, Math.round(relevancePct)))
      : Math.round((score / 3) * 100);
  const tier: Tier = score >= 3 ? "high" : score >= 2 ? "mid" : "low";
  const label = t(
    score >= 3 ? "result.tierHigh" : score >= 2 ? "result.tierMid" : "result.tierLow",
  );
  const title =
    relevancePct != null
      ? t("result.relevanceTitle", { pct, score })
      : t("result.relevanceTitleShort", { score });
  return { pct, tier, label, title };
}

// Découpe un abstract « Label : texte » par ligne (Contexte/Méthodes/Résultats/
// Conclusion ou Background/Methods/…) en sections pour le « Résumé structuré ».
// Un abstract non structuré (paragraphe unique, sans étiquette) donne UNE section
// en texte brut — pas de mise en avant « conclusion ». La dernière section d'un
// abstract réellement structuré (plusieurs lignes) est mise en avant (or).
export function abstractSections(
  abstract: string,
): { label: string; text: string; concl: boolean }[] {
  const lines = abstract
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.map((line, i) => {
    const sep = line.indexOf(":");
    const hasLabel = sep > 0 && sep < 24;
    return {
      label: hasLabel ? line.slice(0, sep).trim() : "",
      text: hasLabel ? line.slice(sep + 1).trim() : line,
      concl: lines.length > 1 && i === lines.length - 1,
    };
  });
}

// Rendu « Résumé structuré » partagé par le digest et la recherche : à fournir en
// `children` de la carte avec `revealBodyClassName="xmr-sections"`. L'étiquette
// « traduit en … » n'apparaît que pour un abstract réellement traduit.
export function StructuredAbstract({
  abstract,
  translated,
  lang,
}: {
  abstract: string;
  translated?: boolean;
  /** Langue du texte affiché (nommée dans l'étiquette de traduction). */
  lang?: Locale;
}) {
  const { t, locale } = useT();
  const shown = lang ?? locale;
  return (
    <>
      {translated && (
        <div className="abstract-fr-label" style={{ marginBottom: 8 }}>
          📄{" "}
          {t("lang.translatedLabel", {
            language: t(`lang.languageName.${shown}`),
          })}
        </div>
      )}
      {abstractSections(abstract).map((s, i) => (
        <div key={i}>
          {s.label && (
            <span className={`xmr-section-label ${s.concl ? "concl" : ""}`}>{s.label}</span>
          )}
          <span className={`xmr-section-text ${s.concl ? "concl" : ""}`}>{s.text}</span>
        </div>
      ))}
    </>
  );
}

export default function XMedResult({
  rank,
  title,
  journal,
  year,
  level,
  relevance,
  contribution,
  extraActions,
  sourceTag,
  pubmedUrl,
  mesh,
  sourceTitle,
  readTime,
  ringCaption,
  featured,
  why,
  spoken,
  spokenLang,
  revealLabel,
  revealHead,
  revealBodyClassName = "xmr-abstract",
  children,
}: XMedResultProps) {
  const { t, locale } = useT();
  const [open, setOpen] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const caption = ringCaption ?? t("result.ringCaption");
  const revealTitle = revealLabel ?? t("result.defaultRevealLabel");

  // Anneau : anime le remplissage 0 → pct.
  const pct = relevance?.pct ?? 0;
  const [ringPct, setRingPct] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setRingPct(pct), 200);
    return () => clearTimeout(t);
  }, [pct]);

  useEffect(() => () => TTS.stop(), []);

  const hasReveal = Boolean(children) || (why && why.length > 0);
  const ev = level ? EV[level] : null;
  const chip = relevance ? TIER_CHIP[relevance.tier] : null;
  const meshShown = (mesh ?? []).slice(0, 6);

  // Clic sur la carte (hors bouton/lien) : déplie/replie.
  const wrapRef = useRef<HTMLElement>(null);
  const cardClick = (e: React.MouseEvent) => {
    if (!hasReveal) return;
    if (!(e.target as HTMLElement).closest("button, a, input, select")) setOpen((o) => !o);
  };

  function toggleSpeak() {
    if (!spoken) return;
    if (speaking) {
      TTS.stop();
      setSpeaking(false);
      return;
    }
    setSpeaking(true);
    TTS.speak(spoken, spokenLang ?? locale, () => setSpeaking(false));
  }

  return (
    <article ref={wrapRef} className={`xmr-card ${featured ? "featured" : ""}`} onClick={cardClick}>
      {featured && <div className="xmr-feat-kicker">{t("result.featured")}</div>}

      <div className={`xmr-grid ${relevance ? "" : "no-ring"}`}>
        <div className="xmr-head">
          <div className="xmr-tags-line">
            <span className="xmr-no">{String(rank).padStart(2, "0")}</span>
            {relevance && chip && (
              <span
                className="xmr-tierchip"
                style={{ background: chip.bg, color: chip.fg }}
              >
                <span className="dot" style={{ background: chip.dot }} />
                {relevance.label}
              </span>
            )}
            {ev && <span className={`xmr-ev ${ev.cls}`}>{t(ev.labelKey)}</span>}
          </div>
          <h3 className="xmr-title">
            <a href={pubmedUrl} target="_blank" rel="noreferrer">
              {title}
            </a>
          </h3>
          <div className="xmr-journal">
            {journal || t("result.unknownJournal")}
            {year ? ` · ${year}` : ""}
            {sourceTag ? ` · ${sourceTag}` : ""}
          </div>
          {contribution ? (
            <p className="xmr-contribution">
              <span className="xmr-contribution-label">
                {t("result.contributionLabel")}
              </span>
              {contribution}
            </p>
          ) : null}
        </div>

        {relevance && (
          <div className="xmr-ringwrap">
            <div
              className="xmr-ring"
              style={{
                background: `conic-gradient(var(--accent) 0% ${ringPct}%, var(--surface-soft) ${ringPct}% 100%)`,
              }}
              title={relevance.title}
            >
              <div className="xmr-ring-inner">
                <span className="xmr-ring-val">{relevance.pct}</span>
                <span className="xmr-ring-unit">{t("result.ringUnit")}</span>
              </div>
            </div>
            <span className="xmr-ring-cap">{caption}</span>
          </div>
        )}
      </div>

      {meshShown.length > 0 && (
        <div className="xmr-mesh">
          {meshShown.map((m) => (
            <a key={m} className="xmr-mchip" href={PUB(m)} target="_blank" rel="noreferrer">
              {m}
            </a>
          ))}
        </div>
      )}

      <div className="xmr-actions">
        {extraActions}
        {hasReveal && (
          <button
            type="button"
            className={`xmr-toggle ${open ? "on" : ""}`}
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            <span className="caret">⌄</span>
            {open ? t("result.hideSummary") : revealTitle}
          </button>
        )}
        <a className="xmr-act accent" href={pubmedUrl} target="_blank" rel="noreferrer">
          {t("result.readOnPubmed")} {ARROW}
        </a>
        {spoken && (
          <button
            type="button"
            className={`xmr-act ${speaking ? "on" : ""}`}
            onClick={toggleSpeak}
          >
            <svg>
              <path d="M4 9v6h4l5 4V5L8 9z" />
              <path d="M16 8.5a5 5 0 0 1 0 7" />
            </svg>
            {speaking ? t("result.stopListening") : t("result.listen")}
          </button>
        )}
        {readTime && (
          <span className="xmr-read">
            <svg>
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            {t("result.readTime", { time: readTime })}
          </span>
        )}
      </div>

      {open && hasReveal && (
        <div className="xmr-reveal">
          <div className="xmr-reveal-head">
            <span className="xmr-reveal-label">{revealTitle}</span>
            {revealHead}
            {sourceTitle && (
              <span className="xmr-source">
                {t("result.source", { title: sourceTitle })}
              </span>
            )}
          </div>
          <div className={`xmr-reveal-grid ${why && why.length ? "" : "single"}`}>
            <div className={revealBodyClassName}>{children}</div>
            {why && why.length > 0 && (
              <div className="xmr-ia">
                <div className="xmr-ia-head">
                  <span className="xmr-ia-title">
                    <svg>
                      <path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z" />
                    </svg>
                    {t("result.aiSummary")}
                  </span>
                  <span className="xmr-ia-dis">{t("result.toVerify")}</span>
                </div>
                <ul className="xmr-ia-list">
                  {why.map((w, i) => (
                    <li key={i}>
                      <span className="dash">—</span>
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </article>
  );
}
