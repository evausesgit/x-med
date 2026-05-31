"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArticleResult,
  EmbeddingModelInfo,
  listModels,
  meshAutocomplete,
  searchHybrid,
  searchMesh,
  SearchResponse,
} from "@/lib/api";

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

// Barre de « match » pour la recherche par sens.
// Le score brut renvoyé par l'API hybride est un score de fusion RRF
// (Reciprocal Rank Fusion) : il plafonne vers ~0,03 et ne se lit PAS comme un
// pourcentage de certitude. On affiche donc une pertinence *relative*,
// normalisée au meilleur résultat de la page, + un libellé qualitatif.
function MatchBar({ score, max }: { score: number; max: number }) {
  const rel = max > 0 ? score / max : 0;
  const pct = Math.round(rel * 100);
  const tier = rel >= 0.85 ? "high" : rel >= 0.6 ? "mid" : "low";
  const label = rel >= 0.85 ? "Très pertinent" : rel >= 0.6 ? "Pertinent" : "Lié";
  return (
    <div
      className="match"
      title={`Score de fusion RRF : ${score.toFixed(4)} — la barre indique la pertinence relative au meilleur résultat de la page (ce n'est pas un % de certitude).`}
    >
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="match-pct">{pct}%</span>
    </div>
  );
}

type Mode = "keyword" | "semantic";

export default function Home() {
  const [mode, setMode] = useState<Mode>("semantic");
  const [q, setQ] = useState("");
  const [mesh, setMesh] = useState<string[]>([]);
  const [meshMode, setMeshMode] = useState<"and" | "or">("or");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [evidenceMax, setEvidenceMax] = useState("");

  const [meshInput, setMeshInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [models, setModels] = useState<EmbeddingModelInfo[]>([]);
  const [model, setModel] = useState("");

  const [data, setData] = useState<SearchResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // modèles d'embedding disponibles (pour le mode sémantique)
  useEffect(() => {
    listModels().then((ms) => {
      setModels(ms);
      const ready = ms.find((m) => m.embedded > 0) || ms[0];
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

  async function runSearch(newOffset = 0) {
    setLoading(true);
    setError(null);
    try {
      let res: SearchResponse;
      if (mode === "semantic") {
        if (!q.trim()) {
          setLoading(false);
          return;
        }
        res = await searchHybrid(q.trim(), model, PAGE);
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
      setOffset(newOffset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
      setData(null);
    } finally {
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

  // Meilleur score de la page : sert à normaliser les barres de « match ».
  const maxScore =
    data && data.results.length
      ? Math.max(0, ...data.results.map((r) => r.score ?? 0))
      : 0;

  return (
    <main className="container">
      <h1>X-Med — Recherche d&apos;articles scientifiques médicaux</h1>
      <p className="subtitle">
        Cherchez par phrase en langage naturel (recherche sémantique), ou par
        mots-clés / tags MeSH.
      </p>

      <div className="panel">
        {/* Bascule de mode */}
        <div className="toggle" style={{ marginBottom: 14 }}>
          <button
            type="button"
            className={mode === "semantic" ? "on" : ""}
            onClick={() => setMode("semantic")}
          >
            Par sens (sémantique)
          </button>
          <button
            type="button"
            className={mode === "keyword" ? "on" : ""}
            onClick={() => setMode("keyword")}
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

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <>
          <p className="meta">
            {data.total.toLocaleString("fr-FR")} résultat(s)
            {mode === "keyword" && data.total > 0 &&
              ` · affichage ${offset + 1}–${Math.min(offset + PAGE, data.total)}`}
          </p>

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
              {r.score != null && maxScore > 0 && (
                <MatchBar score={r.score} max={maxScore} />
              )}
              {r.abstract_snippet && (
                <p className="abstract">{r.abstract_snippet}</p>
              )}
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
    </main>
  );
}
