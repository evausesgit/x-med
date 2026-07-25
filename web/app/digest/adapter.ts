/* Adaptateur pur : réponse de la pipeline v2 (DeepSearchResponse) → données du
   digest magazine (DigestData). Le backend garde UN seul format de réponse
   (décision accordée avec Codex : pas de second DTO métier à maintenir) ; la
   mise en forme éditoriale est une affaire d'affichage, donc elle vit ici. */

import type { DeepHit, DeepSearchResponse, Doctor } from "@/lib/api";
import type { Translate } from "@/lib/locale";
import type { Article, DigestData } from "./types";

// ~200 mots/min de lecture, borné pour rester plausible sur une carte.
function estimateRead(text: string | null): string {
  const words = (text ?? "").split(/\s+/).filter(Boolean).length;
  return `${Math.min(15, Math.max(1, Math.round(words / 200)))} min`;
}

export function hitToArticle(h: DeepHit, t: Translate): Article {
  const why = h.reason ? [h.reason] : [];
  const en = {
    title: h.title,
    stand: h.reason ?? "",
    abstract: h.abstract ?? "",
    why,
    spoken: `${h.title}. ${h.reason ?? ""}`.trim(),
  };
  // Tant que la traduction n'est pas arrivée (elle est streamée après les
  // résultats), la face FR retombe sur l'anglais — la bascule FR/EN de la
  // carte reste cohérente, simplement identique des deux côtés.
  const fr = {
    title: h.title_fr ?? h.title,
    stand: h.reason ?? "",
    abstract: h.abstract_fr ?? h.abstract ?? "",
    why,
    spoken: `${h.title_fr ?? h.title}. ${h.reason ?? ""}`.trim(),
  };
  return {
    id: String(h.pmid),
    journal: h.journal ?? t("digest.unknownJournal"),
    year: h.pub_year, // nullable : on n'invente ni année ni niveau de preuve
    level: h.evidence_level,
    match: h.relevance_pct ?? (h.score ?? 0) * 33,
    read: estimateRead(h.abstract),
    pubmedUrl: h.pubmed_url,
    fr,
    en,
    // DeepHit ne porte pas les MeSH de l'article (ceux de la réponse décrivent
    // la requête) : pas de chips plutôt que des chips fausses.
    mesh: [],
  };
}

export function deepSearchToDigestData(
  res: DeepSearchResponse,
  doctor: Doctor,
  // `t` transite par les options : cet adaptateur est une fonction pure, pas
  // un composant — il ne peut pas lire le contexte i18n lui-même.
  opts: { date: string; generated: string; days: number; t: Translate },
): DigestData | null {
  if (res.results.length === 0) return null; // le type impose un article phare
  const p = doctor.profile;
  const themes = p
    ? [...p.subspecialties, ...p.pathologies, ...p.mesh_terms_extra].slice(0, 6)
    : [];
  const { t } = opts;
  const [lead, ...articles] = res.results.map((h) => hitToArticle(h, t));
  return {
    date: opts.date,
    generated: opts.generated,
    method: t("digest.method", { days: opts.days }),
    doctor: {
      name: doctor.name,
      specialty: p?.specialty_main || t("digest.unknownSpecialty"),
    },
    themes,
    lead,
    articles,
  };
}
