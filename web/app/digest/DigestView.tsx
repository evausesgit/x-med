"use client";

/* X-Med — vue « Mon Digest » (design system « X-Med App »).
   En-tête éditorial (date, profil, thèmes) + liste de cartes XMedResult
   partagées avec la recherche. La zone repliée présente le « Résumé structuré »
   (Contexte / Méthodes / Résultats / Conclusion) via le composant partagé
   StructuredAbstract, bascule FR/EN dans l'en-tête ; les puces « pourquoi »
   alimentent le panneau Résumé IA.

   Comme la recherche, on peut cocher 2 à 3 articles (SelectButton) puis lancer
   l'analyse critique comparative (CritiquePanel). L'analyse résout les abstracts
   par PMID côté API : elle est donc opérationnelle dès que le digest fournit de
   vrais PMID (cf. getDigest dans page.tsx) ; sur l'aperçu de démonstration
   (ids non numériques) elle se solde par un message d'indisponibilité. */

import { useEffect, useRef, useState } from "react";
import XMedResult, { StructuredAbstract, type Relevance } from "../XMedResult";
import { CritiquePanel, MAX_COMPARE, SelectButton } from "../Critique";
import { analyzeCompareStream, type CompareResult, type PubmedLog } from "@/lib/api";
import type { Article, DigestData } from "./types";

// Pertinence pour le profil (0–100) → format commun de la carte.
function digestRelevance(match: number): Relevance {
  const tier: Relevance["tier"] = match >= 85 ? "high" : match >= 70 ? "mid" : "low";
  const label = match >= 85 ? "Très pertinent" : match >= 70 ? "Pertinent" : "Lié";
  return { pct: match, tier, label, title: `Pertinence pour votre profil : ${match}%` };
}

// Une carte de digest : conserve l'état de langue, qui pilote à la fois la
// bascule FR/EN (dans l'en-tête replié) et les sections affichées. La case à
// cocher (SelectButton) alimente l'analyse critique pilotée par DigestView.
function DigestCard({
  a,
  rank,
  selected,
  onToggle,
  disabled,
}: {
  a: Article;
  rank: number;
  selected: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
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
      extraActions={
        <SelectButton selected={selected} disabled={disabled} onToggle={onToggle} />
      }
      revealLabel="Résumé structuré"
      revealHead={langToggle}
      revealBodyClassName="xmr-sections"
    >
      <StructuredAbstract abstract={t.abstract} />
    </XMedResult>
  );
}

// Déroulé live de l'analyse critique codex (mêmes classes que la recherche).
function CritiqueLive({ logs }: { logs: PubmedLog[] }) {
  return (
    <div className="xm-live running">
      <div className="xm-live-head">
        <span className="xm-live-dot" />
        <span className="xm-live-title">Analyse critique — en direct</span>
        <span className="xm-live-spin" />
      </div>
      <div className="xm-live-body">
        {logs.length === 0 && <div className="xm-live-line">Lecture des abstracts par codex…</div>}
        {logs.map((l, k) => (
          <div key={k} className="xm-live-line">
            {l.msg}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DigestView({ data }: { data: DigestData }) {
  const D = data;
  // Le digest présente l'article phare puis le reste de la sélection.
  const articles = [D.lead, ...D.articles];

  // Sélection pour l'analyse critique comparative (≤ MAX_COMPARE), résultat et
  // état de l'appel codex — même mécanique que la page de recherche.
  const [selected, setSelected] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<CompareResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisLogs, setAnalysisLogs] = useState<PubmedLog[]>([]);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  // Ordre de sélection figé au lancement (stabilise les colonnes du tableau).
  const [analysisOrder, setAnalysisOrder] = useState<number[]>([]);
  const critiqueRef = useRef<EventSource | null>(null);

  useEffect(() => () => critiqueRef.current?.close(), []);

  function toggleSelected(id: string) {
    setSelected((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length >= MAX_COMPARE
          ? prev
          : [...prev, id],
    );
  }

  function clearSelection() {
    setSelected([]);
    setAnalysis(null);
    setAnalysisError(null);
    setAnalysisLogs([]);
    critiqueRef.current?.close();
    setAnalyzing(false);
  }

  function runAnalysis() {
    if (selected.length < 2 || analyzing) return;
    // L'API d'analyse résout les abstracts par PMID : la sélection doit porter de
    // vrais PMID (ids numériques). L'aperçu de démonstration ne les a pas encore.
    const pmids = selected.map((id) => Number(id));
    setAnalysisOrder(pmids);
    setAnalyzing(true);
    setAnalysis(null);
    setAnalysisError(null);
    setAnalysisLogs([]);
    critiqueRef.current?.close();
    if (pmids.some((p) => !Number.isFinite(p))) {
      setAnalysisError(
        "L'analyse critique compare de vrais articles PubMed. Disponible dès que votre digest sera généré — l'aperçu de démonstration ne contient pas d'articles réels.",
      );
      setAnalyzing(false);
      return;
    }
    const question = `${D.doctor.specialty} — ${D.themes.join(", ")}`;
    critiqueRef.current = analyzeCompareStream(question, pmids, {
      onLog: (log) => setAnalysisLogs((prev) => [...prev, log]),
      onResult: (res) => {
        if (res.codex_limit) {
          setAnalysisError("Limite d'usage GPT-5.4 atteinte — réessayez l'analyse plus tard.");
        } else {
          setAnalysis(res);
        }
        setAnalyzing(false);
      },
      onError: (msg) => {
        setAnalysisError(msg || "L'analyse critique a échoué.");
        setAnalyzing(false);
      },
    });
  }

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

      {/* Barre d'analyse critique : apparaît dès qu'un article est coché. */}
      {selected.length > 0 && (
        <div className="xm-compare-bar">
          <span className="xm-compare-count">
            <strong>{selected.length}</strong> / {MAX_COMPARE} sélectionné
            {selected.length > 1 ? "s" : ""} pour l&apos;analyse
          </span>
          <span className="xm-compare-actions">
            <button
              type="button"
              className="primary"
              disabled={selected.length < 2 || analyzing}
              onClick={runAnalysis}
              title={
                selected.length < 2
                  ? "Sélectionnez au moins 2 articles"
                  : "Lancer l'analyse critique comparative"
              }
            >
              {analyzing ? "Analyse en cours…" : "🔬 Analyser la sélection"}
            </button>
            <button type="button" className="xmr-act" onClick={clearSelection}>
              Effacer
            </button>
          </span>
        </div>
      )}

      {analyzing && <CritiqueLive logs={analysisLogs} />}
      {analysisError && <p className="xm-banner warn">⚠ {analysisError}</p>}
      {analysis && <CritiquePanel result={analysis} order={analysisOrder} />}

      <div>
        {articles.map((a, i) => (
          <DigestCard
            key={a.id}
            a={a}
            rank={i + 1}
            selected={selected.includes(a.id)}
            disabled={!selected.includes(a.id) && selected.length >= MAX_COMPARE}
            onToggle={() => toggleSelected(a.id)}
          />
        ))}
      </div>

      <p className="xm-disclaimer">
        Sélection établie pour votre profil — un appui à la veille, pas une validation
        clinique.
      </p>
    </div>
  );
}
