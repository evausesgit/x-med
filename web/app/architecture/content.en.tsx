// Contenu ANGLAIS de la page « Comment ça marche » — traduction fidèle de
// content.fr.tsx (mêmes chiffres, mêmes noms de paramètres techniques, qui
// restent en anglais des deux côtés). Server Component.
import Link from "next/link";
import Step from "./Step";

export default function ArchitectureEn() {
  return (
    <>
      <h1>How it works</h1>
      <p className="subtitle">
        The PubMed + AI search (<code>/search/pubmed/deep</code>) explained
        technically: pipeline, v1 vs v2 differences, batch sizes, timeouts and
        constraints.
      </p>

      <p className="meta">
        Looking to try it instead? <Link href="/">← Back to search</Link>
      </p>

      <Step n={1} title="Overview: 2 sources, 1 judge">
        <p>
          A three-stage pipeline, with <strong>2 sources queried in
          parallel</strong>:
        </p>
        <ul>
          <li>
            <strong>A — live PubMed</strong>: the E-utilities API
            (<code>esearch</code>), sorted by “Best Match”, in real time;
          </li>
          <li>
            <strong>B — local database</strong>: our Postgres mirror of PubMed
            (<strong>~25 M articles / 63 GB</strong>), queried with full-text
            search (FTS).
          </li>
        </ul>
        <p>
          Candidates from both sources are merged, then an AI
          (<strong>Codex</strong>) <em>actually reads</em> each abstract and
          gives it a relevance score. The v1 / v2 options of the “SORT” selector
          only change <strong>which candidates get judged</strong>; the{" "}
          <strong>final ordering is always the Codex score</strong> (never the
          PubMed ranking nor the lexical score).
        </p>
      </Step>

      <Step n={2} title="How many articles at each stage (v1 vs v2)">
        <table className="bench-table">
          <thead>
            <tr>
              <th>Stage</th>
              <th>v1 · AI score (default)</th>
              <th>v2 · RRF fusion</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>A — live PubMed</strong> (<code>k_pubmed</code>)
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
                <strong>B — local database</strong> (<code>max_local</code>)
              </td>
              <td>≤ 200</td>
              <td>≤ 200</td>
            </tr>
            <tr>
              <td>
                <strong>Candidate merging</strong>
              </td>
              <td>A then B (PubMed first, local as a safety net)</td>
              <td>
                RRF (reciprocal rank) of both lists → local results are not
                buried
              </td>
            </tr>
            <tr>
              <td>
                <strong>Guaranteed local floor</strong> (<code>local_floor</code>)
              </td>
              <td>0</td>
              <td>adjustable (slider, 0 by default)</td>
            </tr>
            <tr>
              <td>
                <strong>Read / scored by the AI per batch</strong> (
                <code>judge_batch</code>)
              </td>
              <td>50 (fixed)</td>
              <td>50, adjustable 20–100 (slider)</td>
            </tr>
            <tr>
              <td>
                <strong>Keep threshold</strong> (<code>min_score</code>)
              </td>
              <td>≥ 2 / 3</td>
              <td>≥ 2 / 3</td>
            </tr>
            <tr>
              <td>
                <strong>“Analyse 50 more”</strong>
              </td>
              <td>+1 batch of 50</td>
              <td>
                +1 batch of <code>judge_batch</code>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="note">
          <strong>RRF fusion</strong> (Reciprocal Rank Fusion) uses only the{" "}
          <em>ranks</em> of the two lists — not their scores, whose scales are
          not comparable: an article ranked highly in <em>either</em> list moves
          up. Why it matters: ~<strong>39 %</strong> of the articles judged
          relevant come from the <strong>local database alone</strong> — without
          RRF, PubMed would monopolise the batch of 50 that gets judged.
        </p>
      </Step>

      <Step n={3} title="Timing & timeouts">
        <table className="bench-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Value</th>
              <th>Beyond that</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Typical duration of a search</strong>
              </td>
              <td>
                <strong>30–90 s</strong> (often ~1 min)
              </td>
              <td>
                UI: “a little longer” &gt; 90 s, “long search” &gt; 180 s
              </td>
            </tr>
            <tr>
              <td>Query building (Codex)</td>
              <td>180 s timeout</td>
              <td>falls back to the “raw query”</td>
            </tr>
            <tr>
              <td>
                PubMed <code>esearch</code> (source A)
              </td>
              <td>depends on NCBI</td>
              <td>failure → 502 (stops everything)</td>
            </tr>
            <tr>
              <td>
                <strong>Local database query (source B)</strong>
              </td>
              <td>
                ≤ <strong>120 s</strong> (<code>statement_timeout</code>,
                configurable) + stop button
              </td>
              <td>B = ∅, falls back to PubMed only</td>
            </tr>
            <tr>
              <td>
                <code>esummary</code>/<code>efetch</code> (missing abstracts)
              </td>
              <td>best-effort</td>
              <td>degrades (no title/abstract), never a 500</td>
            </tr>
            <tr>
              <td>Judging (Codex)</td>
              <td>420 s timeout</td>
              <td>falls back to no score (raw lexical ordering)</td>
            </tr>
            <tr>
              <td>SSE keep-alive</td>
              <td>every 10 s</td>
              <td>
                prevents the proxy from cutting the connection while judging is
                silent
              </td>
            </tr>
            <tr>
              <td>Local database (performance)</td>
              <td>~0.4–0.5 s (normal query)</td>
              <td>25 M rows; ~13 s cold without the Postgres tuning</td>
            </tr>
          </tbody>
        </table>
        <p className="note">
          Most of the waiting is not the search itself but{" "}
          <strong>the AI reading the abstracts</strong>.
        </p>
      </Step>

      <Step n={4} title="Technical constraints">
        <ul>
          <li>
            <strong>2 Codex calls</strong> per initial search (1 to build the
            query + 1 to judge the 50); each “50 more” adds 1 judging call. The
            “profile” part of the prompt is cached.
          </li>
          <li>
            <strong>Abstract truncated to 1,200 characters</strong> before being
            sent to the judge (so the whole batch fits in a single call).
          </li>
          <li>
            <strong>Source B = full-text only</strong> (GIN index,{" "}
            <code>ts_rank</code> ordering). SQL filtering by MeSH tags was
            removed: a common descriptor (“Heart Failure”) took the same query
            from 0.4 s to 206 s. MeSH terms are now only used to build the
            PubMed query.
          </li>
          <li>
            <strong>120 s local guard</strong> (configurable) + stop button in
            the interface: measured up to ~493 s on very common words, even with
            full-text only.
          </li>
          <li>
            <strong>Postgres tuning</strong> is essential at this scale:
            <code> shared_buffers</code> 8 GB, <code>work_mem</code> 64 MB,{" "}
            <code>effective_cache_size</code> 24 GB, FTS index (5.7 GB)
            pre-warmed (<code>pg_prewarm</code>).
          </li>
          <li>
            <strong>SSE streaming</strong>: progress is shown live (query
            building → PubMed → local filter → judging → results →
            translations).
          </li>
        </ul>
        <p className="note">
          Measured end to end: a targeted query (SGLT2/HFpEF) → local 0.5 s, 150
          candidates, 15 kept; a broad query, warm, ~32 s under the guard.
        </p>
      </Step>

      <Step n={5} title="Open question">
        <p>
          Speeding up very broad topics <em>as well</em>, without relying on the
          guard: two directions under study — a <strong>RUM index</strong>{" "}
          (full-text ranked directly by the index) or{" "}
          <strong>pgvector / HNSW</strong> (semantic search via embeddings, the
          target architecture, with vectors still to be completed across the 25 M
          documents).
        </p>
      </Step>

      <p className="meta" style={{ marginTop: 24 }}>
        <Link href="/">← Back to search</Link>
      </p>
    </>
  );
}
