// Page statique « Comment ça marche » : explication TECHNIQUE de la recherche
// PubMed + IA (v1 / v2), alignée sur docs/communication_recherche.md § 2 et
// ALGO_RECHERCHE.md. Server Component par défaut (aucun état, aucune
// interactivité) → rendu une fois, pas de JS côté client.
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "X-Med — Comment ça marche",
  description:
    "La recherche PubMed + IA expliquée en technique : pipeline, v1 vs v2, tailles de lots, timeouts et contraintes.",
};

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="arch-step">
      <div className="step-head">
        <span className="step-num">{n}</span>
        <h2>{title}</h2>
      </div>
      <div className="step-body">{children}</div>
    </section>
  );
}

export default function ArchitecturePage() {
  return (
    <main className="container">
      <h1>Comment ça marche</h1>
      <p className="subtitle">
        La recherche PubMed + IA (<code>/search/pubmed/deep</code>) expliquée en
        technique : pipeline, différences v1 / v2, tailles de lots, timeouts et
        contraintes.
      </p>

      <p className="meta">
        Vous cherchez plutôt à tester ?{" "}
        <Link href="/">← Retour à la recherche</Link>
      </p>

      <Step n={1} title="Vue d'ensemble : 2 sources, 1 juge">
        <p>
          Pipeline en 3 temps, avec <strong>2 sources interrogées en
          parallèle</strong> :
        </p>
        <ul>
          <li>
            <strong>A — PubMed live</strong> : l&apos;API E-utilities
            (<code>esearch</code>), triée « Best Match », en temps réel ;
          </li>
          <li>
            <strong>B — base locale</strong> : notre miroir Postgres de PubMed
            (<strong>~25 M articles / 63 Go</strong>), interrogé en recherche
            plein-texte (FTS).
          </li>
        </ul>
        <p>
          Les candidats des deux sources sont fusionnés, puis une IA
          (<strong>Codex</strong>) <em>lit réellement</em> le résumé de chacun
          et lui attribue un score de pertinence. Les deux versions v1 / v2 du
          sélecteur « TRI » ne changent <strong>que la sélection des candidats
          à faire juger</strong> ; le{" "}
          <strong>tri final est toujours le score Codex</strong> (jamais le
          classement PubMed ni le score lexical).
        </p>
      </Step>

      <Step n={2} title="Combien d'articles à chaque étape (v1 vs v2)">
        <table className="bench-table">
          <thead>
            <tr>
              <th>Étape</th>
              <th>v1 · score IA (défaut)</th>
              <th>v2 · fusion RRF</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>A — PubMed live</strong> (<code>k_pubmed</code>)
              </td>
              <td>
                <strong>20</strong>
              </td>
              <td>
                <strong>50</strong>
              </td>
            </tr>
            <tr>
              <td>
                <strong>B — base locale</strong> (<code>max_local</code>)
              </td>
              <td>≤ 200</td>
              <td>≤ 200</td>
            </tr>
            <tr>
              <td>
                <strong>Fusion des candidats</strong>
              </td>
              <td>A puis B (PubMed d&apos;abord, local en filet)</td>
              <td>RRF (rang réciproque) des 2 listes → le local n&apos;est pas
                enterré</td>
            </tr>
            <tr>
              <td>
                <strong>Plancher local garanti</strong> (
                <code>local_floor</code>)
              </td>
              <td>0</td>
              <td>réglable (curseur, 0 par défaut)</td>
            </tr>
            <tr>
              <td>
                <strong>Lus / notés par l&apos;IA par lot</strong> (
                <code>judge_batch</code>)
              </td>
              <td>50 (fixe)</td>
              <td>50, réglable 20–100 (curseur)</td>
            </tr>
            <tr>
              <td>
                <strong>Seuil de conservation</strong> (<code>min_score</code>)
              </td>
              <td>≥ 2 / 3</td>
              <td>≥ 2 / 3</td>
            </tr>
            <tr>
              <td>
                <strong>« Analyser 50 de plus »</strong>
              </td>
              <td>+1 lot de 50</td>
              <td>
                +1 lot de <code>judge_batch</code>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="note">
          La <strong>fusion RRF</strong> (Reciprocal Rank Fusion) n&apos;utilise
          que les <em>rangs</em> des deux listes — pas leurs scores, dont les
          échelles ne sont pas comparables : un article bien classé dans
          l&apos;une <em>ou</em> l&apos;autre remonte. Pourquoi c&apos;est
          important : ~<strong>39 %</strong> des articles jugés pertinents
          viennent de la <strong>base locale seule</strong> — sans RRF, PubMed
          monopoliserait le lot des 50 jugés.
        </p>
      </Step>

      <Step n={3} title="Temps & timeouts">
        <table className="bench-table">
          <thead>
            <tr>
              <th>Poste</th>
              <th>Valeur</th>
              <th>Au-delà</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Durée typique d&apos;une recherche</strong>
              </td>
              <td>
                <strong>30–90 s</strong> (souvent ~1 min)
              </td>
              <td>UI : « un peu plus long » &gt; 90 s, « recherche longue »
                &gt; 180 s</td>
            </tr>
            <tr>
              <td>Construction de la requête (Codex)</td>
              <td>timeout 180 s</td>
              <td>repli « requête brute »</td>
            </tr>
            <tr>
              <td>
                <code>esearch</code> PubMed (source A)
              </td>
              <td>dépend de NCBI</td>
              <td>échec → 502 (stoppe tout)</td>
            </tr>
            <tr>
              <td>
                <strong>Requête base locale (source B)</strong>
              </td>
              <td>
                ≤ <strong>120 s</strong> (<code>statement_timeout</code>,
                configurable) + bouton stop
              </td>
              <td>B = ∅, repli PubMed seul</td>
            </tr>
            <tr>
              <td>
                <code>esummary</code>/<code>efetch</code> (résumés manquants)
              </td>
              <td>best-effort</td>
              <td>dégrade (titre/résumé absents), pas de 500</td>
            </tr>
            <tr>
              <td>Jugement (Codex)</td>
              <td>timeout 420 s</td>
              <td>repli sans score (tri lexical brut)</td>
            </tr>
            <tr>
              <td>Keep-alive SSE</td>
              <td>toutes les 10 s</td>
              <td>évite la coupure proxy pendant le silence du jugement</td>
            </tr>
            <tr>
              <td>Base locale (perf)</td>
              <td>~0,4–0,5 s (requête normale)</td>
              <td>25 M lignes ; ~13 s à froid sans le tuning Postgres</td>
            </tr>
          </tbody>
        </table>
        <p className="note">
          L&apos;essentiel du temps d&apos;attente n&apos;est pas la recherche
          elle-même mais la <strong>lecture des résumés par l&apos;IA</strong>.
        </p>
      </Step>

      <Step n={4} title="Contraintes techniques">
        <ul>
          <li>
            <strong>2 appels Codex</strong> par recherche initiale (1 pour
            construire la requête + 1 pour juger les 50) ; chaque « 50 de
            plus » = +1 appel de jugement. La partie « profil » du prompt est
            mise en cache.
          </li>
          <li>
            <strong>Abstract tronqué à 1 200 caractères</strong> avant envoi au
            juge (le lot entier tient dans un seul appel).
          </li>
          <li>
            <strong>Source B = plein-texte seul</strong> (index GIN, tri{" "}
            <code>ts_rank</code>). Le filtre par tags MeSH en SQL a été retiré :
            un descripteur courant (« Heart Failure ») faisait passer la même
            requête de 0,4 s à 206 s. Les termes MeSH ne servent plus
            qu&apos;à construire la requête PubMed.
          </li>
          <li>
            <strong>Garde-fou local 120 s</strong> (configurable) + bouton stop
            côté interface : mesuré jusqu&apos;à ~493 s sur des mots
            ultra-courants, même en plein-texte seul.
          </li>
          <li>
            <strong>Tuning Postgres</strong> indispensable à cette échelle :
            <code> shared_buffers</code> 8 Go, <code>work_mem</code> 64 Mo,{" "}
            <code>effective_cache_size</code> 24 Go, index FTS (5,7 Go)
            préchauffé (<code>pg_prewarm</code>).
          </li>
          <li>
            <strong>Streaming SSE</strong> : le déroulé s&apos;affiche en
            direct (construction de la requête → PubMed → filtre local →
            jugement → résultats → traductions).
          </li>
        </ul>
        <p className="note">
          Mesuré de bout en bout : requête ciblée (SGLT2/HFpEF) → local 0,5 s,
          150 candidats, 15 retenus ; requête large à chaud ~32 s sous le
          garde-fou.
        </p>
      </Step>

      <Step n={5} title="Question ouverte">
        <p>
          Accélérer <em>aussi</em> les sujets très larges sans dépendre du
          garde-fou : deux pistes à l&apos;étude — un <strong>index RUM</strong>{" "}
          (plein-texte classé directement par l&apos;index) ou{" "}
          <strong>pgvector / HNSW</strong> (recherche sémantique par
          embeddings, architecture cible, vecteurs à compléter sur les 25 M de
          documents).
        </p>
      </Step>

      <p className="meta" style={{ marginTop: 24 }}>
        <Link href="/">← Retour à la recherche</Link>
      </p>
    </main>
  );
}
