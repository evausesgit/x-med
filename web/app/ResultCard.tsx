"use client";

/* X-Med — carte de résultat « magazine ».
   Réutilise le style des cartes du Digest (.xmed-digest .item) pour que la page
   de recherche et le digest parlent le même langage visuel. On garde uniquement
   le format « carte » : pas de lead sombre, pas de jauge anneau, pas de panneau
   « Résumé IA » ni de synthèse vocale — ces éléments n'ont pas de données réelles
   côté recherche (voir décision « Magazine cards only »).

   La carte fournit le chrome (rang, pastille de pertinence, badge de preuve,
   barre de pertinence, justification, lien PubMed, abstract repliable + MeSH) ;
   le contenu de l'abstract est passé en `children` pour que chaque mode garde sa
   logique (FR/EN à la demande pour la v2, simple snippet pour les autres). */

import { useEffect, useState } from "react";
import "./digest/digest.css";

const ARROW = (
  <svg
    viewBox="0 0 24 24"
    style={{ width: 13, height: 13, fill: "none", stroke: "currentColor", strokeWidth: 2 }}
  >
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

const EV_LABEL: Record<number, string> = {
  1: "preuve élevée",
  2: "modérée",
  3: "cas / série",
  4: "avis",
};

export type Tier = "high" | "mid" | "low" | "off";

// Pastille de pertinence : couleur via les classes du digest (mid/low) ;
// "high" = pas de modificateur, "off" retombe sur "low".
function chipClass(tier: Tier): string {
  if (tier === "mid") return "mid";
  if (tier === "low" || tier === "off") return "low";
  return "";
}

/** Pertinence d'un résultat. Absente en mode « Mots-clés / MeSH » (le tri vient
    des filtres, pas d'un score) : ni pastille ni barre dans ce cas. */
export interface Relevance {
  /** largeur de la barre, 0–100 */
  pct: number;
  tier: Tier;
  /** libellé de la pastille (« Très pertinent », « Pertinent »…) */
  label: string;
  /** texte de droite de la barre (« 83 % », « 3/3 »…) */
  text: string;
  /** infobulle sur la barre (détail du score) */
  title?: string;
}

export interface ResultCardProps {
  rank: number;
  title: string;
  journal?: string | null;
  year?: number | null;
  level?: number | null;
  relevance?: Relevance;
  /** justification / chapô (texte court sous le titre) */
  reason?: string | null;
  /** étiquette de provenance (« A · PubMed + B · local »…) */
  sourceTag?: string | null;
  pubmedUrl: string;
  /** termes MeSH (chips dans la zone repliée) */
  mesh?: string[];
  /** contenu de l'abstract (rendu dans la zone repliée) */
  children?: React.ReactNode;
}

const PUB = (t: string) => "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(t);

export default function ResultCard({
  rank,
  title,
  journal,
  year,
  level,
  relevance,
  reason,
  sourceTag,
  pubmedUrl,
  mesh,
  children,
}: ResultCardProps) {
  const [open, setOpen] = useState(false);
  // Anime la barre de pertinence (0 → pct) comme dans le digest.
  const [bar, setBar] = useState(0);
  const pct = relevance?.pct ?? 0;
  useEffect(() => {
    const t = setTimeout(() => setBar(pct), 200);
    return () => clearTimeout(t);
  }, [pct]);

  const hasDetail = Boolean(children) || (mesh && mesh.length > 0);

  // Clic sur la carte (hors bouton/lien) : déplie/replie l'abstract.
  const cardClick = (e: React.MouseEvent) => {
    if (!hasDetail) return;
    if (!(e.target as HTMLElement).closest("button, a, details, summary")) {
      setOpen((o) => !o);
    }
  };

  return (
    <article className="item" onClick={cardClick} aria-expanded={open}>
      <div className="top">
        <span className="no">{String(rank).padStart(2, "0")}</span>
        {relevance && (
          <span className={`relchip ${chipClass(relevance.tier)}`}>
            <span className="d" /> {relevance.label}
          </span>
        )}
      </div>
      <h3>
        <a href={pubmedUrl} target="_blank" rel="noreferrer">
          {title}
        </a>
      </h3>
      <div className="meta-row">
        {level ? (
          <span className={`badge ev${level}`}>
            Niv. {level} · {EV_LABEL[level]}
          </span>
        ) : null}
        <span className="m">
          {journal || "Journal inconnu"}
          {year ? ` · ${year}` : ""}
        </span>
        {sourceTag ? <span className="m">{sourceTag}</span> : null}
      </div>
      {reason ? <p className="stand">{reason}</p> : null}
      {relevance && (
        <div className="relrow">
          <div className="relbar">
            <span style={{ width: `${bar}%` }} />
          </div>
          <span className="relpct" title={relevance.title}>
            {relevance.text}
          </span>
        </div>
      )}

      {hasDetail && (
        <>
          <button
            type="button"
            className={`cue ${open ? "on" : ""}`}
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            <span className="cv">{ARROW}</span>
            {open ? "Masquer l’abstract" : "Abstract & termes MeSH"}
          </button>
          {open && (
            <div className="reveal">
              {children}
              {mesh && mesh.length > 0 && (
                <div className="mesh">
                  {mesh.slice(0, 12).map((m) => (
                    <a
                      key={m}
                      className="mchip"
                      href={PUB(m)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {m}
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: 12 }}>
        <a className="readmore" href={pubmedUrl} target="_blank" rel="noreferrer">
          PubMed {ARROW}
        </a>
      </div>
    </article>
  );
}
