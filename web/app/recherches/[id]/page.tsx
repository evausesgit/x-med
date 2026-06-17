"use client";

// Page d'une recherche sauvegardée, accessible par lien direct
// (/recherches/{id}) — c'est CE lien qu'on partage. Le snapshot est servi tel
// quel (pas de nouvel appel codex) et l'endpoint n'a pas de contrôle d'accès,
// donc n'importe qui avec le lien voit les résultats.
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { getSavedSearch, SavedSearchDetail } from "@/lib/api";
import { fmtDate, ResultDetail, ShareButton } from "../shared";

export default function SharedSearchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [search, setSearch] = useState<SavedSearchDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "notfound">("loading");

  useEffect(() => {
    let alive = true;
    getSavedSearch(id)
      .then((d) => {
        if (alive) {
          setSearch(d);
          setStatus("ok");
        }
      })
      .catch(() => {
        if (alive) setStatus("notfound");
      });
    return () => {
      alive = false;
    };
  }, [id]);

  return (
    <main className="container">
      <p className="meta">
        <Link href="/recherches">← Toutes les recherches sauvegardées</Link>
      </p>

      {status === "loading" && <p className="meta">Chargement…</p>}

      {status === "notfound" && (
        <p className="notice">
          Cette recherche sauvegardée est introuvable. Le lien est peut-être
          erroné ou la recherche a été supprimée.
        </p>
      )}

      {status === "ok" && search && (
        <>
          <h1>{search.query}</h1>
          <div className="journal">
            👤 {search.doctor_name || "Sans profil"} · {search.n_results}{" "}
            article(s) · {fmtDate(search.created_at)}
          </div>
          <div className="saved-actions" style={{ margin: "12px 0" }}>
            <ShareButton id={search.id} />
          </div>
          <ResultDetail payload={search.payload} />
        </>
      )}
    </main>
  );
}
