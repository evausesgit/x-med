/* X-Med — composants de la démo guidée (React + Babel). */
const { useState, useEffect, useRef } = React;

const EVIDENCE_LABEL = {
  1: "Preuve élevée",
  2: "Preuve modérée",
  3: "Cas / série",
  4: "Autre",
};

function Badge({ level }) {
  if (!level) return null;
  return (
    <span className={`badge ev${level}`}>
      Niv. {level} · {EVIDENCE_LABEL[level]}
    </span>
  );
}

// Barre de « match » — pertinence RELATIVE au meilleur résultat de la page.
// (Le score brut RRF plafonne bas et n'est PAS un % de certitude.)
function MatchBar({ score, max, revealed, tourId }) {
  const rel = max > 0 ? score / max : 0;
  const pct = Math.round(rel * 100);
  const tier = rel >= 0.85 ? "high" : rel >= 0.6 ? "mid" : "low";
  const label = rel >= 0.85 ? "Très pertinent" : rel >= 0.6 ? "Pertinent" : "Lié";
  return (
    <div
      className="match"
      data-tour={tourId}
      title={`Score de fusion RRF : ${score.toFixed(4)} — la barre indique la pertinence relative au meilleur résultat de la page (ce n'est pas un % de certitude).`}
    >
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: revealed ? `${pct}%` : "0%" }} />
      </div>
      <span className="match-pct">{pct}%</span>
    </div>
  );
}

function pubmedUrl(r) {
  // Lien réel vers PubMed (recherche par termes) — fonctionne hors-ligne.
  return "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(r.term);
}

function ResultCard({ r, rank, maxScore, revealed, isFirst }) {
  const idProp = isFirst ? { id: "first-result" } : {};
  return (
    <article className="result" {...idProp}>
      <h3>
        <span className="rank">#{rank}</span>
        <a
          className="result-link"
          data-tour={isFirst ? "result-title" : undefined}
          href={pubmedUrl(r)}
          target="_blank"
          rel="noreferrer"
        >
          {r.title}
        </a>
      </h3>
      <div className="journal">
        <span data-tour={isFirst ? "result-badge" : undefined}>
          <Badge level={r.evidence_level} />
        </span>
        {r.journal || "Journal inconnu"}
        {r.pub_year ? ` · ${r.pub_year}` : ""}
      </div>
      {r.score != null && maxScore > 0 && (
        <MatchBar
          score={r.score}
          max={maxScore}
          revealed={revealed}
          tourId={isFirst ? "result-score" : undefined}
        />
      )}
      {r.abstract && <p className="abstract">{r.abstract}</p>}
      {r.mesh_terms && r.mesh_terms.length > 0 && (
        <div className="tags" data-tour={isFirst ? "result-tags" : undefined}>
          {r.mesh_terms.slice(0, 8).map((t) => (
            <span className="tag" key={t}>{t}</span>
          ))}
        </div>
      )}
    </article>
  );
}

// Liste de résultats + animation des barres de match.
function Results({ results, mode, total, offset }) {
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    setRevealed(false);
    const t = setTimeout(() => setRevealed(true), 60);
    return () => clearTimeout(t);
  }, [results]);

  const maxScore = results.length
    ? Math.max(0, ...results.map((r) => r.score ?? 0))
    : 0;

  return (
    <div>
      <p className="meta">
        {total.toLocaleString("fr-FR")} résultat(s)
        {mode === "keyword" && total > 0 &&
          ` · affichage ${offset + 1}–${Math.min(offset + results.length, total)}`}
      </p>
      {results.map((r, i) => (
        <ResultCard
          key={r.pmid}
          r={r}
          rank={offset + i + 1}
          maxScore={maxScore}
          revealed={revealed}
          isFirst={i === 0}
        />
      ))}
      {mode === "keyword" && total > results.length && (
        <div className="pager">
          <button disabled>← Précédent</button>
          <button>Suivant →</button>
        </div>
      )}
    </div>
  );
}

// Flat MeSH list for autocomplete.
const MESH_FLAT = Array.from(
  new Set([].concat(...Object.values(window.XMED.meshSuggest)))
);

function SearchPanel({
  mode, setMode, q, setQ, onSearch, loading,
  mesh, setMesh, yearFrom, setYearFrom, evidenceMax, setEvidenceMax,
}) {
  const [meshInput, setMeshInput] = useState("");
  const suggestions = meshInput.trim()
    ? MESH_FLAT.filter(
        (t) => t.toLowerCase().includes(meshInput.trim().toLowerCase()) && !mesh.includes(t)
      ).slice(0, 6)
    : [];

  function addMesh(term) {
    if (!mesh.includes(term)) setMesh([...mesh, term]);
    setMeshInput("");
  }

  return (
    <div className="panel">
      <div className="toggle" data-tour="modes" style={{ marginBottom: 14 }}>
        <button type="button" className={mode === "semantic" ? "on" : ""} onClick={() => setMode("semantic")}>
          Par sens (sémantique)
        </button>
        <button type="button" className={mode === "keyword" ? "on" : ""} onClick={() => setMode("keyword")}>
          Mots-clés / MeSH
        </button>
      </div>

      <form
        className="search-row"
        data-tour="search-input"
        onSubmit={(e) => { e.preventDefault(); onSearch(); }}
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

      {mode === "semantic" && (
        <div className="filters">
          <div className="field">
            <label>Modèle d'embedding</label>
            <select defaultValue="bge_m3">
              <option value="bge_m3">bge_m3 (3 000 articles)</option>
              <option value="medcpt">medcpt (3 000 articles)</option>
            </select>
          </div>
          <p style={{ alignSelf: "center", color: "var(--faint)", fontSize: 13, margin: 0 }}>
            Modèle multilingue — fait le pont français → anglais.
          </p>
        </div>
      )}

      {mode === "keyword" && (
        <React.Fragment>
          <div className="mesh-box" data-tour="keyword-panel">
            {mesh.length > 0 && (
              <div className="chips">
                {mesh.map((m) => (
                  <span className="chip" key={m}>
                    {m}
                    <button type="button" onClick={() => setMesh(mesh.filter((x) => x !== m))} aria-label={`Retirer ${m}`}>×</button>
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
                if (e.key === "Enter" && suggestions.length) { e.preventDefault(); addMesh(suggestions[0]); }
              }}
              style={{ width: "100%" }}
            />
            {suggestions.length > 0 && (
              <div className="suggestions">
                {suggestions.map((s) => (
                  <div key={s} onClick={() => addMesh(s)}>{s}</div>
                ))}
              </div>
            )}
          </div>

          <div className="filters">
            {mesh.length > 1 && (
              <div className="field">
                <label>Combinaison des tags</label>
                <div className="toggle">
                  <button type="button" className="on">OU</button>
                  <button type="button">ET</button>
                </div>
              </div>
            )}
            <div className="field">
              <label>Année min.</label>
              <input type="number" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} placeholder="2018" />
            </div>
            <div className="field">
              <label>Année max.</label>
              <input type="number" placeholder="2026" defaultValue="" />
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
        </React.Fragment>
      )}
    </div>
  );
}

Object.assign(window, { Badge, MatchBar, ResultCard, Results, SearchPanel, pubmedUrl, EVIDENCE_LABEL });
