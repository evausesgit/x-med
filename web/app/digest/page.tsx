"use client";

// Page « Mon Digest » — design system « X-Med App » (composant DigestView).
// L'EN-TÊTE est RÉEL : médecin + thèmes lus depuis /api/doctors.
// La SÉLECTION d'articles reste un APERÇU (sampleDigest) tant que la génération
// du digest n'est pas branchée. Voir getDigest() ci-dessous : remplacez la
// partie `articles`/`lead` par la vraie sélection au format DigestData.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Doctor, listDoctors } from "@/lib/api";
import DigestView from "./DigestView";
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
  // Avec un profil : en-tête réel. Sans aucun profil (ex. preview fraîche) : on
  // montre quand même le digest de démonstration pour donner à voir le design.
  const noProfile = doctors !== null && doctors.length === 0;
  const data = useMemo(
    () => (doctor ? getDigest(doctor) : noProfile ? { ...sampleDigest, date: todayFr() } : null),
    [doctor, noProfile],
  );

  return (
    <main className="xm-page">
      <div className="xm-banner warn" style={{ marginTop: 0 }}>
        {noProfile ? (
          <>
            Aperçu de démonstration — aucun profil n&apos;existe encore.{" "}
            <Link href="/profil">Créer un profil →</Link> pour personnaliser cette veille.
          </>
        ) : (
          <>
            Aperçu — l&apos;en-tête (médecin, thèmes) est lié à un vrai profil ; la
            sélection d&apos;articles est encore un exemple en attendant la génération du
            digest.
          </>
        )}
      </div>

      {doctors && doctors.length > 1 && (
        <div
          className="xm-method-row"
          style={{ marginTop: 0, marginBottom: 24, gap: 10 }}
        >
          <label htmlFor="doctor-select" className="xm-method-label">
            PROFIL
          </label>
          <select
            id="doctor-select"
            value={idx}
            onChange={(e) => setIdx(Number(e.target.value))}
            style={{ width: "auto", minWidth: 200 }}
          >
            {doctors.map((d, k) => (
              <option key={d.id} value={k}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {data && <DigestView data={data} />}
    </main>
  );
}
