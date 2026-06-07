"use client";

// Page « Vectorisation » : visualise l'avancement de l'embedding du corpus
// (combien d'articles restent à vectoriser), sous trois angles — couverture
// globale, périmètre prévu (articles avec abstract) et détail par année.
// Données : /api/embeddings/progress. Auto-rafraîchie pour suivre le job en cours.
import { useEffect, useState } from "react";
import {
  EmbeddingProgress,
  EmbeddingCoverage,
  getEmbeddingProgress,
} from "@/lib/api";

const REFRESH_MS = 15000;
const fmt = (n: number) => n.toLocaleString("fr-FR");
const pct = (c: EmbeddingCoverage) =>
  c.total > 0 ? (c.embedded / c.total) * 100 : 0;

function Bar({
  label,
  coverage,
  hint,
}: {
  label: string;
  coverage: EmbeddingCoverage;
  hint?: string;
}) {
  const p = pct(coverage);
  const remaining = Math.max(0, coverage.total - coverage.embedded);
  const done = remaining === 0 && coverage.total > 0;
  return (
    <div className="emb-row">
      <div className="emb-head">
        <span className="emb-label">{label}</span>
        <span className="emb-pct">{p.toFixed(1)} %</span>
      </div>
      <span className="emb-bar">
        <span
          className={`emb-fill${done ? " done" : ""}`}
          style={{ width: `${Math.min(100, p)}%` }}
        />
      </span>
      <div className="emb-counts">
        {fmt(coverage.embedded)} / {fmt(coverage.total)} vectorisés ·{" "}
        <strong>{fmt(remaining)}</strong> restants
        {hint ? <> — {hint}</> : null}
      </div>
    </div>
  );
}

export default function EmbeddingsPage() {
  const [data, setData] = useState<EmbeddingProgress | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const d = await getEmbeddingProgress("bge_m3");
      if (!alive) return;
      setData(d);
      setLoaded(true);
      if (d) setUpdatedAt(new Date());
    };
    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="container">
      <h1>Vectorisation</h1>
      <p className="tagline">Où en est l&apos;embedding du corpus ?</p>
      <p className="subtitle">
        Chaque article est transformé en vecteur (modèle <code>bge-m3</code>) pour
        la recherche par le sens. Voici combien d&apos;articles sont déjà
        vectorisés — et combien il en reste. La page se met à jour toute seule.
      </p>

      {!loaded && <p className="meta">Chargement…</p>}

      {loaded && data === null && (
        <div className="panel">
          <p style={{ margin: 0 }}>
            Impossible de récupérer l&apos;avancement (API indisponible ?).
          </p>
        </div>
      )}

      {data && (
        <>
          <section className="panel">
            <h2 className="bench-ds">Vue d&apos;ensemble</h2>
            <Bar
              label="Périmètre prévu (articles avec abstract)"
              coverage={data.planned}
              hint="seuls les articles ayant un résumé sont vectorisés (un titre seul est peu fiable)"
            />
            <Bar
              label="Corpus complet (tous les articles)"
              coverage={data.global}
              hint="inclut les articles sans abstract, qu'on ne vectorise pas pour l'instant"
            />
          </section>

          <section className="panel">
            <h2 className="bench-ds">Par année</h2>
            <p className="meta" style={{ marginTop: 0, marginBottom: 14 }}>
              Sur la base du périmètre prévu (articles avec abstract), pour les
              années d&apos;au moins 1 000 articles. Le job en cours traite les
              années les plus récentes en premier.
            </p>
            {data.by_year
              .filter((y) => y.total >= 1000)
              .map((y) => {
              const p = y.total > 0 ? (y.embedded / y.total) * 100 : 0;
              const done = y.embedded >= y.total && y.total > 0;
              return (
                <div className="emb-year" key={y.year}>
                  <span className="emb-year-label">{y.year}</span>
                  <span className="emb-bar">
                    <span
                      className={`emb-fill${done ? " done" : ""}`}
                      style={{ width: `${Math.min(100, p)}%` }}
                    />
                  </span>
                  <span className="emb-year-counts">
                    {fmt(y.embedded)} / {fmt(y.total)} · {p.toFixed(0)} %
                  </span>
                </div>
              );
            })}
          </section>

          {updatedAt && (
            <p className="meta">
              Mis à jour à {updatedAt.toLocaleTimeString("fr-FR")} · rafraîchi
              toutes les {REFRESH_MS / 1000} s.
            </p>
          )}
        </>
      )}
    </main>
  );
}
