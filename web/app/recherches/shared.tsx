"use client";

// Composants d'affichage partagés entre la liste des recherches sauvegardées
// (page.tsx) et la page d'une recherche partageable (`[id]/page.tsx`). Repris de
// la page de recherche (web/app/page.tsx) pour une relecture cohérente.
import { useState } from "react";
import { DeepHit, DeepSearchResponse } from "@/lib/api";
import {
  type DisplayedHit,
  LanguageToggle,
  useDisplayLang,
  useTranslatedHits,
} from "../lang";

const EVIDENCE_LABEL: Record<number, string> = {
  1: "Preuve élevée",
  2: "Preuve modérée",
  3: "Cas / série",
  4: "Autre",
};

export function Badge({ level }: { level: number | null }) {
  if (!level) return null;
  return (
    <span className={`badge ev${level}`}>
      Niv. {level} · {EVIDENCE_LABEL[level]}
    </span>
  );
}

export function DeepScoreBar({ score }: { score: number }) {
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
}: {
  hit: DeepHit;
  rank: number;
  display: DisplayedHit;
}) {
  return (
    <article className="result">
      <h3>
        <span className="rank">#{rank}</span>
        <a href={hit.pubmed_url} target="_blank" rel="noreferrer">
          {display.title}
        </a>
      </h3>
      <div className="journal">
        <Badge level={hit.evidence_level} />
        {hit.journal || "Journal inconnu"}
        {hit.pub_year ? ` · ${hit.pub_year}` : ""}
      </div>
      {hit.score != null && <DeepScoreBar score={hit.score} />}
      {hit.reason && <p className="explanation-note">{hit.reason}</p>}
      {display.abstract &&
        (display.translated ? (
          <div className="abstract-fr">
            <div className="abstract-fr-label">📄 Résumé (traduit en français)</div>
            <p className="abstract">{display.abstract}</p>
          </div>
        ) : (
          <details className="explanation">
            <summary>📄 Résumé (anglais)</summary>
            <p className="abstract">{display.abstract}</p>
          </details>
        ))}
    </article>
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
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              justifyContent: "flex-end",
              margin: "4px 0 12px",
            }}
          >
            <span className="meta">Langue d&apos;affichage</span>
            <LanguageToggle lang={lang} onChange={setLang} busy={busy} />
          </div>
          {payload.results.map((h, i) => (
            <HitCard key={`${h.pmid}-${i}`} hit={h} rank={i + 1} display={resolve(h)} />
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
