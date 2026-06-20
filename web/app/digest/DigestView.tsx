"use client";

/* X-Med — vue « Mon Digest » (design system « X-Med App »).
   En-tête éditorial (date, profil, thèmes) + liste de cartes XMedResult
   partagées avec la recherche. La zone repliée présente le « Résumé structuré »
   du design (Contexte / Méthodes / Résultats / Conclusion), bascule FR/EN dans
   l'en-tête ; les puces « pourquoi » alimentent le panneau Résumé IA. */

import { useState } from "react";
import XMedResult, { type Relevance } from "../XMedResult";
import type { Article, DigestData, LocalizedText } from "./types";

// Pertinence pour le profil (0–100) → format commun de la carte.
function digestRelevance(match: number): Relevance {
  const tier: Relevance["tier"] = match >= 85 ? "high" : match >= 70 ? "mid" : "low";
  const label = match >= 85 ? "Très pertinent" : match >= 70 ? "Pertinent" : "Lié";
  return { pct: match, tier, label, title: `Pertinence pour votre profil : ${match}%` };
}

// L'abstract est structuré « Label : texte » par ligne (Contexte/Méthodes/… ou
// Background/Methods/…). On le découpe en sections pour le « Résumé structuré ».
// La dernière section (conclusion) est mise en avant (or).
function toSections(abstract: string): { label: string; text: string; concl: boolean }[] {
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
      concl: i === lines.length - 1,
    };
  });
}

function Sections({ t }: { t: LocalizedText }) {
  return (
    <>
      {toSections(t.abstract).map((s, i) => (
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

// Une carte de digest : conserve l'état de langue, qui pilote à la fois la
// bascule FR/EN (dans l'en-tête replié) et les sections affichées.
function DigestCard({ a, rank }: { a: Article; rank: number }) {
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const t = a[lang];
  const langToggle = (
    <div className="xmr-langtoggle">
      <button type="button" className={lang === "fr" ? "on" : ""} onClick={() => setLang("fr")}>
        Français
      </button>
      <button type="button" className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>
        English
      </button>
    </div>
  );
  return (
    <XMedResult
      rank={rank}
      title={t.title}
      journal={a.journal}
      year={a.year}
      level={a.level}
      relevance={digestRelevance(a.match)}
      stand={t.stand}
      sourceTitle={a.en.title}
      readTime={a.read}
      ringCaption="Pertinence pour votre profil"
      featured={rank === 1}
      why={a.why}
      spoken={a.spoken}
      mesh={a.mesh}
      pubmedUrl={"https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(a.en.title)}
      revealLabel="Résumé structuré"
      revealHead={langToggle}
      revealBodyClassName="xmr-sections"
    >
      <Sections t={t} />
    </XMedResult>
  );
}

export default function DigestView({ data }: { data: DigestData }) {
  const D = data;
  // Le digest présente l'article phare puis le reste de la sélection.
  const articles = [D.lead, ...D.articles];

  return (
    <div>
      <div className="xm-digest-head">
        <div className="xm-digest-head-row">
          <div>
            <div className="xm-digest-kicker">
              <span className="dot" />
              Mon Digest · {D.date}
            </div>
            <h1 className="xm-digest-title">Votre veille du jour</h1>
            <p className="xm-digest-sub">
              {articles.length} articles choisis pour votre profil — {D.doctor.name},{" "}
              {D.doctor.specialty}.
            </p>
          </div>
          <div className="xm-digest-gen">
            Généré {D.generated} CET
            <br />
            Modèle {D.model}
          </div>
        </div>

        <div className="xm-digest-themes">
          <span className="xm-digest-themes-label">VOS THÈMES</span>
          {D.themes.map((t) => (
            <span className="xm-theme" key={t}>
              {t}
            </span>
          ))}
          <a className="xm-theme-link" href="/profil">
            ajuster mes thèmes →
          </a>
        </div>
      </div>

      <div>
        {articles.map((a, i) => (
          <DigestCard key={a.id} a={a} rank={i + 1} />
        ))}
      </div>

      <p className="xm-disclaimer">
        Sélection établie pour votre profil — un appui à la veille, pas une validation
        clinique.
      </p>
    </div>
  );
}
