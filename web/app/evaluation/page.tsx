"use client";

// Page « Évaluation » : lit le leaderboard du benchmark (/api/bench/leaderboard)
// et l'affiche en tableaux lisibles, un par jeu de données. Voir PLAN_EVAL.md.
import { useEffect, useState } from "react";
import { BenchRow, listLeaderboard } from "@/lib/api";

const METRICS: { key: string; label: string; help: string }[] = [
  { key: "ndcg@10", label: "nDCG@10", help: "Qualité du classement des 10 premiers (tient compte du grade de pertinence)." },
  { key: "recall@100", label: "Recall@100", help: "Parmi les 100 ramenés, fraction des bons articles attrapés (qualité du pré-filtre)." },
  { key: "mrr", label: "MRR", help: "Position du 1er bon résultat (1er = 1.0, 2e = 0.5…)." },
  { key: "precision@10", label: "P@10", help: "Fraction des 10 premiers qui sont pertinents." },
];

// Libellés lisibles pour les méthodes (model_name stocké en base).
function methodLabel(model: string): string {
  if (model === "fulltext") return "Plein-texte";
  if (model.startsWith("hybrid:")) return `Hybride · ${model.slice(7)}`;
  return `${model} (sémantique)`;
}

const DATASET_LABEL: Record<string, string> = {
  gold_fr: "Gold set FR (requêtes françaises — le verdict produit)",
  nfcorpus: "NFCorpus (jeu standard anglais — repère)",
};

function DatasetTable({ rows }: { rows: BenchRow[] }) {
  // meilleure valeur par métrique (pour surligner)
  const best: Record<string, number> = {};
  for (const m of METRICS) {
    best[m.key] = Math.max(...rows.map((r) => r.metrics?.[m.key] ?? 0));
  }
  // ordre des lignes : on classe par nDCG@10 décroissant
  const sorted = [...rows].sort(
    (a, b) => (b.metrics?.["ndcg@10"] ?? 0) - (a.metrics?.["ndcg@10"] ?? 0),
  );

  return (
    <table className="bench-table">
      <thead>
        <tr>
          <th>Méthode</th>
          {METRICS.map((m) => (
            <th key={m.key} title={m.help}>
              {m.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={r.model}>
            <td className="bench-method">{methodLabel(r.model)}</td>
            {METRICS.map((m) => {
              const v = r.metrics?.[m.key] ?? 0;
              const isBest = v > 0 && v === best[m.key];
              return (
                <td key={m.key} className={isBest ? "bench-best" : ""}>
                  <span className="bench-val">{v.toFixed(3)}</span>
                  <span className="bench-bar">
                    <span
                      className="bench-fill"
                      style={{ width: `${Math.round(Math.min(1, v) * 100)}%` }}
                    />
                  </span>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function EvaluationPage() {
  const [rows, setRows] = useState<BenchRow[] | null>(null);

  useEffect(() => {
    listLeaderboard().then(setRows);
  }, []);

  // regrouper par dataset
  const byDataset: Record<string, BenchRow[]> = {};
  for (const r of rows ?? []) {
    (byDataset[r.dataset] ??= []).push(r);
  }
  const datasets = Object.keys(byDataset).sort((a) =>
    a === "gold_fr" ? -1 : 1,
  );

  return (
    <main className="container">
      <h1>Évaluation</h1>
      <p className="tagline">La recherche est-elle pertinente ?</p>
      <p className="subtitle">
        On compare les méthodes (plein-texte, sémantique, hybride) sur un jeu de
        requêtes dont la pertinence a été jugée par des médecins. Plus c&apos;est
        haut, mieux c&apos;est. La meilleure valeur de chaque colonne est
        surlignée.
      </p>

      {rows === null && <p className="meta">Chargement…</p>}

      {rows !== null && datasets.length === 0 && (
        <div className="panel">
          <p style={{ margin: 0 }}>
            Pas encore de résultats. Lancer le benchmark côté serveur :{" "}
            <code>uv run python -m scripts.run_benchmark</code> (voir{" "}
            <code>PLAN_EVAL.md</code>).
          </p>
        </div>
      )}

      {datasets.map((ds) => (
        <section key={ds} style={{ marginBottom: 28 }}>
          <h2 className="bench-ds">{DATASET_LABEL[ds] ?? ds}</h2>
          <DatasetTable rows={byDataset[ds]} />
        </section>
      ))}

      {rows !== null && datasets.length > 0 && (
        <p className="meta" style={{ marginTop: 18 }}>
          Survole un en-tête de colonne pour la définition de la métrique.
        </p>
      )}
    </main>
  );
}
