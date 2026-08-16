"use client";

import type { DeepSearchResponse } from "@/lib/api";

/** Le repli « ce qui a réellement été cherché », commun à la recherche live et
 *  aux recherches sauvegardées (les deux affichaient le même bloc, dupliqué).
 *
 *  Il montre les DEUX sources côte à côte, parce qu'elles ne cherchent pas la
 *  même chose et que l'écart n'est devinable nulle part ailleurs :
 *  - PubMed reçoit la requête complète, descripteurs MeSH compris ;
 *  - le vivier local reçoit les mêmes concepts SANS les MeSH (un descripteur
 *    courant comme « Heart Failure » matcherait des millions de lignes), et
 *    l'échelle de relâchement a pu en retirer un en cours de route.
 *
 *  Sans ce bloc, un vivier local vide ou bizarre n'était pas diagnosticable
 *  après coup : on ne voyait que la requête PubMed, qui disait autre chose.
 */

type LocalState = NonNullable<DeepSearchResponse["local_state"]>;

/** Verdict lisible du pré-filtre local. `tone` colore le badge : l'échelle de
 *  relâchement et l'abandon ne sont pas des marches normales, ils expliquent un
 *  vivier maigre — c'est justement ce qu'on veut voir sans lire les logs. */
const LOCAL_STATE: Record<LocalState, { label: string; tone: string; hint: string }> = {
  ok: {
    label: "concepts combinés en ET",
    tone: "ok",
    hint: "Tous les concepts ont été exigés simultanément.",
  },
  relaxed: {
    label: "un concept relâché",
    tone: "warn",
    hint:
      "Le ET strict rendait trop peu d'articles : on a rejoué la recherche en " +
      "retirant un concept à la fois, puis fusionné les listes.",
  },
  timeout: {
    label: "délai dépassé",
    tone: "bad",
    hint:
      "Le garde-fou de latence a coupé la requête locale — les résultats " +
      "viennent des seuls articles PubMed.",
  },
  stopped: {
    label: "interrompue",
    tone: "muted",
    hint: "Recherche locale annulée (bouton « Arrêter »).",
  },
  skipped: {
    label: "non interrogée",
    tone: "muted",
    hint:
      "Aucun mot-clé anglais disponible : interroger un index anglais avec la " +
      "question française n'aurait rien donné, on s'est appuyé sur PubMed.",
  },
};

export default function SearchQueryDetails({
  pubmedQuery,
  keywordsEn,
  conceptsEn,
  localState,
  localCount,
}: {
  pubmedQuery: string | null;
  keywordsEn?: string[];
  conceptsEn?: string[][];
  localState?: LocalState;
  localCount?: number;
}) {
  const groups = conceptsEn ?? [];
  // Recherches sauvegardées d'avant ces champs, et digest (dont le payload est
  // assaini des termes cliniques) : on n'affiche alors que la partie PubMed.
  const hasLocal = groups.length > 0 || localState !== undefined;
  if (!pubmedQuery && !hasLocal) return null;
  const state = localState ? LOCAL_STATE[localState] : null;
  // Les recherches sauvegardées d'avant ces champs n'ont que la partie PubMed :
  // le titre ne doit pas annoncer une section absente.
  const summary =
    pubmedQuery && hasLocal
      ? "Ce qui a été cherché — PubMed et base locale"
      : pubmedQuery
        ? "Requête PubMed générée + mots-clés"
        : "Ce qui a été cherché dans la base locale";

  return (
    <details className="explanation">
      <summary>{summary}</summary>

      {pubmedQuery && (
        <section className="sqd-block">
          <h4 className="sqd-title">Requête envoyée à PubMed</h4>
          <p className="sqd-query">{pubmedQuery}</p>
          {keywordsEn && keywordsEn.length > 0 && (
            <div className="tags">
              {keywordsEn.slice(0, 12).map((t) => (
                <span className="tag" key={t}>
                  {t}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      {hasLocal && (
        <section className="sqd-block">
          <h4 className="sqd-title">
            Base locale PubMed
            {state && <span className={`sqd-state ${state.tone}`}>{state.label}</span>}
            {typeof localCount === "number" && (
              <span className="sqd-count">
                {localCount} candidat{localCount > 1 ? "s" : ""}
              </span>
            )}
          </h4>
          {state && <p className="explanation-note sqd-hint">{state.hint}</p>}

          {groups.length > 0 && (
            <>
              <div className="sqd-groups">
                {groups.map((group, i) => (
                  <div className="sqd-group" key={i}>
                    {i > 0 && <span className="sqd-op">ET</span>}
                    <div className="tags sqd-syn">
                      {group.map((t) => (
                        <span className="tag" key={t}>
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p className="explanation-note">
                Un article doit satisfaire <strong>tous</strong> les concepts, chacun
                par <strong>n&apos;importe lequel</strong>{" "}de ses synonymes. Les
                descripteurs MeSH visibles dans la requête PubMed sont volontairement
                absents ici : trop courants, ils feraient s&apos;effondrer la
                recherche plein-texte sur 25 millions d&apos;articles.
              </p>
            </>
          )}
        </section>
      )}
    </details>
  );
}
