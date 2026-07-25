"use client";

/* Analyse critique comparative (V1) — composants d'affichage.

   Parcours : le médecin coche 2 à 3 résultats (SelectButton, injecté dans
   `extraActions` de XMedResult), puis lance l'analyse. Le résultat est rendu en
   tableau (axes en lignes, articles en colonnes) + concordance + synthèse.

   Les axes V1 sont volontairement restreints (extractibles depuis l'abstract) en
   attendant la grille fine validée par les médecins. Voir le brouillon
   analyse_critique_criteres.md. */

import type { CompareResult, CompareRow } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/locale";

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
  const { t } = useT();
  return (
    <button
      type="button"
      className={`xmr-act xm-select ${selected ? "on" : ""}`}
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={selected}
      title={
        disabled
          ? t("critique.selectLimit", { max: MAX_COMPARE })
          : selected
            ? t("critique.selectRemove")
            : t("critique.selectAdd")
      }
    >
      <span className={`xm-select-box ${selected ? "on" : ""}`}>{selected ? "✓" : ""}</span>
      {selected ? t("critique.selected") : t("critique.compare")}
    </button>
  );
}

// Les axes V1 et leur libellé (ordre du tableau).
const AXES: { key: keyof CompareRow; labelKey: MessageKey }[] = [
  { key: "study_type", labelKey: "critique.axisStudyType" },
  { key: "population", labelKey: "critique.axisPopulation" },
  { key: "primary_outcome", labelKey: "critique.axisPrimaryOutcome" },
  { key: "effect_size", labelKey: "critique.axisEffectSize" },
  { key: "limits", labelKey: "critique.axisLimits" },
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
  const { t } = useT();
  const byPmid = new Map(result.rows.map((r) => [r.pmid, r]));
  const cols = order.map((p) => byPmid.get(p)).filter((r): r is CompareRow => !!r);
  if (cols.length === 0) return null;

  return (
    <div className="xm-critique-tablewrap">
      <table className="xm-critique-table">
        <thead>
          <tr>
            <th className="xm-ct-axis">{t("critique.axisHeader")}</th>
            {cols.map((c, i) => (
              <th key={c.pmid}>
                <span className="xm-ct-colno">
                  {t("critique.columnNo", { n: i + 1 })}
                </span>
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
                {t(ax.labelKey)}
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
  const { t } = useT();
  return (
    <div className="xm-critique">
      <div className="xm-critique-head">
        <h2 className="xm-critique-title">{t("critique.title")}</h2>
        <p className="xm-critique-sub">{t("critique.subtitle")}</p>
      </div>

      <CritiqueTable result={result} order={order} />

      {result.concordance && (
        <div className="xm-critique-block">
          <h3>{t("critique.concordance")}</h3>
          <p>{result.concordance}</p>
        </div>
      )}
      {result.synthesis && (
        <div className="xm-critique-block accent">
          <h3>{t("critique.synthesis")}</h3>
          <p>{result.synthesis}</p>
        </div>
      )}
    </div>
  );
}
