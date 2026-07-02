"use client";

import { useEffect, useRef, useState } from "react";
import {
  analyzeCompareStream,
  ArticleResult,
  DeepSearchResponse,
  Doctor,
  EmbeddingModelInfo,
  listDoctors,
  listModels,
  lookupSavedSearch,
  meshAutocomplete,
  PubmedLog,
  saveSearch,
  searchMesh,
  searchPubmedDeepMoreStream,
  searchPubmedDeepStream,
  searchSemantic,
  SearchResponse,
} from "@/lib/api";
import type { CompareResult, DeepHit } from "@/lib/api";
import Link from "next/link";
import XMedResult, { deepRelevance, StructuredAbstract, type Relevance } from "./XMedResult";
import { CritiquePanel, MAX_COMPARE, SelectButton } from "./Critique";
import { LanguageToggle, useDisplayLang, useTranslatedHits } from "./lang";

const PAGE = 20;

// Durée d'une recherche PubMed + IA (jugement codex). En pratique 30–90 s ; le
// backend laisse beaucoup plus avant d'abandonner (timeouts codex : 180 s pour
// la requête + 420 s pour le jugement, cf. app/services/codex_*). On affiche un
// chrono et ces repères pour que l'utilisateur sache combien patienter plutôt
// que de se demander si « ça a planté ».
const DEEP_TYPICAL_TXT = "30 à 90 secondes";
const DEEP_TYPICAL_S = 90; // au-delà : « un peu plus long que d'habitude »
const DEEP_LONG_S = 180; // au-delà : on prévient que c'est une recherche longue
// Format chrono lisible : « 12s », puis « 1 min 05s ».
const fmtElapsed = (s: number) =>
  s < 60 ? `${s}s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}s`;

// Seuils de pertinence pour la recherche par sens (similarité cosinus bge-m3).
// ⚠ Provisoires : à caler sur le gold set annoté par les médecins (/annotate).
const SEM_RELEVANT = 0.5; // en-dessous : on prévient que rien n'est vraiment pertinent
const SEM_FLOOR = 0.45; // en-dessous : hors périmètre couvert

// --- Pertinence par méthode → format commun de la carte (anneau + pastille) ---
// Chaque méthode a sa propre échelle ; on convertit ici en {pct, tier, label}.

// Sémantique : `score` EST la similarité cosinus (0–1), signal ABSOLU. Affiché tel
// quel (pas de normalisation au meilleur de la page).
function semanticRelevance(score: number): Relevance {
  const pct = Math.round(score * 100);
  const tier: Relevance["tier"] =
    score >= 0.6 ? "high" : score >= SEM_RELEVANT ? "mid" : score >= SEM_FLOOR ? "low" : "off";
  const label =
    score >= 0.6
      ? "Très pertinent"
      : score >= SEM_RELEVANT
        ? "Pertinent"
        : score >= SEM_FLOOR
          ? "Lié"
          : "Hors périmètre";
  return {
    pct,
    tier,
    label,
    title: `Similarité de sens : ${score.toFixed(3)} (0–1, signal absolu, non normalisé).`,
  };
}

function Explanation({ article }: { article: ArticleResult }) {
  const explanation = article.explanation;
  if (!explanation) return null;

  const hasExplanation =
    explanation.concepts.length > 0 ||
    explanation.population ||
    explanation.intervention ||
    explanation.study_type;

  if (!hasExplanation) return null;

  return (
    <details className="explanation" style={{ marginTop: 14 }}>
      <summary>Pourquoi ce résultat ?</summary>
      <p className="explanation-note">
        Indices issus de l&apos;indexation PubMed et des mentions repérées dans le
        résumé. Ils expliquent le contenu rapproché de la question, sans constituer
        une validation clinique.
      </p>
      <dl className="explanation-grid">
        {explanation.concepts.length > 0 && (
          <div>
            <dt>Concepts</dt>
            <dd>{explanation.concepts.join(" · ")}</dd>
          </div>
        )}
        {explanation.population && (
          <div>
            <dt>Population</dt>
            <dd>{explanation.population}</dd>
          </div>
        )}
        {explanation.intervention && (
          <div>
            <dt>Intervention</dt>
            <dd>{explanation.intervention}</dd>
          </div>
        )}
        {explanation.study_type && (
          <div>
            <dt>Type d&apos;étude</dt>
            <dd>{explanation.study_type}</dd>
          </div>
        )}
      </dl>
    </details>
  );
}

// Recherche PubMed + IA (filtre lexical/MeSH → jugement codex), recherche par
// sens (sémantique) et recherche par mots-clés/MeSH.
type Mode = "pubmed_v2" | "semantic" | "keyword";

function CopyLinkButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="xm-copylink"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(window.location.href);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          /* clipboard indisponible (http non sécurisé) : l'URL reste copiable à la main */
        }
      }}
    >
      <svg viewBox="0 0 24 24">
        <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
        <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
      </svg>
      {copied ? "Lien copié" : "Copier le lien"}
    </button>
  );
}

// Concepts MeSH défilants pendant l'attente (rend le temps de recherche vivant).
const MESH_SAMPLES = [
  "Heart Failure",
  "Diabetes Mellitus, Type 2",
  "Myocardial Infarction",
  "Sodium-Glucose Transporter 2 Inhibitors",
  "Hypertension",
  "Stroke",
  "Anticoagulants",
  "Randomized Controlled Trial",
  "Atrial Fibrillation",
  "Chronic Kidney Disease",
  "Glucagon-Like Peptide 1",
  "Cardiovascular Diseases",
];

// Panneau « Déroulé de la recherche » dans la langue du design : événements SSE
// en direct (méthodes PubMed) ou, pour les recherches en un seul appel
// (sémantique / mots-clés), une rotation de concepts MeSH pendant l'attente.
function LiveEvents({
  running,
  variant,
  logs,
}: {
  running: boolean;
  variant: "pubmed" | "other";
  logs: PubmedLog[];
}) {
  const [i, setI] = useState(0);
  const isPubmed = variant === "pubmed";
  useEffect(() => {
    if (isPubmed) return; // les lignes viennent du serveur (SSE)
    const t = setInterval(() => setI((n) => (n + 1) % MESH_SAMPLES.length), 1300);
    return () => clearInterval(t);
  }, [isPubmed]);

  // Chrono « la recherche tourne depuis… » : repart de zéro à chaque lancement et
  // se fige quand la recherche se termine (running repasse à false).
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    setElapsed(0);
    const start = Date.now();
    const t = setInterval(
      () => setElapsed(Math.round((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(t);
  }, [running]);

  const title =
    variant === "pubmed"
      ? "Pré-filtre local puis jugement par codex"
      : "Recherche en cours";
  const queryLog = logs.find((l) => l.pubmed_query);

  // Message de patience adapté au temps écoulé : l'utilisateur sait à quoi
  // s'attendre et n'a pas l'impression que « ça a planté ».
  const waitHint =
    elapsed < DEEP_TYPICAL_S
      ? `⏳ Une recherche prend en général ${DEEP_TYPICAL_TXT}. Le déroulé s'affiche au fur et à mesure — inutile de relancer.`
      : elapsed < DEEP_LONG_S
        ? `⏳ Un peu plus long que d'habitude (sujet large) — l'IA lit et juge les articles, on continue.`
        : `⏳ Recherche longue : on patiente encore un peu, elle s'arrêtera d'elle-même si elle dépasse quelques minutes.`;

  return (
    <div className={`xm-live ${running ? "running" : ""}`}>
      <div className="xm-live-head">
        <span className="xm-live-dot" />
        <span className="xm-live-title">
          Déroulé de la recherche
          {running ? ` — en direct · ${fmtElapsed(elapsed)}` : ""}
        </span>
        {running && <span className="xm-live-spin" />}
      </div>
      <div className="xm-live-body">
        {isPubmed ? (
          <>
            {logs.length === 0 && <div className="xm-live-line">{title}…</div>}
            {logs.map((l, k) => (
              <div key={k} className="xm-live-line">
                {l.msg}
              </div>
            ))}
            {queryLog?.pubmed_query && (
              <pre className="xm-live-query">{queryLog.pubmed_query}</pre>
            )}
            {running && <div className="xm-live-hint">{waitHint}</div>}
          </>
        ) : (
          <>
            <div className="xm-live-line">{title}…</div>
            <span className="xm-live-mesh" key={i}>
              🔖 {MESH_SAMPLES[i]}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

// Sauvegarde du résultat v2 courant : snapshot complet rattaché à un profil.
function SaveSearchBar({
  deep,
  query,
  dateFrom,
  dateTo,
  alreadySavedId,
}: {
  deep: DeepSearchResponse;
  query: string;
  dateFrom: string;
  dateTo: string;
  alreadySavedId?: string;
}) {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [doctorId, setDoctorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(alreadySavedId ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDoctors().then(setDoctors);
  }, []);

  useEffect(() => {
    setSavedId(alreadySavedId ?? null);
    setError(null);
  }, [query, alreadySavedId]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const s = await saveSearch({
        query,
        payload: deep,
        doctor_id: doctorId || null,
        method: "v2",
        params: { date_from: dateFrom, date_to: dateTo },
      });
      setSavedId(s.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Échec de la sauvegarde");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="save-bar">
      <label className="save-bar-label">Profil</label>
      <select
        value={doctorId}
        onChange={(e) => setDoctorId(e.target.value)}
        disabled={busy || !!savedId}
      >
        <option value="">— Aucun profil —</option>
        {doctors.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
            {d.profile?.specialty_main ? ` · ${d.profile.specialty_main}` : ""}
          </option>
        ))}
      </select>
      {savedId ? (
        <span className="meta" style={{ margin: 0 }}>
          ✓ Sauvegardée — <Link href="/recherches">voir mes recherches</Link>
        </span>
      ) : (
        <button type="button" className="primary" onClick={save} disabled={busy}>
          {busy ? "…" : "💾 Sauvegarder cette recherche"}
        </button>
      )}
      {error && (
        <span className="error" style={{ margin: 0 }}>
          {error}
        </span>
      )}
    </div>
  );
}

// Icône loupe de la barre de recherche.
const SearchIcon = (
  <svg viewBox="0 0 24 24" className="icon">
    <circle cx="11" cy="11" r="7" />
    <path d="M21 21l-4.3-4.3" />
  </svg>
);

export default function Home() {
  const [mode, setMode] = useState<Mode>("pubmed_v2");
  const [q, setQ] = useState("");
  const [mesh, setMesh] = useState<string[]>([]);
  const [meshMode, setMeshMode] = useState<"and" | "or">("or");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [evidenceMax, setEvidenceMax] = useState("");

  const [dateFrom, setDateFrom] = useState("2025-01-01");
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));

  const [meshInput, setMeshInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [models, setModels] = useState<EmbeddingModelInfo[]>([]);
  const [model, setModel] = useState("");

  // Recherche PubMed + IA : filtre lexical+MeSH local borné, puis un appel codex
  // de jugement (méthode unique).
  const isPubmed = mode === "pubmed_v2";

  // Algo PubMed : v1 (tri par score IA) ou v2 « hybride re-classé » (tri par
  // pertinence PubMed Best Match + k_pubmed élevé). Ref pour éviter une lecture
  // périmée dans runSearch au moment où on bascule.
  const [algo, setAlgo] = useState<"v1" | "v2">("v1");
  const algoRef = useRef(algo);

  const [data, setData] = useState<SearchResponse | null>(null);
  const [deep, setDeep] = useState<DeepSearchResponse | null>(null);
  const [savedHit, setSavedHit] = useState<{ id: string; created_at: string } | null>(null);
  const [logs, setLogs] = useState<PubmedLog[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  // Jugement d'un lot supplémentaire (« Analyser 50 de plus ») en cours.
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codexLimit, setCodexLimit] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const moreRef = useRef<EventSource | null>(null);

  // Analyse critique comparative : PMID sélectionnés (≤ MAX_COMPARE), résultat,
  // déroulé et état de l'appel codex.
  const [selected, setSelected] = useState<number[]>([]);
  const [analysis, setAnalysis] = useState<CompareResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisLogs, setAnalysisLogs] = useState<PubmedLog[]>([]);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  // Ordre de sélection figé au lancement (stabilise les colonnes du tableau).
  const [analysisOrder, setAnalysisOrder] = useState<number[]>([]);
  const critiqueRef = useRef<EventSource | null>(null);

  useEffect(
    () => () => {
      esRef.current?.close();
      moreRef.current?.close();
      critiqueRef.current?.close();
    },
    [],
  );

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
    critiqueRef.current = analyzeCompareStream(q.trim(), order, {
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

  // Langue d'affichage (préférence persistante) + traduction à la demande des
  // résultats quand on bascule en français (un seul appel par lot, cache global).
  const [lang, setLang] = useDisplayLang();
  const { resolve: resolveLang, busy: translating } = useTranslatedHits(
    deep?.results ?? [],
    lang,
  );

  // Classement identique au backend : score décroissant (non jugé en dernier),
  // niveau de preuve croissant, puis année décroissante.
  const sortDeep = (rows: DeepHit[]): DeepHit[] =>
    [...rows].sort(
      (a, b) =>
        (b.score ?? -1) - (a.score ?? -1) ||
        (a.evidence_level ?? 99) - (b.evidence_level ?? 99) ||
        (b.pub_year ?? 0) - (a.pub_year ?? 0),
    );

  // « Analyser 50 de plus » : juge le prochain lot de `remaining` puis fusionne.
  function loadMore() {
    if (!deep?.remaining?.length || loadingMore) return;
    const next = deep.remaining.slice(0, 50);
    setLoadingMore(true);
    setError(null);
    moreRef.current?.close();
    moreRef.current = searchPubmedDeepMoreStream(q.trim(), next, {
      onLog: (log) => {
        setLogs((prev) => [...prev, log]);
        if (log.phase === "codex_limit") setCodexLimit(true);
      },
      onResult: (res) => {
        if (res.codex_limit) setCodexLimit(true);
        setDeep((prev) => {
          if (!prev) return prev;
          const known = new Set(prev.results.map((r) => r.pmid));
          const merged = sortDeep([
            ...prev.results,
            ...res.results.filter((r) => !known.has(r.pmid)),
          ]);
          return {
            ...prev,
            results: merged,
            remaining: (prev.remaining ?? []).slice(next.length),
            counts: {
              ...prev.counts,
              judged: (prev.counts.judged ?? 0) + res.judged,
              kept: merged.length,
            },
          };
        });
        setLoadingMore(false);
      },
      onError: (msg) => {
        if (msg && /usage limit|limite d'usage|rate limit/i.test(msg))
          setCodexLimit(true);
        setError(msg || "L'analyse du lot suivant a échoué.");
        setLoadingMore(false);
      },
      onTranslations: (fr) =>
        setDeep((prev) =>
          prev
            ? {
                ...prev,
                results: prev.results.map((r) =>
                  fr[String(r.pmid)]
                    ? {
                        ...r,
                        abstract_fr: fr[String(r.pmid)].abstract_fr,
                        title_fr: fr[String(r.pmid)].title_fr || r.title_fr,
                      }
                    : r,
                ),
              }
            : prev,
        ),
    });
  }

  useEffect(() => {
    listModels().then((ms) => {
      setModels(ms);
      const ready =
        ms.find((m) => m.name === "bge_m3" && m.embedded > 0) ||
        ms.find((m) => m.embedded > 0) ||
        ms[0];
      if (ready) setModel(ready.name);
    });
  }, []);

  const acTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (acTimer.current) clearTimeout(acTimer.current);
    if (!meshInput.trim()) {
      setSuggestions([]);
      return;
    }
    acTimer.current = setTimeout(async () => {
      setSuggestions(await meshAutocomplete(meshInput.trim()));
    }, 180);
  }, [meshInput]);

  function syncUrl(m: Mode, query: string) {
    const sp = new URLSearchParams();
    sp.set("mode", m);
    if (query.trim()) sp.set("q", query.trim());
    if (m === "pubmed_v2") {
      if (dateFrom) sp.set("from", dateFrom);
      if (dateTo) sp.set("to", dateTo);
    }
    window.history.replaceState(null, "", `?${sp.toString()}`);
  }

  function selectMode(m: Mode) {
    setMode(m);
    syncUrl(m, q);
  }

  // Clic sur la pastille de méthode.
  function selectMethod(method: "pubmed" | "semantic" | "keyword") {
    if (method === "pubmed") selectMode("pubmed_v2");
    else selectMode(method);
  }

  // Bascule algo v1/v2 : on met la ref à jour AVANT de relancer (setAlgo est
  // asynchrone) pour que runSearch lise bien la nouvelle valeur. Relance à chaud
  // pour comparer les deux tris sur la même requête.
  function switchAlgo(v: "v1" | "v2") {
    if (v === algo) return;
    algoRef.current = v;
    setAlgo(v);
    if (isPubmed && q.trim()) runSearch(0, { force: true });
  }

  const autorun = useRef(false);
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const m = sp.get("mode");
    const query = sp.get("q");
    if (m === "pubmed_v2" || m === "semantic" || m === "keyword") {
      setMode(m);
    } else if (m === "pubmed" || m === "pubmed_v1") {
      // rétro-compat des anciens liens (?mode=pubmed, ?mode=pubmed_v1) → méthode unique.
      setMode("pubmed_v2");
    }
    const from = sp.get("from");
    const to = sp.get("to");
    if (from) setDateFrom(from);
    if (to) setDateTo(to);
    if (query) {
      setQ(query);
      autorun.current = true;
    }
  }, []);

  useEffect(() => {
    if (!autorun.current) return;
    if (mode === "semantic" && !model) return;
    autorun.current = false;
    runSearch(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, model, q]);

  async function runSearch(newOffset = 0, opts: { force?: boolean } = {}) {
    setLoading(true);
    setError(null);
    setCodexLimit(false);
    syncUrl(mode, q);
    try {
      if (isPubmed) {
        if (!q.trim()) {
          setLoading(false);
          return;
        }
        setData(null);
        setDeep(null);
        setSavedHit(null);
        setLogs([]);
        setOffset(0);
        setLoadingMore(false);
        clearSelection();
        esRef.current?.close();
        moreRef.current?.close();
        // Recherche PubMed + IA : streaming SSE (déroulé en direct) pour ne pas
        // se faire couper par le proxy sur les requêtes longues.
        // Avant tout appel codex (coûteux), on regarde si une recherche identique
        // a déjà été sauvegardée : on réaffiche alors le snapshot.
        // `force` (bouton « Relancer quand même ») court-circuite ce cache.
        if (!opts.force) {
          let existing = null;
          try {
            existing = await lookupSavedSearch({
              query: q.trim(),
              date_from: dateFrom || undefined,
              date_to: dateTo || undefined,
            });
          } catch {
            /* lookup best-effort : en cas d'échec, on relance la recherche */
          }
          if (existing) {
            setDeep(existing.payload);
            setSavedHit({ id: existing.id, created_at: existing.created_at });
            setLoading(false);
            return;
          }
        }
        esRef.current = searchPubmedDeepStream(
          q.trim(),
          dateFrom || undefined,
          dateTo || undefined,
          algoRef.current === "v2" ? 100 : 12,
          {
            onLog: (log) => {
              setLogs((prev) => [...prev, log]);
              if (log.phase === "codex_limit") setCodexLimit(true);
            },
            onResult: (res) => {
              setDeep(res);
              if (res.codex_limit) setCodexLimit(true);
              setLoading(false);
            },
            onError: (msg) => {
              if (msg && /usage limit|limite d'usage|rate limit/i.test(msg))
                setCodexLimit(true);
              setError(msg || "La recherche a échoué.");
              setLoading(false);
            },
            // Traductions FR qui arrivent après les résultats : on les fusionne.
            onTranslations: (fr) =>
              setDeep((prev) =>
                prev
                  ? {
                      ...prev,
                      results: prev.results.map((r) =>
                        fr[String(r.pmid)]
                          ? {
                              ...r,
                              abstract_fr: fr[String(r.pmid)].abstract_fr,
                              title_fr: fr[String(r.pmid)].title_fr || r.title_fr,
                            }
                          : r,
                      ),
                    }
                  : prev,
              ),
          },
          algoRef.current === "v2",
        );
        return; // `loading` reste vrai jusqu'à onResult/onError
      }
      let res: SearchResponse;
      if (mode === "semantic") {
        if (!q.trim()) {
          setLoading(false);
          return;
        }
        res = await searchSemantic(q.trim(), model, PAGE);
      } else {
        res = await searchMesh({
          q: q.trim() || undefined,
          mesh,
          mode: meshMode,
          yearFrom: yearFrom ? Number(yearFrom) : undefined,
          yearTo: yearTo ? Number(yearTo) : undefined,
          evidenceMax: evidenceMax ? Number(evidenceMax) : undefined,
          limit: PAGE,
          offset: newOffset,
        });
      }
      setData(res);
      setDeep(null);
      setOffset(newOffset);
      setLoading(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
      setData(null);
      setDeep(null);
      setLoading(false);
    }
  }

  function addMesh(term: string) {
    if (!mesh.includes(term)) setMesh([...mesh, term]);
    setMeshInput("");
    setSuggestions([]);
  }

  const selectedModel = models.find((m) => m.name === model);
  const noEmbeddings = mode === "semantic" && selectedModel && selectedModel.embedded === 0;

  const topScore =
    data && data.results.length ? Math.max(0, ...data.results.map((r) => r.score ?? 0)) : 0;
  const weakSemantic =
    mode === "semantic" && data !== null && data.results.length > 0 && topScore < SEM_RELEVANT;

  return (
    <main className="xm-page">
      <h1 className="xm-hero">Que voulez-vous comprendre aujourd’hui&nbsp;?</h1>

      <form
        className="xm-searchbar"
        onSubmit={(e) => {
          e.preventDefault();
          runSearch(0);
        }}
      >
        {SearchIcon}
        <input
          type="text"
          placeholder={
            mode === "semantic"
              ? "Ex. : crise cardiaque chez le patient diabétique âgé…"
              : isPubmed
                ? "Décrivez votre question clinique en français…"
                : "Mots-clés (anglais) : myocardial infarction, diabetes…"
          }
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" className="xm-explore" disabled={loading}>
          {loading ? "…" : "Explorer →"}
        </button>
      </form>

      <div className="xm-method-row">
        <span className="xm-method-label">MÉTHODE</span>
        <button
          type="button"
          className={`xm-chip ${isPubmed ? "on" : ""}`}
          onClick={() => selectMethod("pubmed")}
        >
          PubMed + IA
        </button>
        <button
          type="button"
          className={`xm-chip ${mode === "semantic" ? "on" : ""}`}
          onClick={() => selectMethod("semantic")}
        >
          Par sens
        </button>
        <button
          type="button"
          className={`xm-chip ${mode === "keyword" ? "on" : ""}`}
          onClick={() => selectMethod("keyword")}
        >
          Mots-clés / MeSH
        </button>

        {isPubmed && (
          <div className="xm-daterange">
            <svg viewBox="0 0 24 24">
              <rect x="3" y="5" width="18" height="16" rx="2" />
              <path d="M3 9h18M8 3v4M16 3v4" />
            </svg>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            <span className="sep">→</span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
        )}

        {isPubmed && (
          <div
            className="xm-algo-toggle"
            title="v1 = tri par score IA · v2 = tri par pertinence PubMed (Best Match) + vivier PubMed élargi"
          >
            <span className="xm-method-label">TRI</span>
            <button
              type="button"
              className={`xm-chip ${algo === "v1" ? "on" : ""}`}
              onClick={() => switchAlgo("v1")}
            >
              v1 · score IA
            </button>
            <button
              type="button"
              className={`xm-chip ${algo === "v2" ? "on" : ""}`}
              onClick={() => switchAlgo("v2")}
            >
              v2 · PubMed
            </button>
          </div>
        )}
      </div>

      {/* PubMed + IA : note de fonctionnement (méthode unique). */}
      {isPubmed && (
        <p
          className="meta"
          style={{ margin: "12px 2px 0", color: "var(--faint)", fontSize: 12.5 }}
        >
          L’IA construit une requête experte, on pré-filtre la base en local
          (mots-clés + MeSH), puis GPT-5.4 lit et juge uniquement ces candidats —
          rapide, insensible à la largeur de la période.
        </p>
      )}

      {/* Sémantique : sélecteur de modèle d'embedding. */}
      {mode === "semantic" && (
        <div className="filters">
          <div className="field">
            <label>Modèle d&apos;embedding</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name} ({m.embedded.toLocaleString("fr-FR")} articles)
                </option>
              ))}
            </select>
          </div>
          {noEmbeddings && (
            <p className="error" style={{ alignSelf: "center" }}>
              ⚠ Ce modèle n&apos;a pas encore d&apos;articles vectorisés.
            </p>
          )}
        </div>
      )}

      {/* Mots-clés : chips MeSH + filtres. */}
      {mode === "keyword" && (
        <>
          <div className="mesh-box">
            {mesh.length > 0 && (
              <div className="chips">
                {mesh.map((m) => (
                  <span className="chip" key={m}>
                    {m}
                    <button
                      type="button"
                      onClick={() => setMesh(mesh.filter((x) => x !== m))}
                      aria-label={`Retirer ${m}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <input
              type="text"
              placeholder="Ajouter un tag MeSH (autocomplétion)…"
              value={meshInput}
              onChange={(e) => setMeshInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && suggestions.length) {
                  e.preventDefault();
                  addMesh(suggestions[0]);
                }
              }}
              style={{ width: "100%" }}
            />
            {suggestions.length > 0 && (
              <div className="suggestions">
                {suggestions.map((s) => (
                  <div key={s} onClick={() => addMesh(s)}>
                    {s}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="filters">
            {mesh.length > 1 && (
              <div className="field">
                <label>Combinaison des tags</label>
                <div className="toggle">
                  <button type="button" className={meshMode === "or" ? "on" : ""} onClick={() => setMeshMode("or")}>
                    OU
                  </button>
                  <button type="button" className={meshMode === "and" ? "on" : ""} onClick={() => setMeshMode("and")}>
                    ET
                  </button>
                </div>
              </div>
            )}
            <div className="field">
              <label>Année min.</label>
              <input type="number" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} placeholder="1975" />
            </div>
            <div className="field">
              <label>Année max.</label>
              <input type="number" value={yearTo} onChange={(e) => setYearTo(e.target.value)} placeholder="2026" />
            </div>
            <div className="field">
              <label>Niveau de preuve max.</label>
              <select value={evidenceMax} onChange={(e) => setEvidenceMax(e.target.value)}>
                <option value="">Tous</option>
                <option value="1">1 — élevée</option>
                <option value="2">≤ 2</option>
                <option value="3">≤ 3</option>
                <option value="4">≤ 4</option>
              </select>
            </div>
          </div>
        </>
      )}

      {codexLimit && (
        <div className="xm-banner error" role="alert">
          🚫 <b>Limite d’usage GPT-5.4 atteinte.</b> Les recherches «&nbsp;PubMed +
          codex&nbsp;» reposent sur GPT-5.4 (construction de la requête, tri et
          traduction) : le quota est épuisé pour le moment. Les résultats sont en{" "}
          <b>mode dégradé</b> (sans tri intelligent ni traduction FR). Réessayez un
          peu plus tard.
        </div>
      )}

      {error && <p className="xm-banner error">⚠ {error}</p>}

      {(loading || loadingMore || (isPubmed && logs.length > 0)) && (
        <LiveEvents
          running={loading || loadingMore}
          variant={isPubmed ? "pubmed" : "other"}
          logs={logs}
        />
      )}

      {/* ---------- Résultats sémantique / mots-clés ---------- */}
      {data && (
        <>
          <div className="xm-results-head">
            <span className="xm-results-count">
              {data.total.toLocaleString("fr-FR")} résultat(s)
              {mode === "keyword" &&
                data.total > 0 &&
                ` · affichage ${offset + 1}–${Math.min(offset + PAGE, data.total)}`}
            </span>
            <CopyLinkButton />
          </div>

          {weakSemantic && (
            <p className="xm-banner warn">
              Aucun article vraiment pertinent pour cette requête. Le périmètre couvert
              par la recherche sémantique est encore limité (surtout gynéco-obstétrique
              &amp; ophtalmologie) — les résultats ci-dessous sont les plus proches, pas
              forcément adaptés. Essayez le mode «&nbsp;Mots-clés&nbsp;».
            </p>
          )}

          <div>
            {data.results.map((r: ArticleResult, i: number) => {
              const e = r.explanation;
              const hasExp = !!(
                e &&
                (e.concepts.length > 0 || e.population || e.intervention || e.study_type)
              );
              const detail =
                r.abstract_snippet || hasExp ? (
                  <>
                    {r.abstract_snippet && (
                      <span style={{ whiteSpace: "pre-line" }}>{r.abstract_snippet}</span>
                    )}
                    <Explanation article={r} />
                  </>
                ) : undefined;
              return (
                <XMedResult
                  key={r.pmid}
                  rank={offset + i + 1}
                  title={r.title}
                  journal={r.journal}
                  year={r.pub_year}
                  level={r.evidence_level}
                  relevance={
                    mode === "semantic" && r.score != null ? semanticRelevance(r.score) : undefined
                  }
                  pubmedUrl={r.pubmed_url}
                  mesh={r.mesh_terms ?? undefined}
                >
                  {detail}
                </XMedResult>
              );
            })}
          </div>

          {mode === "keyword" && data.total > PAGE && (
            <div className="pager">
              <button disabled={offset === 0 || loading} onClick={() => runSearch(Math.max(0, offset - PAGE))}>
                ← Précédent
              </button>
              <button disabled={offset + PAGE >= data.total || loading} onClick={() => runSearch(offset + PAGE)}>
                Suivant →
              </button>
            </div>
          )}
        </>
      )}

      {/* ---------- Résultats PubMed v2 (deep) ---------- */}
      {deep && (
        <>
          <div className="xm-results-head">
            <span className="xm-results-count">
              {deep.counts.kept ?? 0} retenu(s) · {deep.counts.judged ?? 0} jugés codex ·{" "}
              {deep.counts.merged ?? 0} fusionnés
            </span>
            <CopyLinkButton />
          </div>

          {savedHit && (
            <p
              className="xm-banner info"
              style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}
            >
              <span>
                💾 Résultat déjà sauvegardé le{" "}
                {new Date(savedHit.created_at).toLocaleDateString("fr-FR", {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}{" "}
                — affiché sans relancer codex.
              </span>
              <button
                type="button"
                style={{ minHeight: 32, padding: "4px 12px" }}
                onClick={() => runSearch(0, { force: true })}
              >
                Relancer quand même
              </button>
            </p>
          )}

          {!loading && deep.results.length > 0 && (
            <SaveSearchBar
              deep={deep}
              query={q.trim()}
              dateFrom={dateFrom}
              dateTo={dateTo}
              alreadySavedId={savedHit?.id}
            />
          )}

          {deep.pubmed_query && (
            <details className="explanation">
              <summary>Requête PubMed générée + mots-clés</summary>
              <p className="abstract" style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>
                {deep.pubmed_query}
              </p>
              {deep.keywords_en.length > 0 && (
                <div className="tags">
                  {deep.keywords_en.slice(0, 12).map((t) => (
                    <span className="tag" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </details>
          )}

          {deep.judge === "skipped" && (
            <p className="xm-banner warn">
              ⚠ codex indisponible : tri lexical de repli (pas de jugement de pertinence).
            </p>
          )}
          {deep.results.length === 0 && (
            <p className="xm-banner warn">Aucun article jugé pertinent pour cette recherche.</p>
          )}

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
          {analyzing && <LiveEvents running variant="other" logs={analysisLogs} />}
          {analysisError && (
            <p className="xm-banner warn">⚠ {analysisError}</p>
          )}
          {analysis && <CritiquePanel result={analysis} order={analysisOrder} />}

          <div>
            {deep.results.map((r, i) => {
              const d = resolveLang(r);
              return (
                <XMedResult
                  key={`deep-${r.pmid}`}
                  rank={i + 1}
                  title={d.title}
                  journal={r.journal}
                  year={r.pub_year}
                  level={r.evidence_level}
                  relevance={
                    r.score != null
                      ? deepRelevance(r.score, r.relevance_pct)
                      : undefined
                  }
                  contribution={r.reason}
                  extraActions={
                    <SelectButton
                      selected={selected.includes(r.pmid)}
                      disabled={
                        !selected.includes(r.pmid) && selected.length >= MAX_COMPARE
                      }
                      onToggle={() => toggleSelected(r.pmid)}
                    />
                  }
                  sourceTag={
                    r.source === "both"
                      ? "A · PubMed + B · local"
                      : r.source === "pubmed"
                        ? "A · PubMed"
                        : "B · local"
                  }
                  pubmedUrl={r.pubmed_url}
                  sourceTitle={r.title}
                  revealLabel="Résumé structuré"
                  revealBodyClassName="xmr-sections"
                  revealHead={
                    <LanguageToggle lang={lang} onChange={setLang} busy={translating} />
                  }
                  spoken={d.abstract ?? r.reason ?? undefined}
                >
                  {d.abstract ? (
                    <StructuredAbstract abstract={d.abstract} translated={d.translated} />
                  ) : undefined}
                </XMedResult>
              );
            })}
          </div>

          {deep.judge === "codex" && (deep.remaining?.length ?? 0) > 0 && (
            <div style={{ textAlign: "center", marginTop: 16 }}>
              <button
                type="button"
                className="primary"
                disabled={loadingMore}
                onClick={loadMore}
              >
                {loadingMore
                  ? "Analyse en cours…"
                  : `Analyser ${Math.min(50, deep.remaining!.length)} de plus`}
              </button>
              <p className="meta" style={{ marginTop: 6 }}>
                {deep.remaining!.length} abstract(s) pré-filtré(s) restant(s) à juger.
              </p>
            </div>
          )}
        </>
      )}

      <p className="xm-disclaimer">
        Pertinence jugée par l’IA à partir des abstracts PubMed — un appui à la
        lecture, pas une validation clinique.
      </p>
    </main>
  );
}
