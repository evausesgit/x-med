"use client";

// Recherches sauvegardées : liste partagée (pour l'instant tout le monde voit
// tout) des résultats de recherche enregistrés. On peut rouvrir une recherche
// pour relire ses articles — le snapshot est servi tel quel, sans relancer codex.
import { useEffect, useState } from "react";
import {
  deleteSavedSearch,
  DeepHit,
  DeepSearchResponse,
  getSavedSearch,
  listSavedSearches,
  SavedSearchSummary,
} from "@/lib/api";

const EVIDENCE_LABEL: Record<number, string> = {
  1: "Preuve élevée",
  2: "Preuve modérée",
  3: "Cas / série",
  4: "Autre",
};

// Badge de niveau de preuve + barre de score codex (0–3) : reprennent l'affichage
// de la page de recherche (web/app/page.tsx) pour une relecture cohérente.
function Badge({ level }: { level: number | null }) {
  if (!level) return null;
  return (
    <span className={`badge ev${level}`}>
      Niv. {level} · {EVIDENCE_LABEL[level]}
    </span>
  );
}

function DeepScoreBar({ score }: { score: number }) {
  const pct = Math.round((score / 3) * 100);
  const tier = score >= 3 ? "high" : score >= 2 ? "mid" : "low";
  const label = score >= 3 ? "Très pertinent" : score >= 2 ? "Pertinent" : "Partiel";
  return (
    <div className="match" title={`Score codex : ${score} / 3 (grille 0–3).`}>
      <span className={`match-label ml-${tier}`}>{label}</span>
      <div className="match-bar">
        <div className="match-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="match-pct">{score}/3</span>
    </div>
  );
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function HitCard({ hit, rank }: { hit: DeepHit; rank: number }) {
  return (
    <article className="result">
      <h3>
        <span className="rank">#{rank}</span>
        <a href={hit.pubmed_url} target="_blank" rel="noreferrer">
          {hit.title}
        </a>
      </h3>
      <div className="journal">
        <Badge level={hit.evidence_level} />
        {hit.journal || "Journal inconnu"}
        {hit.pub_year ? ` · ${hit.pub_year}` : ""}
      </div>
      {hit.score != null && <DeepScoreBar score={hit.score} />}
      {hit.reason && <p className="explanation-note">{hit.reason}</p>}
      {hit.abstract_fr ? (
        <div className="abstract-fr">
          <div className="abstract-fr-label">📄 Résumé (traduit en français)</div>
          <p className="abstract">{hit.abstract_fr}</p>
        </div>
      ) : (
        hit.abstract && (
          <details className="explanation">
            <summary>📄 Résumé (anglais)</summary>
            <p className="abstract">{hit.abstract}</p>
          </details>
        )
      )}
    </article>
  );
}

function ResultDetail({ payload }: { payload: DeepSearchResponse }) {
  return (
    <div className="saved-detail">
      {payload.pubmed_query && (
        <details className="explanation">
          <summary>Requête PubMed générée + mots-clés</summary>
          <p className="abstract" style={{ fontFamily: "monospace", fontSize: 13 }}>
            {payload.pubmed_query}
          </p>
          {payload.keywords_en?.length > 0 && (
            <div className="tags">
              {payload.keywords_en.slice(0, 12).map((t) => (
                <span className="tag" key={t}>
                  {t}
                </span>
              ))}
            </div>
          )}
        </details>
      )}
      {payload.results.length === 0 ? (
        <p className="notice">Aucun article dans cette recherche sauvegardée.</p>
      ) : (
        payload.results.map((h, i) => (
          <HitCard key={`${h.pmid}-${i}`} hit={h} rank={i + 1} />
        ))
      )}
    </div>
  );
}

export default function SavedSearchesPage() {
  const [items, setItems] = useState<SavedSearchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DeepSearchResponse | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);

  function reload() {
    setLoading(true);
    listSavedSearches()
      .then(setItems)
      .finally(() => setLoading(false));
  }
  useEffect(reload, []);

  async function toggle(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    setDetailBusy(true);
    try {
      const d = await getSavedSearch(id);
      setDetail(d.payload);
    } finally {
      setDetailBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Supprimer cette recherche sauvegardée ?")) return;
    await deleteSavedSearch(id);
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
    }
    reload();
  }

  return (
    <main className="container">
      <h1>Recherches sauvegardées</h1>
      <p className="tagline">Vos résultats, à relire et réutiliser</p>
      <p className="subtitle">
        Chaque recherche est enregistrée telle quelle (requête + articles
        retenus). La rouvrir n&apos;appelle pas l&apos;IA à nouveau. Pour
        l&apos;instant, toutes les recherches sont visibles de tous.
      </p>

      {loading ? (
        <p className="meta">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="notice">
          Aucune recherche sauvegardée pour l&apos;instant. Lancez une recherche
          «&nbsp;PubMed + Filtre lexical + Codex&nbsp;» puis cliquez sur
          «&nbsp;💾 Sauvegarder cette recherche&nbsp;».
        </p>
      ) : (
        <>
          <p className="meta">{items.length} recherche(s) sauvegardée(s)</p>
          {items.map((s) => (
            <article className="result" key={s.id}>
              <div className="saved-item">
                <div className="saved-item-main">
                  <h3 style={{ margin: 0 }}>
                    <span>{s.query}</span>
                  </h3>
                  <div className="journal">
                    👤 {s.doctor_name || "Sans profil"} · {s.n_results} article(s)
                    {" · "}
                    {fmtDate(s.created_at)}
                  </div>
                </div>
                <div className="saved-actions">
                  <button type="button" onClick={() => toggle(s.id)}>
                    {openId === s.id ? "Masquer" : "Rouvrir / relire"}
                  </button>
                  <button type="button" onClick={() => remove(s.id)}>
                    Supprimer
                  </button>
                </div>
              </div>
              {openId === s.id &&
                (detailBusy ? (
                  <p className="meta saved-detail">Chargement des résultats…</p>
                ) : (
                  detail && <ResultDetail payload={detail} />
                ))}
            </article>
          ))}
        </>
      )}
    </main>
  );
}
