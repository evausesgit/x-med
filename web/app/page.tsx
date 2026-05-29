"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArticleResult,
  meshAutocomplete,
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

export default function Home() {
  const [q, setQ] = useState("");
  const [mesh, setMesh] = useState<string[]>([]);
  const [mode, setMode] = useState<"and" | "or">("or");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [evidenceMax, setEvidenceMax] = useState("");

  const [meshInput, setMeshInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [data, setData] = useState<SearchResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // autocomplétion MeSH (debounce léger)
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
      const res = await searchMesh({
        q: q.trim() || undefined,
        mesh,
        mode,
        yearFrom: yearFrom ? Number(yearFrom) : undefined,
        yearTo: yearTo ? Number(yearTo) : undefined,
        evidenceMax: evidenceMax ? Number(evidenceMax) : undefined,
        limit: PAGE,
        offset: newOffset,
      });
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

  return (
    <main className="container">
      <h1>X-Med — Recherche PubMed</h1>
      <p className="subtitle">
        Cherchez par phrase libre (langage naturel) et/ou par tags MeSH.
      </p>

      <div className="panel">
        <form
          className="search-row"
          onSubmit={(e) => {
            e.preventDefault();
            runSearch(0);
          }}
        >
          <input
            type="text"
            placeholder="Ex. : anticoagulation chez le sujet âgé avec fibrillation atriale…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="submit" className="primary" disabled={loading}>
            {loading ? "…" : "Rechercher"}
          </button>
        </form>

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
                  className={mode === "or" ? "on" : ""}
                  onClick={() => setMode("or")}
                >
                  OU (au moins un)
                </button>
                <button
                  type="button"
                  className={mode === "and" ? "on" : ""}
                  onClick={() => setMode("and")}
                >
                  ET (tous)
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
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <>
          <p className="meta">
            {data.total.toLocaleString("fr-FR")} résultat(s)
            {data.total > 0 &&
              ` · affichage ${offset + 1}–${Math.min(offset + PAGE, data.total)}`}
          </p>

          {data.results.map((r: ArticleResult) => (
            <article className="result" key={r.pmid}>
              <h3>
                <a href={r.pubmed_url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </h3>
              <div className="journal">
                <Badge level={r.evidence_level} />
                {r.journal || "Journal inconnu"}
                {r.pub_year ? ` · ${r.pub_year}` : ""}
                {r.score != null ? ` · score ${r.score.toFixed(3)}` : ""}
              </div>
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

          {data.total > PAGE && (
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
