"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArticleResult,
  EmbeddingModelInfo,
  listModels,
  meshAutocomplete,
  PubmedSearchResponse,
  searchMesh,
  searchPubmed,
  searchSemantic,
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

type Mode = "keyword" | "semantic" | "pubmed";

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
  const [pubmed, setPubmed] = useState<PubmedSearchResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function runSearch(newOffset = 0) {
    setLoading(true);
    setError(null);
    try {
      if (mode === "pubmed") {
        if (!q.trim()) {
          setLoading(false);
          return;
        }
        const res = await searchPubmed(q.trim(), 12, model || undefined);
        setPubmed(res);
        setData(null);
        setOffset(0);
        setLoading(false);
        return;
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
      setOffset(newOffset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
      setData(null);
      setPubmed(null);
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
          <button
            type="button"
            className={mode === "pubmed" ? "on" : ""}
            onClick={() => setMode("pubmed")}
          >
            PubMed + base
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
                : mode === "pubmed"
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

        {/* Mode PubMed : note de fonctionnement */}
        {mode === "pubmed" && (
          <p className="notice" style={{ marginTop: 10 }}>
            Ce mode interroge PubMed <b>en direct</b> : l’IA traduit votre question
            en requête PubMed experte, récupère les articles récents, puis cherche
            des compléments dans notre base. Comptez ~1&nbsp;minute par recherche.
          </p>
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
          <p className="meta">
            {pubmed.total_hits.toLocaleString("fr-FR")} résultat(s) sur PubMed ·
            requête construite par{" "}
            {pubmed.query_builder === "codex" ? "l’IA (codex)" : "repli (texte brut)"}
          </p>
          {pubmed.pubmed_query && (
            <details className="explanation">
              <summary>Requête PubMed générée</summary>
              <p className="abstract" style={{ fontFamily: "monospace", fontSize: 13 }}>
                {pubmed.pubmed_query}
              </p>
            </details>
          )}

          <h2 style={{ marginTop: 18 }}>Articles récents sur PubMed</h2>
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
                {r.in_db ? (
                  <span className="tag" style={{ marginLeft: 8 }}>déjà dans notre base</span>
                ) : (
                  <span className="tag" style={{ marginLeft: 8, opacity: 0.7 }}>
                    nouveau (hors base)
                  </span>
                )}
              </div>
              {r.abstract_fr && <p className="abstract">{r.abstract_fr}</p>}
            </article>
          ))}

          {pubmed.related.length > 0 && (
            <>
              <h2 style={{ marginTop: 24 }}>Plus dans notre base (voisins sémantiques)</h2>
              {pubmed.related.map((r: ArticleResult, i: number) => (
                <article className="result" key={`rel-${r.pmid}`}>
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
                  </div>
                  {r.abstract_snippet && <p className="abstract">{r.abstract_snippet}</p>}
                </article>
              ))}
            </>
          )}
        </>
      )}
    </main>
  );
}
