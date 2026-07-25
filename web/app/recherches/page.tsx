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
import { useT } from "@/lib/i18n";

export default function SavedSearchesPage() {
  const { t, tp, tag } = useT();
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
    if (!confirm(t("saved.confirmDelete"))) return;
    await deleteSavedSearch(id);
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
    }
    reload();
  }

  return (
    <main className="container">
      <h1>{t("saved.title")}</h1>
      <p className="tagline">{t("saved.tagline")}</p>
      <p className="subtitle">{t("saved.subtitle")}</p>

      {loading ? (
        <p className="meta">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="notice">{t("saved.empty")}</p>
      ) : (
        <>
          <p className="meta">{tp("saved.count", items.length)}</p>
          {items.map((s) => (
            <article className="result" key={s.id}>
              <div className="saved-item">
                <div className="saved-item-main">
                  <h3 style={{ margin: 0 }}>
                    <Link href={`/recherches/${s.id}`}>{s.query}</Link>
                  </h3>
                  <div className="journal">
                    👤 {s.doctor_name || t("saved.noProfile")} ·{" "}
                    {tp("saved.articles", s.n_results)}
                    {" · "}
                    {fmtDate(s.created_at, tag)}
                  </div>
                </div>
                <div className="saved-actions">
                  <button type="button" onClick={() => toggle(s.id)}>
                    {openId === s.id ? t("saved.hide") : t("saved.reopen")}
                  </button>
                  <ShareButton id={s.id} />
                  <button type="button" onClick={() => remove(s.id)}>
                    {t("saved.delete")}
                  </button>
                </div>
              </div>
              {openId === s.id &&
                (detailBusy ? (
                  <p className="meta saved-detail">{t("saved.loadingResults")}</p>
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
