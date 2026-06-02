"use client";

// Page d'annotation in-site du gold set : on choisit une requête, on juge chaque
// article candidat 0/1/2 (boutons), enregistré en base (/eval/annotate).
// Voir bench/GUIDE_ANNOTATION.md.
import { useEffect, useState } from "react";
import {
  annotate,
  EvalCandidate,
  EvalPool,
  EvalQueryProgress,
  getEvalPool,
  listEvalQueries,
} from "@/lib/api";

const GRADES = [
  { g: 2, label: "Très pertinent", cls: "g2" },
  { g: 1, label: "Pertinent", cls: "g1" },
  { g: 0, label: "Non pertinent", cls: "g0" },
];

export default function AnnotatePage() {
  const [queries, setQueries] = useState<EvalQueryProgress[]>([]);
  const [pool, setPool] = useState<EvalPool | null>(null);
  const [annotator, setAnnotator] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [selectedQueryId, setSelectedQueryId] = useState<number | null>(null);
  const [loadingQueryId, setLoadingQueryId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAnnotator(localStorage.getItem("xmed_annotator") || "");
    listEvalQueries()
      .then((q) => {
        setQueries(q);
        setLoaded(true);
      })
      .catch(() => {
        setError("Impossible de charger les lignes à annoter.");
        setLoaded(true);
      });
  }, []);

  function saveAnnotator(v: string) {
    setAnnotator(v);
    localStorage.setItem("xmed_annotator", v);
  }

  async function openQuery(qid: number) {
    setSelectedQueryId(qid);
    setLoadingQueryId(qid);
    setError(null);
    setPool(null);
    try {
      setPool(await getEvalPool(qid));
    } catch {
      setError("Impossible d'ouvrir cette ligne d'annotation.");
    } finally {
      setLoadingQueryId(null);
    }
  }

  async function grade(c: EvalCandidate, g: number) {
    if (!pool) return;
    setError(null);
    try {
      await annotate(pool.query_id, c.pmid, g, annotator || undefined);
    } catch {
      setError("La note n'a pas pu être enregistrée.");
      return;
    }
    // maj locale
    setPool({
      ...pool,
      candidates: pool.candidates.map((x) =>
        x.pmid === c.pmid ? { ...x, grade: g } : x,
      ),
    });
    setQueries((qs) =>
      qs.map((q) =>
        q.query_id === pool.query_id
          ? {
              ...q,
              n_annotated:
                c.grade == null ? q.n_annotated + 1 : q.n_annotated,
            }
          : q,
      ),
    );
  }

  return (
    <main className="container">
      <h1>Annotation</h1>
      <p className="tagline">Jugez la pertinence des articles</p>
      <p className="subtitle">
        Pour chaque requête, notez chaque article : <b>2</b> = très pertinent,{" "}
        <b>1</b> = pertinent, <b>0</b> = non pertinent. Sur le fond clinique, à
        partir du titre + résumé. En cas de doute, prenez la note la plus basse.
      </p>

      <div className="panel" style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <label style={{ color: "var(--faint)", fontSize: 13, fontWeight: 650 }}>
          Vos initiales / nom
        </label>
        <input
          type="text"
          placeholder="ex. Dr A."
          value={annotator}
          onChange={(e) => saveAnnotator(e.target.value)}
          style={{ maxWidth: 200 }}
        />
      </div>

      {error && (
        <div className="panel error-panel">
          <p>{error}</p>
        </div>
      )}

      {loaded && queries.length === 0 && (
        <div className="panel">
          <p style={{ margin: 0 }}>
            Le pool est vide. Le générer côté serveur :{" "}
            <code>uv run python -m scripts.build_pool</code> (nécessite les
            embeddings). Voir <code>PLAN_EVAL.md</code>.
          </p>
        </div>
      )}

      {/* Sélecteur de requêtes */}
      {queries.length > 0 && (
        <div className="q-list">
          {queries.map((q) => {
            const done = q.n_annotated >= q.n_candidates && q.n_candidates > 0;
            return (
              <button
                type="button"
                key={q.query_id}
                className={`q-item ${selectedQueryId === q.query_id ? "on" : ""}`}
                onClick={() => openQuery(q.query_id)}
                aria-pressed={selectedQueryId === q.query_id}
              >
                <span className="q-text">{q.query}</span>
                <span className={`q-prog ${done ? "q-done" : ""}`}>
                  {loadingQueryId === q.query_id
                    ? "Chargement..."
                    : `${q.n_annotated}/${q.n_candidates}`}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Candidats de la requête sélectionnée */}
      {pool && (
        <section style={{ marginTop: 8 }}>
          <p className="meta">
            Requête : <b>{pool.query}</b> · {pool.candidates.length} articles à juger
          </p>
          {pool.candidates.map((c) => (
            <article className="result" key={c.pmid}>
              <div className="grade-row">
                {GRADES.map((gr) => (
                  <button
                    type="button"
                    key={gr.g}
                    className={`grade-btn ${gr.cls} ${c.grade === gr.g ? "on" : ""}`}
                    onClick={() => grade(c, gr.g)}
                  >
                    {gr.g} · {gr.label}
                  </button>
                ))}
              </div>
              <h3 style={{ gridTemplateColumns: "1fr" }}>
                <a href={c.pubmed_url} target="_blank" rel="noreferrer">
                  {c.title}
                </a>
              </h3>
              <div className="journal">
                {c.journal || "Journal inconnu"}
                {c.pub_year ? ` · ${c.pub_year}` : ""}
                {c.found_by ? ` · trouvé par : ${c.found_by}` : ""}
              </div>
              {c.abstract && <p className="abstract">{c.abstract}</p>}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
