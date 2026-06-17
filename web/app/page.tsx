"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArticleResult,
  DeepSearchResponse,
  Doctor,
  EmbeddingModelInfo,
  listDoctors,
  listModels,
  meshAutocomplete,
  PubmedLog,
  PubmedSearchResponse,
  saveSearch,
  searchMesh,
  searchPubmedDeepStream,
  searchPubmedStream,
  searchSemantic,
  SearchResponse,
} from "@/lib/api";
import Link from "next/link";

const PAGE = 20;
const EVIDENCE_LABEL: Record<number, string> = {
  1: "Preuve élevée",
  2: "Preuve modérée",
  3: "Cas / série",
  4: "Autre",
};

function Badge({ level }: { level: number | null }) {
  if (!level) return null;
  return (
    <span className={`badge ev${level}`}>
      Niv. {level} · {EVIDENCE_LABEL[level]}
    </span>
  );
}

// Seuils de pertinence pour la recherche par sens (similarité cosinus bge-m3).
// ⚠ Provisoires : à caler sur le gold set annoté par les médecins (/annotate).
const SEM_RELEVANT = 0.5; // en-dessous : on prévient que rien n'est vraiment pertinent
const SEM_FLOOR = 0.45; // en-dessous : hors périmètre couvert

// Barre de pertinence pour la recherche par sens.
// En sémantique pur, `score` EST la similarité cosinus (0–1) renvoyée par
// /search/semantic : un signal ABSOLU et interprétable. On l'affiche tel quel
// (plus de normalisation au meilleur de la page, qui faisait passer tous les
// résultats pour « ~100 % Très pertinent »).
function MatchBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tier =
    score >= 0.6 ? "high" : score >= SEM_RELEVANT ? "mid" : score >= SEM_FLOOR ? "low" : "off";
  const label =
    score >= 0.6
      ? "Très pertinent"
      : score >= SEM_RELEVANT
        ? "Pertinent"
        : score >= SEM_FLOOR
          ? "Lié"
          : "Hors périmètre";
  return (
    <div
      className="match"
      title={`Similarité de sens : ${score.toFixed(3)} (0–1, signal absolu, non normalisé).`}
    >
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="match-pct">{pct}%</span>
    </div>
  );
}

function CodexScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tier = score >= 0.75 ? "high" : score >= 0.55 ? "mid" : "low";
  const label =
    score >= 0.75 ? "Très pertinent" : score >= 0.55 ? "Pertinent" : "Partiel";
  return (
    <div className="match" title={`Score absolu GPT-5.4 : ${score.toFixed(2)} / 1.`}>
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="match-pct">{pct}%</span>
    </div>
  );
}

// Barre de score pour la méthode v2 (deep) : score entier 0–3 attribué par codex.
function DeepScoreBar({ score }: { score: number }) {
  const pct = Math.round((score / 3) * 100);
  const tier = score >= 3 ? "high" : score >= 2 ? "mid" : "low";
  const label = score >= 3 ? "Très pertinent" : score >= 2 ? "Pertinent" : "Partiel";
  return (
    <div className="match" title={`Score codex : ${score} / 3 (grille 0–3).`}>
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="match-pct">{score}/3</span>
    </div>
  );
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
    <details className="explanation">
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

// Deux onglets PubMed distincts : v2 (filtre + jugement) et v1 (lots d'abstracts).
type Mode = "pubmed_v2" | "pubmed_v1" | "semantic" | "keyword";

function CopyLinkButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-link"
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
      {copied ? "✓ Lien copié" : "🔗 Copier le lien"}
    </button>
  );
}

// Concepts MeSH défilants pendant l'attente (illustratif : rend le temps de
// recherche — parfois long quand codex lit les abstracts — plus vivant).
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

function SearchLoader({ variant }: { variant: "v1" | "v2" | "other" }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % MESH_SAMPLES.length), 1300);
    return () => clearInterval(t);
  }, []);
  const title =
    variant === "v1"
      ? "GPT-5.4 lit les abstracts par lots…"
      : variant === "v2"
        ? "Pré-filtre local puis jugement par codex…"
        : "Recherche en cours…";
  return (
    <div className="search-loader" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <div className="search-loader-text">
        <span className="search-loader-title">{title}</span>
        <span className="search-loader-mesh" key={i}>
          🔖 {MESH_SAMPLES[i]}
        </span>
      </div>
    </div>
  );
}

// Sauvegarde du résultat v2 courant : on enregistre le snapshot complet (pour
// relire/réutiliser sans relancer codex), rattaché à un profil au choix. Pour
// l'instant tout le monde voit toutes les recherches (page « Sauvegardées »).
function SaveSearchBar({
  deep,
  query,
  dateFrom,
  dateTo,
}: {
  deep: DeepSearchResponse;
  query: string;
  dateFrom: string;
  dateTo: string;
}) {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [doctorId, setDoctorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDoctors().then(setDoctors);
  }, []);

  // Une nouvelle recherche (autre requête) réarme le bouton.
  useEffect(() => {
    setSavedId(null);
    setError(null);
  }, [query]);

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
      {error && <span className="error" style={{ margin: 0 }}>{error}</span>}
    </div>
  );
}

export default function Home() {
  // v2 (filtre + jugement) est la recherche par défaut à l'arrivée sur le site.
  const [mode, setMode] = useState<Mode>("pubmed_v2");
  const [q, setQ] = useState("");
  const [mesh, setMesh] = useState<string[]>([]);
  const [meshMode, setMeshMode] = useState<"and" | "or">("or");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [evidenceMax, setEvidenceMax] = useState("");

  // Fenêtre de dates du mode PubMed. Défaut 2025-01-01 → aujourd'hui : aligne la
  // recherche PubMed sur la période couverte par notre base (2025-2026), pour que
  // les deux soient comparables.
  const [dateFrom, setDateFrom] = useState("2025-01-01");
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));

  const [meshInput, setMeshInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [models, setModels] = useState<EmbeddingModelInfo[]>([]);
  const [model, setModel] = useState("");

  // La méthode PubMed découle directement de l'onglet choisi.
  //  pubmed_v2 = filtre lexical+MeSH local borné, puis un appel codex de jugement.
  //  pubmed_v1 = codex lit tous les abstracts locaux de la fenêtre par lots.
  const isPubmed = mode === "pubmed_v1" || mode === "pubmed_v2";
  const pubmedVariant: "v1" | "v2" = mode === "pubmed_v1" ? "v1" : "v2";

  const [data, setData] = useState<SearchResponse | null>(null);
  const [pubmed, setPubmed] = useState<PubmedSearchResponse | null>(null);
  const [deep, setDeep] = useState<DeepSearchResponse | null>(null);
  const [logs, setLogs] = useState<PubmedLog[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Limite d'usage GPT-5.4 atteinte : on en informe l'utilisateur (bandeau).
  const [codexLimit, setCodexLimit] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Ferme le flux SSE en cours si le composant est démonté.
  useEffect(() => () => esRef.current?.close(), []);

  // modèles d'embedding disponibles (pour le mode sémantique)
  useEffect(() => {
    listModels().then((ms) => {
      setModels(ms);
      // bge-m3 par défaut : multilingue, adapté aux requêtes françaises.
      const ready =
        ms.find((m) => m.name === "bge_m3" && m.embedded > 0) ||
        ms.find((m) => m.embedded > 0) ||
        ms[0];
      if (ready) setModel(ready.name);
    });
  }, []);

  // autocomplétion MeSH
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

  // Synchronise le mode + la requête dans l'URL → lien partageable et reproductible.
  function syncUrl(m: Mode, query: string) {
    const sp = new URLSearchParams();
    sp.set("mode", m);
    if (query.trim()) sp.set("q", query.trim());
    if (m === "pubmed_v1" || m === "pubmed_v2") {
      if (dateFrom) sp.set("from", dateFrom);
      if (dateTo) sp.set("to", dateTo);
    }
    window.history.replaceState(null, "", `?${sp.toString()}`);
  }

  // Changer de mode met l'URL à jour immédiatement (lien partageable même sans
  // avoir encore lancé la recherche).
  function selectMode(m: Mode) {
    setMode(m);
    syncUrl(m, q);
  }

  // Au chargement : si l'URL porte un mode/une requête (lien partagé), on les
  // applique et on relance la recherche automatiquement.
  const autorun = useRef(false);
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const m = sp.get("mode");
    const query = sp.get("q");
    if (m === "pubmed_v1" || m === "pubmed_v2" || m === "semantic" || m === "keyword") {
      setMode(m);
    } else if (m === "pubmed") {
      // rétro-compat des anciens liens : ?mode=pubmed(&variant=v1)
      setMode(sp.get("variant") === "v1" ? "pubmed_v1" : "pubmed_v2");
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
    if (mode === "semantic" && !model) return; // attendre le chargement du modèle
    autorun.current = false;
    runSearch(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, model, q]);

  async function runSearch(newOffset = 0) {
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
        setPubmed(null);
        setDeep(null);
        setLogs([]);
        setOffset(0);
        esRef.current?.close();
        // Méthode v2 : streaming SSE (déroulé en direct) — comme v1, pour ne pas
        // se faire couper par le proxy sur les requêtes longues.
        if (pubmedVariant === "v2") {
          esRef.current = searchPubmedDeepStream(
            q.trim(),
            dateFrom || undefined,
            dateTo || undefined,
            12,
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
                setError(msg || "La recherche v2 a échoué.");
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
                            ? { ...r, abstract_fr: fr[String(r.pmid)].abstract_fr }
                            : r,
                        ),
                      }
                    : prev,
                ),
            },
          );
          return;
        }
        // Méthode v1 : streaming SSE, on affiche le déroulé en direct.
        esRef.current = searchPubmedStream(
          q.trim(),
          12,
          dateFrom || undefined,
          dateTo || undefined,
          {
          onLog: (log) => {
            setLogs((prev) => [...prev, log]);
            if (log.phase === "codex_limit") setCodexLimit(true);
          },
          onResult: (res) => {
            setPubmed(res);
            setLoading(false);
          },
          onError: (msg) => {
            if (msg && /usage limit|limite d'usage|rate limit/i.test(msg))
              setCodexLimit(true);
            setError(msg || "La recherche PubMed a échoué.");
            setLoading(false);
          },
        });
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
      setPubmed(null);
      setDeep(null);
      setOffset(newOffset);
      setLoading(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
      setData(null);
      setPubmed(null);
      setDeep(null);
      setLoading(false);
    }
    // NB : pas de `finally { setLoading(false) }` — les branches PubMed (SSE)
    // sortent en `return` avec `loading` encore vrai ; ce sont leurs handlers
    // onResult/onError qui le repassent à false. Un finally couperait la roue.
  }

  function addMesh(term: string) {
    if (!mesh.includes(term)) setMesh([...mesh, term]);
    setMeshInput("");
    setSuggestions([]);
  }

  const selectedModel = models.find((m) => m.name === model);
  const noEmbeddings = mode === "semantic" && selectedModel && selectedModel.embedded === 0;

  // Meilleure similarité de la page (mode sémantique) : sert à prévenir quand
  // rien n'est vraiment pertinent, sans normaliser les barres.
  const topScore =
    data && data.results.length
      ? Math.max(0, ...data.results.map((r) => r.score ?? 0))
      : 0;
  const weakSemantic =
    mode === "semantic" && data !== null && data.results.length > 0 && topScore < SEM_RELEVANT;

  return (
    <main className="container">
      <h1>X-Med</h1>
      <p className="tagline">Explorez la recherche médicale</p>
      <p className="subtitle">
        Décrivez votre question en français — ou cherchez par mots-clés et tags
        MeSH.
      </p>

      <div className="panel">
        {/* Bascule de mode */}
        <div className="toggle" style={{ marginBottom: 14 }}>
          <button
            type="button"
            className={mode === "pubmed_v2" ? "on" : ""}
            onClick={() => selectMode("pubmed_v2")}
          >
            PubMed + Filtre lexical + Codex
          </button>
          <button
            type="button"
            className={mode === "semantic" ? "on" : ""}
            onClick={() => selectMode("semantic")}
          >
            Par sens (sémantique)
          </button>
          <button
            type="button"
            className={mode === "keyword" ? "on" : ""}
            onClick={() => selectMode("keyword")}
          >
            Mots-clés / MeSH
          </button>
        </div>

        <form
          className="search-row"
          onSubmit={(e) => {
            e.preventDefault();
            runSearch(0);
          }}
        >
          <input
            type="text"
            placeholder={
              mode === "semantic"
                ? "Ex. : crise cardiaque chez le patient diabétique âgé…"
                : isPubmed
                  ? "Question clinique en français — interrogée en direct sur PubMed…"
                  : "Mots-clés (anglais) : myocardial infarction, diabetes…"
            }
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="submit" className="primary" disabled={loading}>
            {loading ? "…" : "Rechercher"}
          </button>
        </form>

        {/* Mode sémantique : sélecteur de modèle */}
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

        {/* Mode PubMed (v1 ou v2) : note de fonctionnement + fenêtre de dates */}
        {isPubmed && (
          <>
            <p className="notice" style={{ marginTop: 4 }}>
              {pubmedVariant === "v1" ? (
                <>
                  <b>v1</b> — l’IA traduit votre question en requête experte, puis
                  GPT-5.4 lit <b>tous les abstracts locaux</b> de la période par lots.
                  Une période large peut nécessiter plusieurs appels et durer plusieurs
                  minutes.
                </>
              ) : (
                <>
                  <b>v2</b> — l’IA construit une requête experte, on <b>pré-filtre</b>{" "}
                  la base en local (mots-clés + MeSH), puis GPT-5.4 <b>lit et juge</b>{" "}
                  uniquement ces candidats. Plus rapide et insensible à la largeur de la
                  période.
                </>
              )}
            </p>
            <div className="filters">
              <div className="field">
                <label>Publié depuis</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                />
              </div>
              <div className="field">
                <label>jusqu’au</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                />
              </div>
              <p className="meta" style={{ alignSelf: "center", margin: 0 }}>
                Par défaut 2025 → aujourd’hui, pour rester comparable à notre base.
              </p>
            </div>
          </>
        )}

        {/* Mode mots-clés : chips MeSH + filtres */}
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
                    <button
                      type="button"
                      className={meshMode === "or" ? "on" : ""}
                      onClick={() => setMeshMode("or")}
                    >
                      OU
                    </button>
                    <button
                      type="button"
                      className={meshMode === "and" ? "on" : ""}
                      onClick={() => setMeshMode("and")}
                    >
                      ET
                    </button>
                  </div>
                </div>
              )}
              <div className="field">
                <label>Année min.</label>
                <input
                  type="number"
                  value={yearFrom}
                  onChange={(e) => setYearFrom(e.target.value)}
                  placeholder="1975"
                />
              </div>
              <div className="field">
                <label>Année max.</label>
                <input
                  type="number"
                  value={yearTo}
                  onChange={(e) => setYearTo(e.target.value)}
                  placeholder="2026"
                />
              </div>
              <div className="field">
                <label>Niveau de preuve max.</label>
                <select
                  value={evidenceMax}
                  onChange={(e) => setEvidenceMax(e.target.value)}
                >
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
      </div>

      {codexLimit && (
        <div className="codex-limit" role="alert">
          🚫 <b>Limite d’usage GPT-5.4 atteinte.</b> Les recherches «&nbsp;PubMed +
          codex&nbsp;» reposent sur GPT-5.4 (construction de la requête, tri et
          traduction) : le quota est épuisé pour le moment. Les résultats sont en{" "}
          <b>mode dégradé</b> (sans tri intelligent ni traduction FR). Réessayez un
          peu plus tard.
        </div>
      )}

      {error && <p className="error">⚠ {error}</p>}

      {loading && (
        <SearchLoader variant={isPubmed ? pubmedVariant : "other"} />
      )}

      {isPubmed && logs.length > 0 && (
        <div className="search-log">
          <div className="search-log-head">
            Déroulé de la recherche{loading ? " — en cours…" : ""}
          </div>
          {logs.map((l, i) => (
            <div key={i} className="search-log-line">
              {l.msg}
            </div>
          ))}
          {(() => {
            const ql = logs.find((l) => l.pubmed_query);
            return ql ? <pre className="search-log-query">{ql.pubmed_query}</pre> : null;
          })()}
        </div>
      )}

      {data && (
        <>
          <div className="meta-row">
            <p className="meta" style={{ margin: 0 }}>
              {data.total.toLocaleString("fr-FR")} résultat(s)
              {mode === "keyword" && data.total > 0 &&
                ` · affichage ${offset + 1}–${Math.min(offset + PAGE, data.total)}`}
            </p>
            <CopyLinkButton />
          </div>

          {weakSemantic && (
            <p className="notice">
              Aucun article vraiment pertinent pour cette requête. Le périmètre
              couvert par la recherche sémantique est encore limité (surtout
              gynéco-obstétrique &amp; ophtalmologie) — les résultats ci-dessous
              sont les plus proches, pas forcément adaptés. Essayez le mode
              «&nbsp;Mots-clés&nbsp;».
            </p>
          )}

          {data.results.map((r: ArticleResult, i: number) => (
            <article className="result" key={r.pmid}>
              <h3>
                <span className="rank">#{offset + i + 1}</span>
                <a href={r.pubmed_url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </h3>
              <div className="journal">
                <Badge level={r.evidence_level} />
                {r.journal || "Journal inconnu"}
                {r.pub_year ? ` · ${r.pub_year}` : ""}
              </div>
              {mode === "semantic" && r.score != null && (
                <MatchBar score={r.score} />
              )}
              {r.abstract_snippet && (
                <p className="abstract">{r.abstract_snippet}</p>
              )}
              <Explanation article={r} />
              {r.mesh_terms && r.mesh_terms.length > 0 && (
                <div className="tags">
                  {r.mesh_terms.slice(0, 8).map((t) => (
                    <span className="tag" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}

          {mode === "keyword" && data.total > PAGE && (
            <div className="pager">
              <button
                disabled={offset === 0 || loading}
                onClick={() => runSearch(Math.max(0, offset - PAGE))}
              >
                ← Précédent
              </button>
              <button
                disabled={offset + PAGE >= data.total || loading}
                onClick={() => runSearch(offset + PAGE)}
              >
                Suivant →
              </button>
            </div>
          )}
        </>
      )}

      {pubmed && (
        <>
          <div className="meta-row">
            <p className="meta" style={{ margin: 0 }}>
              {pubmed.total_hits.toLocaleString("fr-FR")} résultat(s) sur PubMed ·
              {pubmed.local_abstracts.toLocaleString("fr-FR")} abstracts locaux lus ·{" "}
              {pubmed.codex_batches} lot(s) GPT-5.4
            </p>
            <CopyLinkButton />
          </div>
          {pubmed.pubmed_query && (
            <details className="explanation">
              <summary>Requête PubMed générée</summary>
              <p className="abstract" style={{ fontFamily: "monospace", fontSize: 13 }}>
                {pubmed.pubmed_query}
              </p>
            </details>
          )}

          <h2 style={{ marginTop: 18 }}>Classement final A + B</h2>
          <p className="meta">
            {pubmed.relevant_total.toLocaleString("fr-FR")} article(s) jugé(s)
            cohérent(s) avec la PRM. Classement par pertinence Codex, niveau de
            preuve, puis récence.
          </p>
          {pubmed.ranked.length === 0 && (
            <p className="notice">Aucun article jugé pertinent pour cette recherche.</p>
          )}
          {pubmed.ranked.map((r, i) => (
            <article className="result" key={`ranked-${r.pmid}`}>
              <h3>
                <span className="rank">#{i + 1}</span>
                <a href={r.pubmed_url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </h3>
              <div className="journal">
                <Badge level={r.evidence_level} />
                {r.journal || "Journal inconnu"}
                {r.pub_year ? ` · ${r.pub_year}` : ""}
                <span className="tag" style={{ marginLeft: 8 }}>
                  {r.sources.includes("pubmed") ? "A · PubMed" : ""}
                  {r.sources.length === 2 ? " + " : ""}
                  {r.sources.includes("local") ? "B · local" : ""}
                </span>
              </div>
              <CodexScoreBar score={r.score} />
              <p className="explanation-note">{r.justification}</p>
              {r.abstract_snippet && <p className="abstract">{r.abstract_snippet}</p>}
            </article>
          ))}

          <details className="explanation" style={{ marginTop: 24 }}>
            <summary>Voir la liste A brute renvoyée par PubMed</summary>
            {pubmed.results.length === 0 && (
              <p className="notice">Aucun article PubMed pour cette requête.</p>
            )}
            {pubmed.results.map((r, i) => (
                <article className="result" key={`pm-${r.pmid}`}>
                  <h3>
                    <span className="rank">#{i + 1}</span>
                    <a href={r.pubmed_url} target="_blank" rel="noreferrer">
                      {r.title}
                    </a>
                  </h3>
                  <div className="journal">
                    <Badge level={r.evidence_level} />
                    {r.journal || "Journal inconnu"}
                    {r.pub_year ? ` · ${r.pub_year}` : ""}
                    {r.in_db ? " · dans la base locale" : " · hors base locale"}
                  </div>
                  {r.abstract_fr && <p className="abstract">{r.abstract_fr}</p>}
                </article>
            ))}
          </details>
        </>
      )}

      {deep && (
        <>
          <div className="meta-row">
            <p className="meta" style={{ margin: 0 }}>
              {deep.counts.pubmed ?? 0} PubMed · {deep.counts.local ?? 0} locaux ·{" "}
              {deep.counts.merged ?? 0} fusionnés · {deep.counts.judged ?? 0} jugés par
              codex · {deep.counts.kept ?? 0} retenus
            </p>
            <CopyLinkButton />
          </div>
          {!loading && deep.results.length > 0 && (
            <SaveSearchBar
              deep={deep}
              query={q.trim()}
              dateFrom={dateFrom}
              dateTo={dateTo}
            />
          )}
          {deep.codex_tokens && (deep.codex_tokens.total ?? 0) > 0 && (
            <p className="meta" style={{ margin: "2px 0 0" }}>
              🧮 GPT-5.4 : {deep.codex_tokens.total!.toLocaleString("fr-FR")} tokens
              {" — "}requête {(deep.codex_tokens.query ?? 0).toLocaleString("fr-FR")}
              {" · "}jugement {(deep.codex_tokens.judge ?? 0).toLocaleString("fr-FR")}
              {" (hors traduction, voir le déroulé)"}
            </p>
          )}
          {deep.pubmed_query && (
            <details className="explanation">
              <summary>Requête PubMed générée + mots-clés</summary>
              <p className="abstract" style={{ fontFamily: "monospace", fontSize: 13 }}>
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

          <h2 style={{ marginTop: 18 }}>Classement final A + B (v2)</h2>
          <p className="meta">
            Pré-filtre lexical + MeSH, puis jugement codex (grille 0–3). Tri par
            pertinence, niveau de preuve, puis récence.
            {deep.judge === "skipped" &&
              " ⚠ codex indisponible : tri lexical de repli."}
          </p>
          {deep.results.length === 0 && (
            <p className="notice">Aucun article jugé pertinent pour cette recherche.</p>
          )}
          {deep.results.map((r, i) => (
            <article className="result" key={`deep-${r.pmid}`}>
              <h3>
                <span className="rank">#{i + 1}</span>
                <a href={r.pubmed_url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </h3>
              <div className="journal">
                <Badge level={r.evidence_level} />
                {r.journal || "Journal inconnu"}
                {r.pub_year ? ` · ${r.pub_year}` : ""}
                <span className="tag" style={{ marginLeft: 8 }}>
                  {r.source === "both"
                    ? "A · PubMed + B · local"
                    : r.source === "pubmed"
                      ? "A · PubMed"
                      : "B · local"}
                </span>
              </div>
              {r.score != null && <DeepScoreBar score={r.score} />}
              {r.reason && <p className="explanation-note">{r.reason}</p>}
              {r.abstract_fr ? (
                <div className="abstract-fr">
                  <div className="abstract-fr-label">📄 Résumé (traduit en français)</div>
                  <p className="abstract">{r.abstract_fr}</p>
                </div>
              ) : (
                r.abstract && (
                  <details className="explanation">
                    <summary>
                      📄 Résumé (anglais)
                      {loading ? " — traduction en cours…" : ""}
                    </summary>
                    <p className="abstract">{r.abstract}</p>
                  </details>
                )
              )}
            </article>
          ))}
        </>
      )}
    </main>
  );
}
