"use client";

// Recherches sauvegardées : liste partagée (pour l'instant tout le monde voit
// tout) des résultats de recherche enregistrés. On peut rouvrir une recherche
// pour relire ses articles — le snapshot est servi tel quel, sans relancer codex.
// Chaque recherche a aussi un lien direct partageable (/recherches/{id}).
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  deleteSavedSearch,
  DeepSearchResponse,
  getSavedSearch,
  listSavedSearches,
  SavedSearchSummary,
} from "@/lib/api";
import { fmtDate, ResultDetail, ShareButton } from "./shared";

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
        l&apos;instant, toutes les recherches sont visibles de tous — le bouton
        «&nbsp;🔗 Partager&nbsp;» copie un lien direct vers les résultats.
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
                    <Link href={`/recherches/${s.id}`}>{s.query}</Link>
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
                  <ShareButton id={s.id} />
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
