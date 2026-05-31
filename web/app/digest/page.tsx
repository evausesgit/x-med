"use client";

// Page « Digest quotidien ». L'en-tête (profil) est RÉEL (lu depuis /api/doctors) ;
// la liste d'articles est encore un APERÇU (la génération du digest n'est pas
// implémentée) avec actions Traduire / Résumer / Écouter en « Bientôt ».
import { useEffect, useState } from "react";
import Link from "next/link";
import { Doctor, listDoctors } from "@/lib/api";

type DemoArticle = {
  title: string;
  journal: string;
  year: number;
  level: number;
  levelLabel: string;
  match: number;
  matchLabel: string;
  snippet: string;
  tags: string[];
};

const ARTICLES: DemoArticle[] = [
  {
    title:
      "Aspirin for the prevention of pre-eclampsia in high-risk pregnancies: an updated meta-analysis",
    journal: "American Journal of Obstetrics & Gynecology",
    year: 2026,
    level: 1,
    levelLabel: "Preuve élevée",
    match: 94,
    matchLabel: "Très pertinent",
    snippet:
      "Low-dose aspirin initiated before 16 weeks of gestation significantly reduced the incidence of pre-eclampsia in women identified as high-risk…",
    tags: ["Pre-Eclampsia", "Aspirin", "Pregnancy, High-Risk"],
  },
  {
    title:
      "Long-term outcomes of conservative versus surgical management of deep endometriosis",
    journal: "Human Reproduction",
    year: 2026,
    level: 2,
    levelLabel: "Preuve modérée",
    match: 88,
    matchLabel: "Très pertinent",
    snippet:
      "A prospective cohort comparing medical and surgical strategies for deep infiltrating endometriosis, with pain and fertility endpoints at 5 years…",
    tags: ["Endometriosis", "Pelvic Pain", "Fertility"],
  },
  {
    title:
      "HPV self-sampling to improve cervical cancer screening coverage: a randomized trial",
    journal: "The Lancet",
    year: 2026,
    level: 1,
    levelLabel: "Preuve élevée",
    match: 81,
    matchLabel: "Pertinent",
    snippet:
      "Offering HPV self-sampling increased screening participation among under-screened women compared with standard invitation…",
    tags: ["Uterine Cervical Neoplasms", "Mass Screening", "Papillomavirus"],
  },
];

function SoonAction({ icon, label }: { icon: string; label: string }) {
  return (
    <button type="button" className="action" disabled title="Fonctionnalité à venir">
      <span aria-hidden>{icon}</span> {label}
      <span className="soon">Bientôt</span>
    </button>
  );
}

export default function DigestPage() {
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    listDoctors().then(setDoctors);
  }, []);

  const doctor = doctors?.[idx] ?? null;
  const interests = doctor?.profile
    ? [
        ...doctor.profile.subspecialties,
        ...doctor.profile.pathologies,
        ...doctor.profile.mesh_terms_extra,
      ].slice(0, 8)
    : [];

  return (
    <main className="container">
      <h1>Digest quotidien</h1>
      <p className="tagline">Vos nouveaux articles, choisis pour votre profil</p>
      <p className="subtitle">
        Chaque matin, X-Med parcourt les nouvelles publications PubMed et
        sélectionne celles qui comptent pour votre pratique.
      </p>

      <div className="preview-banner">
        Aperçu — l&apos;en-tête est lié à un vrai profil ; la sélection
        d&apos;articles et les actions (traduction, résumé, écoute) arrivent
        bientôt.
      </div>

      {doctors !== null && doctors.length === 0 && (
        <div className="panel">
          <p style={{ margin: 0 }}>
            Aucun profil pour l&apos;instant.{" "}
            <Link href="/profil">Créer un profil →</Link>
          </p>
        </div>
      )}

      {doctor && (
        <div className="panel profile-card">
          <div>
            <div className="profile-name">{doctor.name}</div>
            <div className="journal">
              {doctor.profile?.specialty_main || "Spécialité non renseignée"}
            </div>
            {interests.length > 0 && (
              <div className="chips" style={{ marginTop: 10, marginBottom: 0 }}>
                {interests.map((i, k) => (
                  <span className="chip" key={`${i}-${k}`}>
                    {i}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
            {doctors && doctors.length > 1 && (
              <select value={idx} onChange={(e) => setIdx(Number(e.target.value))}>
                {doctors.map((d, k) => (
                  <option key={d.id} value={k}>
                    {d.name}
                  </option>
                ))}
              </select>
            )}
            <Link href="/profil" className="action" style={{ textDecoration: "none" }}>
              Modifier le profil
            </Link>
          </div>
        </div>
      )}

      <p className="meta">
        Digest du 31 mai 2026 · {ARTICLES.length} nouveaux articles{" "}
        <span className="soon">Aperçu</span>
      </p>

      {ARTICLES.map((a) => (
        <article className="result" key={a.title}>
          <h3>
            <span className={`match-label ml-${a.match >= 85 ? "high" : "mid"}`}>
              {a.matchLabel}
            </span>
            <span>{a.title}</span>
          </h3>
          <div className="journal">
            <span className={`badge ev${a.level}`}>
              Niv. {a.level} · {a.levelLabel}
            </span>
            {a.journal} · {a.year}
          </div>
          <p className="abstract">{a.snippet}</p>
          <div className="tags">
            {a.tags.map((t) => (
              <span className="tag" key={t}>
                {t}
              </span>
            ))}
          </div>
          <div className="actions">
            <SoonAction icon="🌐" label="Traduire en français" />
            <SoonAction icon="✨" label="Résumé IA" />
            <SoonAction icon="🔊" label="Écouter" />
          </div>
        </article>
      ))}
    </main>
  );
}
