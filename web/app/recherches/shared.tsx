"use client";

// Composants d'affichage partagés entre la liste des recherches sauvegardées
// (page.tsx) et la page d'une recherche partageable (`[id]/page.tsx`). Repris de
// la page de recherche (web/app/page.tsx) pour une relecture cohérente.
import { useEffect, useRef, useState } from "react";
import {
  analyzeCompareStream,
  type CompareResult,
  DeepHit,
  DeepSearchResponse,
  type PubmedLog,
} from "@/lib/api";
import {
  type DisplayedHit,
  type DisplayLang,
  LanguageToggle,
  useDisplayLang,
  useTranslatedHits,
} from "../lang";
import XMedResult, { deepRelevance, StructuredAbstract } from "../XMedResult";
import { CritiquePanel, MAX_COMPARE, SelectButton } from "../Critique";

export function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function HitCard({
  hit,
  rank,
  display,
  lang,
  onLang,
  busy,
  extraActions,
}: {
  hit: DeepHit;
  rank: number;
  display: DisplayedHit;
  lang: DisplayLang;
  onLang: (l: DisplayLang) => void;
  busy: boolean;
  // Bouton de sélection « Comparer » injecté par ResultDetail (analyse critique).
  extraActions?: React.ReactNode;
}) {
  return (
    <XMedResult
      rank={rank}
      title={display.title}
      journal={hit.journal}
      year={hit.pub_year}
      level={hit.evidence_level}
      relevance={
        hit.score != null ? deepRelevance(hit.score, hit.relevance_pct) : undefined
      }
      contribution={hit.reason}
      extraActions={extraActions}
      sourceTag={
        hit.source === "both"
          ? "A · PubMed + B · local"
          : hit.source === "pubmed"
            ? "A · PubMed"
            : "B · local"
      }
      pubmedUrl={hit.pubmed_url}
      sourceTitle={hit.title}
      revealLabel="Résumé structuré"
      revealBodyClassName="xmr-sections"
      revealHead={<LanguageToggle lang={lang} onChange={onLang} busy={busy} />}
      spoken={display.abstract ?? hit.reason ?? undefined}
    >
      {display.abstract ? (
        <StructuredAbstract abstract={display.abstract} translated={display.translated} />
      ) : undefined}
    </XMedResult>
  );
}

export function ResultDetail({ payload }: { payload: DeepSearchResponse }) {
  const [lang, setLang] = useDisplayLang();
  const { resolve, busy } = useTranslatedHits(payload.results, lang);

  // Analyse critique comparative : on coche 2–3 articles puis on lance l'analyse,
  // comme sur la page de recherche (web/app/page.tsx). Sans ça, une recherche
  // sauvegardée ne permettait plus de comparer les articles.
  const [selected, setSelected] = useState<number[]>([]);
  const [analysis, setAnalysis] = useState<CompareResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisLogs, setAnalysisLogs] = useState<PubmedLog[]>([]);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisOrder, setAnalysisOrder] = useState<number[]>([]);
  const critiqueRef = useRef<EventSource | null>(null);
  useEffect(() => () => critiqueRef.current?.close(), []);

  function toggleSelected(pmid: number) {
    setSelected((prev) =>
      prev.includes(pmid)
        ? prev.filter((p) => p !== pmid)
        : prev.length >= MAX_COMPARE
          ? prev
          : [...prev, pmid],
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
    const order = [...selected];
    setAnalyzing(true);
    setAnalysis(null);
    setAnalysisError(null);
    setAnalysisLogs([]);
    setAnalysisOrder(order);
    critiqueRef.current?.close();
    critiqueRef.current = analyzeCompareStream(payload.query, order, {
      onLog: (log) => setAnalysisLogs((prev) => [...prev, log]),
      onResult: (res) => {
        if (res.codex_limit) {
          setAnalysisError(
            "Limite d'usage GPT-5.4 atteinte — réessayez l'analyse plus tard.",
          );
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
    <div className="saved-detail">
      {payload.pubmed_query && (
        <details className="explanation">
          <summary>Requête PubMed générée + mots-clés</summary>
          <p className="abstract" style={{ fontFamily: "monospace", fontSize: 13 }}>
            {payload.pubmed_query}
          </p>
          {payload.keywords_en?.length > 0 && (
            <div className="tags">
              {payload.keywords_en.slice(0, 12).map((t) => (
                <span className="tag" key={t}>
                  {t}
                </span>
              ))}
            </div>
          )}
        </details>
      )}
      {payload.results.length === 0 ? (
        <p className="notice">Aucun article dans cette recherche sauvegardée.</p>
      ) : (
        <>
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

          {/* Déroulé live de l'analyse codex. */}
          {analyzing && (
            <div className="xm-live running">
              <div className="xm-live-head">
                <span className="xm-live-dot" />
                <span className="xm-live-title">Analyse critique — en direct</span>
                <span className="xm-live-spin" />
              </div>
              <div className="xm-live-body">
                {analysisLogs.length === 0 && (
                  <div className="xm-live-line">Analyse en cours…</div>
                )}
                {analysisLogs.map((l, k) => (
                  <div key={k} className="xm-live-line">
                    {l.msg}
                  </div>
                ))}
              </div>
            </div>
          )}
          {analysisError && <p className="xm-banner warn">⚠ {analysisError}</p>}
          {analysis && <CritiquePanel result={analysis} order={analysisOrder} />}

          {payload.results.map((h, i) => (
            <HitCard
              key={`${h.pmid}-${i}`}
              hit={h}
              rank={i + 1}
              display={resolve(h)}
              lang={lang}
              onLang={setLang}
              busy={busy}
              extraActions={
                <SelectButton
                  selected={selected.includes(h.pmid)}
                  disabled={
                    !selected.includes(h.pmid) && selected.length >= MAX_COMPARE
                  }
                  onToggle={() => toggleSelected(h.pmid)}
                />
              }
            />
          ))}
        </>
      )}
    </div>
  );
}

// Bouton « Partager » : copie le lien public d'une recherche sauvegardée
// (/recherches/{id}) dans le presse-papiers. Le lien est partageable tel quel —
// l'endpoint GET /saved-searches/{id} n'a pas de contrôle d'accès.
export function ShareButton({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = `${window.location.origin}/recherches/${id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Presse-papiers indisponible (http non sécurisé, vieux navigateur) :
      // on montre le lien à copier à la main.
      window.prompt("Copiez ce lien pour le partager :", url);
    }
  }
  return (
    <button type="button" onClick={share}>
      {copied ? "✅ Lien copié" : "🔗 Partager"}
    </button>
  );
}
