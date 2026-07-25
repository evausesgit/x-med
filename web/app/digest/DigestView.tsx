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
import { useT } from "@/lib/i18n";
import type { Locale, Translate } from "@/lib/locale";
import type { Article, DigestData } from "./types";

// Pertinence pour le profil (0–100) → format commun de la carte.
function digestRelevance(match: number, t: Translate): Relevance {
  const tier: Relevance["tier"] = match >= 85 ? "high" : match >= 70 ? "mid" : "low";
  const label = t(
    match >= 85
      ? "result.tierHigh"
      : match >= 70
        ? "result.tierMid"
        : "result.tierRelated",
  );
  return {
    pct: match,
    tier,
    label,
    title: t("result.relevanceProfileTitle", { pct: match }),
  };
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
  const { t, locale } = useT();
  // La face affichée suit la langue du compte ; la bascule ci-dessous reste
  // disponible pour lire l'autre version à la demande, carte par carte.
  const [lang, setLang] = useState<Locale>(locale);
  useEffect(() => setLang(locale), [locale]);
  const face = a[lang];
  const langToggle = (
    <div className="xmr-langtoggle" role="group" aria-label={t("lang.groupLabel")}>
      <button type="button" className={lang === "fr" ? "on" : ""} onClick={() => setLang("fr")}>
        {t("lang.french")}
      </button>
      <button type="button" className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>
        {t("lang.english")}
      </button>
    </div>
  );
  return (
    <XMedResult
      rank={rank}
      title={face.title}
      journal={a.journal}
      year={a.year}
      level={a.level}
      relevance={digestRelevance(a.match, t)}
      contribution={face.stand}
      sourceTitle={a.en.title}
      readTime={a.read}
      ringCaption={t("result.ringCaptionProfile")}
      featured={rank === 1}
      why={face.why}
      spoken={face.spoken}
      mesh={a.mesh}
      pubmedUrl={
        a.pubmedUrl ??
        "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(a.en.title)
      }
      extraActions={
        <SelectButton selected={selected} disabled={disabled} onToggle={onToggle} />
      }
      spokenLang={lang}
      revealLabel={t("search.revealLabel")}
      revealHead={langToggle}
      revealBodyClassName="xmr-sections"
    >
      <StructuredAbstract abstract={face.abstract} lang={lang} />
    </XMedResult>
  );
}

// Déroulé live de l'analyse critique codex (mêmes classes que la recherche).
function CritiqueLive({ logs }: { logs: PubmedLog[] }) {
  const { t } = useT();
  return (
    <div className="xm-live running">
      <div className="xm-live-head">
        <span className="xm-live-dot" />
        <span className="xm-live-title">{t("critique.liveTitle")}</span>
        <span className="xm-live-spin" />
      </div>
      <div className="xm-live-body">
        {logs.length === 0 && (
          <div className="xm-live-line">{t("critique.liveReading")}</div>
        )}
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
  const { t, tp } = useT();
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
      setAnalysisError(t("critique.demoUnavailable"));
      setAnalyzing(false);
      return;
    }
    const question = `${D.doctor.specialty} — ${D.themes.join(", ")}`;
    critiqueRef.current = analyzeCompareStream(question, pmids, {
      onLog: (log) => setAnalysisLogs((prev) => [...prev, log]),
      onResult: (res) => {
        if (res.codex_limit) {
          setAnalysisError(t("common.usageLimit"));
        } else {
          setAnalysis(res);
        }
        setAnalyzing(false);
      },
      onError: (msg) => {
        setAnalysisError(msg || t("critique.failed"));
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
              {t("digest.kicker", { date: D.date })}
            </div>
            <h1 className="xm-digest-title">{t("digest.headTitle")}</h1>
            <p className="xm-digest-sub">
              {t("digest.headSub", {
                count: articles.length,
                name: D.doctor.name,
                specialty: D.doctor.specialty,
              })}
            </p>
          </div>
          <div className="xm-digest-gen">
            {t("digest.generatedAt", { time: D.generated })}
            <br />
            {D.method}
          </div>
        </div>

        <div className="xm-digest-themes">
          <span className="xm-digest-themes-label">{t("digest.themesLabel")}</span>
          {D.themes.map((theme) => (
            <span className="xm-theme" key={theme}>
              {theme}
            </span>
          ))}
          <a className="xm-theme-link" href="/profil">
            {t("digest.adjustThemes")}
          </a>
        </div>
      </div>

      {/* Barre d'analyse critique : apparaît dès qu'un article est coché. */}
      {selected.length > 0 && (
        <div className="xm-compare-bar">
          <span className="xm-compare-count">
            {tp("critique.selectedCount", selected.length, { max: MAX_COMPARE })}
          </span>
          <span className="xm-compare-actions">
            <button
              type="button"
              className="primary"
              disabled={selected.length < 2 || analyzing}
              onClick={runAnalysis}
              title={t(
                selected.length < 2
                  ? "critique.runTitleTooFew"
                  : "critique.runTitle",
              )}
            >
              {analyzing ? t("critique.liveEmpty") : t("critique.run")}
            </button>
            <button type="button" className="xmr-act" onClick={clearSelection}>
              {t("critique.clear")}
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

      <p className="xm-disclaimer">{t("digest.disclaimer")}</p>
    </div>
  );
}
