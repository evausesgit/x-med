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
  /** chapô / justification (texte court sous le titre) */
  stand?: string | null;
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

const EV: Record<number, { label: string; cls: string }> = {
  1: { label: "Niv. 1 · preuve élevée", cls: "xmr-ev1" },
  2: { label: "Niv. 2 · modérée", cls: "xmr-ev2" },
  3: { label: "Niv. 3 · cas", cls: "xmr-ev3" },
  4: { label: "Niv. 4 · avis", cls: "xmr-ev4" },
};

// Couleurs de la pastille de pertinence selon le palier (cf. design tier()).
const TIER_CHIP: Record<Tier, { bg: string; fg: string; dot: string }> = {
  high: { bg: "#e0efe6", fg: "#1d5b43", dot: "#2f8a63" },
  mid: { bg: "#edf3ff", fg: "#284b7b", dot: "#4a73b8" },
  low: { bg: "#f1efe8", fg: "#6c655b", dot: "#a39b8d" },
  off: { bg: "#f6ead9", fg: "#8a5a1c", dot: "#c79a4e" },
};

const ARROW = (
  <svg viewBox="0 0 24 24">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
const PUB = (t: string) => "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(t);

// Synthèse vocale FR navigateur (réutilisée du digest).
const TTS = {
  ok: typeof window !== "undefined" && "speechSynthesis" in window,
  speak(text: string, onend: () => void) {
    if (!this.ok) {
      setTimeout(onend, 50);
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "fr-FR";
    const v = (window.speechSynthesis.getVoices() || []).find((x) => /fr/i.test(x.lang));
    if (v) u.voice = v;
    u.onend = onend;
    u.onerror = onend;
    window.speechSynthesis.speak(u);
  },
  stop() {
    if (this.ok) window.speechSynthesis.cancel();
  },
};

export default function XMedResult({
  rank,
  title,
  journal,
  year,
  level,
  relevance,
  stand,
  sourceTag,
  pubmedUrl,
  mesh,
  sourceTitle,
  readTime,
  ringCaption = "Pertinence pour votre question",
  featured,
  why,
  spoken,
  revealLabel = "Résumé & abstract",
  revealHead,
  revealBodyClassName = "xmr-abstract",
  children,
}: XMedResultProps) {
  const [open, setOpen] = useState(false);
  const [speaking, setSpeaking] = useState(false);

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
    TTS.speak(spoken, () => setSpeaking(false));
  }

  return (
    <article ref={wrapRef} className={`xmr-card ${featured ? "featured" : ""}`} onClick={cardClick}>
      {featured && <div className="xmr-feat-kicker">★ Le plus pertinent</div>}

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
            {ev && <span className={`xmr-ev ${ev.cls}`}>{ev.label}</span>}
          </div>
          <h3 className="xmr-title">
            <a href={pubmedUrl} target="_blank" rel="noreferrer">
              {title}
            </a>
          </h3>
          <div className="xmr-journal">
            {journal || "Journal inconnu"}
            {year ? ` · ${year}` : ""}
            {sourceTag ? ` · ${sourceTag}` : ""}
          </div>
          {stand ? <p className="xmr-stand">{stand}</p> : null}
        </div>

        {relevance && (
          <div className="xmr-ringwrap">
            <div
              className="xmr-ring"
              style={{
                background: `conic-gradient(var(--accent) 0% ${ringPct}%, #eef0ea ${ringPct}% 100%)`,
              }}
              title={relevance.title}
            >
              <div className="xmr-ring-inner">
                <span className="xmr-ring-val">{relevance.pct}</span>
                <span className="xmr-ring-unit">% match</span>
              </div>
            </div>
            <span className="xmr-ring-cap">{ringCaption}</span>
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
        {hasReveal && (
          <button
            type="button"
            className={`xmr-toggle ${open ? "on" : ""}`}
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            <span className="caret">⌄</span>
            {open ? "Masquer le résumé" : revealLabel}
          </button>
        )}
        <a className="xmr-act accent" href={pubmedUrl} target="_blank" rel="noreferrer">
          Lire sur PubMed {ARROW}
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
            {speaking ? "Arrêter" : "Écouter"}
          </button>
        )}
        {readTime && (
          <span className="xmr-read">
            <svg>
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            {readTime} de lecture
          </span>
        )}
      </div>

      {open && hasReveal && (
        <div className="xmr-reveal">
          <div className="xmr-reveal-head">
            <span className="xmr-reveal-label">{revealLabel}</span>
            {revealHead}
            {sourceTitle && <span className="xmr-source">Source : {sourceTitle}</span>}
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
                    Résumé IA
                  </span>
                  <span className="xmr-ia-dis">à vérifier</span>
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
