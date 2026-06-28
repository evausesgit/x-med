"use client";

// Composants d'affichage partagés entre la liste des recherches sauvegardées
// (page.tsx) et la page d'une recherche partageable (`[id]/page.tsx`). Repris de
// la page de recherche (web/app/page.tsx) pour une relecture cohérente.
import { useState } from "react";
import { DeepHit, DeepSearchResponse } from "@/lib/api";
import {
  type DisplayedHit,
  type DisplayLang,
  LanguageToggle,
  useDisplayLang,
  useTranslatedHits,
} from "../lang";
import XMedResult, { CritiqueButton, deepRelevance } from "../XMedResult";

export function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function HitCard({
  hit,
  rank,
  display,
  lang,
  onLang,
  busy,
}: {
  hit: DeepHit;
  rank: number;
  display: DisplayedHit;
  lang: DisplayLang;
  onLang: (l: DisplayLang) => void;
  busy: boolean;
}) {
  return (
    <XMedResult
      rank={rank}
      title={display.title}
      journal={hit.journal}
      year={hit.pub_year}
      level={hit.evidence_level}
      relevance={
        hit.score != null ? deepRelevance(hit.score, hit.relevance_pct) : undefined
      }
      contribution={hit.reason}
      why={hit.reason ? [hit.reason] : undefined}
      extraActions={<CritiqueButton />}
      sourceTag={
        hit.source === "both"
          ? "A · PubMed + B · local"
          : hit.source === "pubmed"
            ? "A · PubMed"
            : "B · local"
      }
      pubmedUrl={hit.pubmed_url}
      sourceTitle={hit.title}
      revealHead={<LanguageToggle lang={lang} onChange={onLang} busy={busy} />}
      spoken={display.abstract ?? hit.reason ?? undefined}
    >
      {display.abstract ? (
        <div>
          {display.translated && (
            <div className="abstract-fr-label" style={{ marginBottom: 8 }}>
              📄 Résumé (traduit en français)
            </div>
          )}
          {display.abstract}
        </div>
      ) : undefined}
    </XMedResult>
  );
}

export function ResultDetail({ payload }: { payload: DeepSearchResponse }) {
  const [lang, setLang] = useDisplayLang();
  const { resolve, busy } = useTranslatedHits(payload.results, lang);
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
        <>
          {payload.results.map((h, i) => (
            <HitCard
              key={`${h.pmid}-${i}`}
              hit={h}
              rank={i + 1}
              display={resolve(h)}
              lang={lang}
              onLang={setLang}
              busy={busy}
            />
          ))}
        </>
      )}
    </div>
  );
}

// Bouton « Partager » : copie le lien public d'une recherche sauvegardée
// (/recherches/{id}) dans le presse-papiers. Le lien est partageable tel quel —
// l'endpoint GET /saved-searches/{id} n'a pas de contrôle d'accès.
export function ShareButton({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = `${window.location.origin}/recherches/${id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Presse-papiers indisponible (http non sécurisé, vieux navigateur) :
      // on montre le lien à copier à la main.
      window.prompt("Copiez ce lien pour le partager :", url);
    }
  }
  return (
    <button type="button" onClick={share}>
      {copied ? "✅ Lien copié" : "🔗 Partager"}
    </button>
  );
}
