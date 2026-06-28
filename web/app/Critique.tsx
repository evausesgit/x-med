"use client";

/* Analyse critique comparative (V1) — composants d'affichage.

   Parcours : le médecin coche 2 à 3 résultats (SelectButton, injecté dans
   `extraActions` de XMedResult), puis lance l'analyse. Le résultat est rendu en
   tableau (axes en lignes, articles en colonnes) + concordance + synthèse.

   Les axes V1 sont volontairement restreints (extractibles depuis l'abstract) en
   attendant la grille fine validée par les médecins. Voir le brouillon
   analyse_critique_criteres.md. */

import type { CompareResult, CompareRow } from "@/lib/api";

export const MAX_COMPARE = 3;

// Bouton de sélection d'un résultat pour l'analyse, façon barre d'action (xmr-act).
export function SelectButton({
  selected,
  disabled,
  onToggle,
}: {
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={`xmr-act xm-select ${selected ? "on" : ""}`}
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={selected}
      title={
        disabled
          ? `Limite de ${MAX_COMPARE} articles atteinte`
          : selected
            ? "Retirer de la sélection"
            : "Ajouter à l'analyse critique"
      }
    >
      <span className={`xm-select-box ${selected ? "on" : ""}`}>{selected ? "✓" : ""}</span>
      {selected ? "Sélectionné" : "Comparer"}
    </button>
  );
}

// Les axes V1 et leur libellé (ordre du tableau).
const AXES: { key: keyof CompareRow; label: string }[] = [
  { key: "study_type", label: "Type d'étude / niveau de preuve" },
  { key: "population", label: "Population (n + profil)" },
  { key: "primary_outcome", label: "Critère de jugement principal" },
  { key: "effect_size", label: "Taille d'effet" },
  { key: "limits", label: "Limites" },
];

// Tableau comparatif : colonnes = articles (dans l'ordre de sélection), lignes = axes.
export function CritiqueTable({
  result,
  order,
}: {
  result: CompareResult;
  // PMID dans l'ordre de sélection du médecin (pour stabiliser les colonnes).
  order: number[];
}) {
  const byPmid = new Map(result.rows.map((r) => [r.pmid, r]));
  const cols = order.map((p) => byPmid.get(p)).filter((r): r is CompareRow => !!r);
  if (cols.length === 0) return null;

  return (
    <div className="xm-critique-tablewrap">
      <table className="xm-critique-table">
        <thead>
          <tr>
            <th className="xm-ct-axis">Critère</th>
            {cols.map((c, i) => (
              <th key={c.pmid}>
                <span className="xm-ct-colno">Article {i + 1}</span>
                <a
                  href={`https://pubmed.ncbi.nlm.nih.gov/${c.pmid}/`}
                  target="_blank"
                  rel="noreferrer"
                  className="xm-ct-coltitle"
                >
                  {c.title || `PMID ${c.pmid}`}
                </a>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {AXES.map((ax) => (
            <tr key={ax.key}>
              <th scope="row" className="xm-ct-axis">
                {ax.label}
              </th>
              {cols.map((c) => (
                <td key={c.pmid}>{String(c[ax.key] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Panneau complet : tableau + concordance + synthèse + disclaimer.
export function CritiquePanel({
  result,
  order,
}: {
  result: CompareResult;
  order: number[];
}) {
  return (
    <div className="xm-critique">
      <div className="xm-critique-head">
        <h2 className="xm-critique-title">Analyse critique comparative</h2>
        <p className="xm-critique-sub">
          Lecture critique générée par l&apos;IA à partir des résumés PubMed — un
          appui à la lecture, pas une validation clinique. Les mentions
          «&nbsp;Non précisé dans le résumé&nbsp;» signalent une information absente
          de l&apos;abstract.
        </p>
      </div>

      <CritiqueTable result={result} order={order} />

      {result.concordance && (
        <div className="xm-critique-block">
          <h3>Concordance entre les articles</h3>
          <p>{result.concordance}</p>
        </div>
      )}
      {result.synthesis && (
        <div className="xm-critique-block accent">
          <h3>À retenir en pratique</h3>
          <p>{result.synthesis}</p>
        </div>
      )}
    </div>
  );
}
