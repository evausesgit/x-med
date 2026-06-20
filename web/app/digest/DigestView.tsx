"use client";

/* X-Med — vue « Mon Digest » (design system « X-Med App »).
   En-tête éditorial (date, profil, thèmes) + liste de cartes XMedResult
   partagées avec la recherche. Le contenu replié de chaque carte est l'abstract
   FR/EN ; les puces « pourquoi » alimentent le panneau Résumé IA. */

import { useState } from "react";
import XMedResult, { type Relevance } from "../XMedResult";
import type { Article, DigestData } from "./types";

// Pertinence pour le profil (0–100) → format commun de la carte.
function digestRelevance(match: number): Relevance {
  const tier: Relevance["tier"] = match >= 85 ? "high" : match >= 70 ? "mid" : "low";
  const label = match >= 85 ? "Très pertinent" : match >= 70 ? "Pertinent" : "Lié";
  return { pct: match, tier, label, title: `Pertinence pour votre profil : ${match}%` };
}

// Abstract bilingue (FR par défaut, bascule EN) — rendu en `children` de la carte.
function DigestAbstract({ a }: { a: Article }) {
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const t = a[lang];
  return (
    <div>
      <div className="xmr-langtoggle" style={{ marginBottom: 12 }}>
        <button type="button" className={lang === "fr" ? "on" : ""} onClick={() => setLang("fr")}>
          Français
        </button>
        <button type="button" className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>
          English
        </button>
      </div>
      {t.abstract}
    </div>
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
          <XMedResult
            key={a.id}
            rank={i + 1}
            title={a.fr.title}
            journal={a.journal}
            year={a.year}
            level={a.level}
            relevance={digestRelevance(a.match)}
            stand={a.fr.stand}
            sourceTitle={a.en.title}
            readTime={a.read}
            ringCaption="Pertinence pour votre profil"
            featured={i === 0}
            why={a.why}
            spoken={a.spoken}
            mesh={a.mesh}
            pubmedUrl={"https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(a.en.title)}
            revealLabel="Résumé & abstract"
          >
            <DigestAbstract a={a} />
          </XMedResult>
        ))}
      </div>

      <p className="xm-disclaimer">
        Sélection établie pour votre profil — un appui à la veille, pas une validation
        clinique.
      </p>
    </div>
  );
}
