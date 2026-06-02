"use client";

// Page « Digest quotidien » — rendu « magazine » (composant DigestMagazine).
// L'EN-TÊTE est RÉEL : médecin + thèmes lus depuis /api/doctors.
// La SÉLECTION d'articles reste un APERÇU (sampleDigest) tant que la génération
// du digest n'est pas branchée. Voir getDigest() ci-dessous : remplacez la
// partie `articles`/`lead` par la vraie sélection au format DigestData.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Doctor, listDoctors } from "@/lib/api";
import DigestMagazine from "./DigestMagazine";
import { sampleDigest } from "./sample-data";
import type { DigestData } from "./types";

// Date du jour en français, ex. « Lundi 2 juin 2026 » (capitalisée).
function todayFr(): string {
  const s = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Construit le DigestData rendu par le composant.
// Aujourd'hui : en-tête issu du vrai profil, articles encore en aperçu.
// Demain : remplacer lead/articles par la sélection renvoyée par l'API.
function getDigest(doctor: Doctor): DigestData {
  const p = doctor.profile;
  const themes = p
    ? [...p.subspecialties, ...p.pathologies, ...p.mesh_terms_extra].slice(0, 6)
    : sampleDigest.themes;

  return {
    ...sampleDigest, // lead + articles : aperçu (sélection non implémentée)
    date: todayFr(),
    doctor: {
      name: doctor.name,
      specialty: p?.specialty_main || "Spécialité non renseignée",
    },
    themes: themes.length ? themes : sampleDigest.themes,
  };
}

export default function DigestPage() {
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    listDoctors().then(setDoctors);
  }, []);

  const doctor = doctors?.[idx] ?? null;
  const data = useMemo(
    () => (doctor ? getDigest(doctor) : null),
    [doctor],
  );

  return (
    <main className="container">
      <div className="preview-banner">
        Aperçu — l&apos;en-tête (médecin, thèmes) est lié à un vrai profil ; la
        sélection d&apos;articles est encore un exemple en attendant la
        génération du digest.
      </div>

      {doctors !== null && doctors.length === 0 && (
        <div className="panel">
          <p style={{ margin: 0 }}>
            Aucun profil pour l&apos;instant.{" "}
            <Link href="/profil">Créer un profil →</Link>
          </p>
        </div>
      )}

      {doctors && doctors.length > 1 && (
        <div className="panel" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <label htmlFor="doctor-select">Profil :</label>
          <select
            id="doctor-select"
            value={idx}
            onChange={(e) => setIdx(Number(e.target.value))}
          >
            {doctors.map((d, k) => (
              <option key={d.id} value={k}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {data && <DigestMagazine data={data} />}
    </main>
  );
}
