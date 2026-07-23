"use client";

import { useEffect, useRef, useState } from "react";
import {
  analyzeCompareStream,
  DeepSearchResponse,
  Doctor,
  listDoctors,
  lookupSavedSearch,
  PubmedLog,
  saveSearch,
  searchPubmedDeepMoreStream,
  searchPubmedDeepStream,
  stopDeepSearch,
  stopLocalSearch,
} from "@/lib/api";
import type { CompareResult, DeepHit } from "@/lib/api";
import Link from "next/link";
import XMedResult, { deepRelevance, StructuredAbstract } from "./XMedResult";
import { CritiquePanel, MAX_COMPARE, SelectButton } from "./Critique";
import { LanguageToggle, useDisplayLang, useTranslatedHits } from "./lang";

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
  stopLocal,
}: {
  running: boolean;
  variant: "pubmed" | "other";
  logs: PubmedLog[];
  // Bouton « arrêter la recherche locale » : fourni uniquement pendant que la
  // requête FTS locale tourne (annulable côté Postgres, la recherche continue
  // ensuite avec PubMed seul).
  stopLocal?: { stopping: boolean; onStop: () => void } | null;
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
            {stopLocal && (
              <button
                type="button"
                className="xm-live-stop"
                onClick={stopLocal.onStop}
                disabled={stopLocal.stopping}
              >
                {stopLocal.stopping
                  ? "Arrêt de la recherche locale…"
                  : "⏹ Arrêter la recherche locale (continuer avec PubMed seul)"}
              </button>
            )}
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
  const [q, setQ] = useState("");

  const [dateFrom, setDateFrom] = useState("2025-01-01");
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));

  // Algo PubMed : v1 (tri par score IA) ou v2 « hybride re-classé » (tri par
  // pertinence PubMed Best Match + k_pubmed élevé). Ref pour éviter une lecture
  // périmée dans runSearch au moment où on bascule.
  const [algo, setAlgo] = useState<"v1" | "v2">("v1");
  const algoRef = useRef(algo);
  // Curseurs v2 : total analysé par lot (judge_batch) et minimum d'articles locaux
  // garantis dans le lot (local_floor). N'ont d'effet qu'en v2 (fusion RRF).
  const [judgeBatch, setJudgeBatch] = useState(50);
  const [localFloor, setLocalFloor] = useState(0);

  const [deep, setDeep] = useState<DeepSearchResponse | null>(null);
  const [savedHit, setSavedHit] = useState<{ id: string; created_at: string } | null>(null);
  const [logs, setLogs] = useState<PubmedLog[]>([]);
  const [loading, setLoading] = useState(false);
  // Jugement d'un lot supplémentaire (« Analyser 50 de plus ») en cours.
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codexLimit, setCodexLimit] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const moreRef = useRef<EventSource | null>(null);
  // Bouton stop de la requête locale (FTS) : jeton propre à chaque recherche,
  // passé au stream pour que le backend sache quelle requête Postgres annuler.
  // Le même jeton sert au bouton « Arrêter » global (annulation de TOUTE la
  // recherche : codex tué + pipeline stoppé côté serveur).
  const localTokenRef = useRef<string>("");
  const [stoppingLocal, setStoppingLocal] = useState(false);
  // Fenêtre de garde après un clic sur « Arrêter » (voir handleStopSearch) :
  // ignore toute resoumission du formulaire (double-clic, touche Entrée) le
  // temps que le bouton reprenne son état normal.
  const [justStopped, setJustStopped] = useState(false);
  // Numéro de lancement : incrémenté à chaque recherche ET à chaque arrêt. Une
  // étape asynchrone (lookup du cache des recherches sauvegardées) ne poursuit
  // que si son numéro est encore le courant — sinon la recherche a été arrêtée
  // ou remplacée entre-temps.
  const runIdRef = useRef(0);

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
            "Limite d'usage GPT-5.6 atteinte — réessayez l'analyse plus tard.",
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

  function syncUrl(query: string) {
    const sp = new URLSearchParams();
    if (query.trim()) sp.set("q", query.trim());
    if (dateFrom) sp.set("from", dateFrom);
    if (dateTo) sp.set("to", dateTo);
    window.history.replaceState(null, "", `?${sp.toString()}`);
  }

  // Bascule algo v1/v2 : on met la ref à jour en même temps que l'état (setAlgo
  // est asynchrone) pour que la PROCHAINE recherche lise la bonne valeur. Ne
  // relance rien : comme les dates et les curseurs, ce choix ne prend effet
  // qu'au clic sur « Explorer » — seul déclencheur d'une recherche.
  function switchAlgo(v: "v1" | "v2") {
    if (v === algo) return;
    algoRef.current = v;
    setAlgo(v);
  }

  const autorun = useRef(false);
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const query = sp.get("q");
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
    autorun.current = false;
    runSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  async function runSearch(opts: { force?: boolean } = {}) {
    const runId = ++runIdRef.current;
    setLoading(true);
    setError(null);
    setCodexLimit(false);
    syncUrl(q);
    try {
      if (!q.trim()) {
        setLoading(false);
        return;
      }
      setDeep(null);
      setSavedHit(null);
      setLogs([]);
      setLoadingMore(false);
      clearSelection();
      esRef.current?.close();
      moreRef.current?.close();
      localTokenRef.current =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setStoppingLocal(false);
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
        // Arrêtée ou remplacée pendant le lookup : ne pas ouvrir le stream.
        if (runId !== runIdRef.current) return;
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
        algoRef.current === "v2" ? 50 : 20,
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
          // Recherche arrêtée côté serveur (normalement le clic sur « Arrêter »
          // a déjà tout remis en état ici — filet de sécurité).
          onStopped: () => setLoading(false),
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
        {
          rrf: algoRef.current === "v2",
          judgeBatch,
          localFloor: algoRef.current === "v2" ? localFloor : 0,
          localToken: localTokenRef.current,
        },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
      setDeep(null);
      setLoading(false);
    }
  }

  // La requête FTS locale tourne si le dernier événement du déroulé est
  // `filter_start` : l'événement suivant (filter / filter_timeout / filter_stopped)
  // la clôt et fait disparaître le bouton stop de lui-même.
  const localSearching =
    loading && logs.length > 0 && logs[logs.length - 1].phase === "filter_start";

  async function handleStopLocal() {
    setStoppingLocal(true);
    const ok = await stopLocalSearch(localTokenRef.current);
    // Rien n'était à annuler (requête déjà terminée) : on réactive le bouton,
    // le log de clôture qui arrive le fera disparaître de toute façon.
    if (!ok) setStoppingLocal(false);
  }

  // Bouton « Arrêter » global : abandonne TOUTE la recherche PubMed + IA en cours
  // (faute de frappe, envie de reformuler…). On coupe le flux SSE, on demande au
  // serveur de tuer l'appel codex + la requête locale (best-effort, sans attendre
  // la réponse), et la barre redevient utilisable immédiatement.
  function handleStopSearch() {
    runIdRef.current++; // invalide le lookup de cache éventuellement en vol
    esRef.current?.close();
    void stopDeepSearch(localTokenRef.current);
    setLoading(false);
    setStoppingLocal(false);
    // Fenêtre de garde : sans elle, le bouton « Arrêter » redevient « Explorer →»
    // (submit) au même endroit sous le curseur au rendu suivant. Un double-clic
    // (réflexe naturel quand l'arrêt semble ne rien faire) atterrit alors sur
    // « Explorer » et relance aussitôt une recherche complète — d'où l'impression
    // que le bouton stop « relance une recherche ». On bloque les resoumissions
    // pendant un court instant le temps que l'utilisateur voie que c'est arrêté.
    setJustStopped(true);
    window.setTimeout(() => setJustStopped(false), 600);
    setLogs((prev) => [
      ...prev,
      {
        phase: "stopped",
        msg: "⏹️ Recherche arrêtée — corrigez votre question et relancez quand vous voulez.",
      },
    ]);
  }

  return (
    <main className="xm-page">
      <h1 className="xm-hero">Que recherchez-vous aujourd’hui, Docteur&nbsp;?</h1>

      <form
        className="xm-searchbar"
        onSubmit={(e) => {
          e.preventDefault();
          if (justStopped) return; // voir handleStopSearch : anti double-clic/Entrée
          runSearch();
        }}
      >
        {SearchIcon}
        <input
          type="text"
          placeholder="Décrivez votre question clinique en français…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {loading ? (
          // Pendant une recherche PubMed + IA, « Explorer » devient « Arrêter » :
          // on peut abandonner à tout moment pour corriger ou reformuler.
          <button
            type="button"
            className="xm-explore xm-explore-stop"
            onClick={handleStopSearch}
            title="Arrêter la recherche en cours (pour corriger ou changer votre question)"
          >
            ⏹ Arrêter
          </button>
        ) : justStopped ? (
          // Fenêtre de garde : le bouton reste visiblement « arrêté » un court
          // instant plutôt que de redevenir aussitôt cliquable au même endroit.
          <button type="button" className="xm-explore" disabled>
            ⏹ Arrêté
          </button>
        ) : (
          <button type="submit" className="xm-explore" disabled={loading}>
            {loading ? "…" : "Explorer →"}
          </button>
        )}
      </form>

      <div className="xm-method-row">
        <div className="xm-daterange">
          <svg viewBox="0 0 24 24">
            <rect x="3" y="5" width="18" height="16" rx="2" />
            <path d="M3 9h18M8 3v4M16 3v4" />
          </svg>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <span className="sep">→</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>

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
            v2 · fusion RRF
          </button>
        </div>
      </div>

      {/* Curseurs v2 : total analysé par lot + minimum local garanti dans le lot. */}
      {algo === "v2" && (
        <div className="xm-sliders">
          <label className="xm-slider">
            <span>
              Analysés par lot : <strong>{judgeBatch}</strong>
            </span>
            <input
              type="range"
              min={20}
              max={100}
              step={10}
              value={judgeBatch}
              onChange={(e) => {
                const v = Number(e.target.value);
                setJudgeBatch(v);
                setLocalFloor((f) => Math.min(f, v));
              }}
            />
          </label>
          <label className="xm-slider">
            <span>
              Minimum local garanti : <strong>{localFloor}</strong>
            </span>
            <input
              type="range"
              min={0}
              max={judgeBatch}
              step={5}
              value={localFloor}
              onChange={(e) => setLocalFloor(Number(e.target.value))}
            />
          </label>
          <span className="xm-slider-hint">
            RRF choisit les candidats · le tri reste par score Codex · appliqué à la
            prochaine recherche
          </span>
        </div>
      )}

      <p
        className="meta"
        style={{ margin: "12px 2px 0", color: "var(--faint)", fontSize: 12.5 }}
      >
        L’IA construit une requête experte, on pré-filtre la base en local
        (mots-clés + MeSH), puis GPT-5.6 lit et juge uniquement ces candidats —
        rapide, insensible à la largeur de la période.
      </p>

      {codexLimit && (
        <div className="xm-banner error" role="alert">
          🚫 <b>Limite d’usage GPT-5.6 atteinte.</b> Les recherches «&nbsp;PubMed +
          codex&nbsp;» reposent sur GPT-5.6 (construction de la requête, tri et
          traduction) : le quota est épuisé pour le moment. Les résultats sont en{" "}
          <b>mode dégradé</b> (sans tri intelligent ni traduction FR). Réessayez un
          peu plus tard.
        </div>
      )}

      {error && <p className="xm-banner error">⚠ {error}</p>}

      {(loading || loadingMore || logs.length > 0) && (
        <LiveEvents
          running={loading || loadingMore}
          variant="pubmed"
          logs={logs}
          stopLocal={
            localSearching
              ? { stopping: stoppingLocal, onStop: handleStopLocal }
              : null
          }
        />
      )}

      {/* ---------- Résultats PubMed v2 (deep) ---------- */}
      {deep && (
        <>
          <div className="xm-results-head">
            <span className="xm-results-count">
              {deep.counts.kept ?? 0} retenu(s) · {deep.counts.judged ?? 0} jugés codex ·{" "}
              {deep.counts.merged ?? 0} fusionnés
              {deep.counts.kept_local != null && (
                <>
                  {" · "}
                  <span className="xm-src pm">
                    {deep.counts.kept_pubmed ?? 0} PubMed
                  </span>
                  {" · "}
                  <span className="xm-src lo">{deep.counts.kept_local ?? 0} local</span>
                  {(deep.counts.kept_both ?? 0) > 0 && (
                    <> · {deep.counts.kept_both} les deux</>
                  )}
                </>
              )}
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
                onClick={() => runSearch({ force: true })}
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
