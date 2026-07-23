"use client";

// Mon profil — rattaché au compte Google connecté. Au chargement, /me/bootstrap
// crée ou retrouve le médecin (rattachement par UID Firebase, repli par email
// pour les profils créés avant l'auth) ; le formulaire n'édite que les
// préférences médicales qui pilotent le digest.
import { useEffect, useState } from "react";
import {
  bootstrapMe,
  Doctor,
  DoctorProfile,
  updateMyProfile,
} from "@/lib/api";

const EMPTY: DoctorProfile = {
  specialty_main: "",
  subspecialties: [],
  pathologies: [],
  treatments: [],
  study_types: [],
  min_evidence_level: null,
  preferred_journals: [],
  mesh_terms_extra: [],
  keywords_extra: [],
};

const toArr = (s: string) =>
  s.split(",").map((x) => x.trim()).filter(Boolean);
const toStr = (a: string[]) => a.join(", ");

export default function ProfilPage() {
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [p, setP] = useState<DoctorProfile>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    bootstrapMe()
      .then((d) => {
        setDoctor(d);
        setP(d.profile ?? EMPTY);
      })
      .catch((err) =>
        setLoadError(err instanceof Error ? err.message : "Erreur"),
      );
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const d = await updateMyProfile(p);
      setDoctor(d);
      setP(d.profile ?? EMPTY);
      setMsg("Profil mis à jour ✓");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  const field = (k: keyof DoctorProfile, label: string) => (
    <div className="field" style={{ flex: "1 1 240px" }}>
      <label>{label}</label>
      <input
        type="text"
        value={toStr(p[k] as string[])}
        onChange={(e) => setP({ ...p, [k]: toArr(e.target.value) })}
        placeholder="séparés par des virgules"
      />
    </div>
  );

  return (
    <main className="container">
      <h1>Mon profil</h1>
      <p className="tagline">Ce que vous recevez dans le digest, et pourquoi</p>
      <p className="subtitle">
        Votre profil est lié à votre compte Google. Il décrit votre pratique
        (spécialité, pathologies, tags MeSH…) et pilote la sélection des
        articles de votre digest.
      </p>

      {loadError && (
        <p className="meta">Impossible de charger le profil : {loadError}</p>
      )}
      {!doctor && !loadError && <p className="meta">Chargement…</p>}

      {doctor && (
        <form className="panel" onSubmit={submit}>
          <h2 className="bench-ds" style={{ marginTop: 0 }}>
            {doctor.name}
            <span className="meta" style={{ marginLeft: 10 }}>{doctor.email}</span>
          </h2>
          <div className="filters" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
            <div className="field" style={{ flex: "1 1 240px" }}>
              <label>Spécialité principale</label>
              <input
                value={p.specialty_main}
                onChange={(e) => setP({ ...p, specialty_main: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="filters" style={{ borderTop: 0, marginTop: 12, paddingTop: 0 }}>
            {field("subspecialties", "Sous-spécialités")}
            {field("pathologies", "Pathologies")}
            {field("treatments", "Traitements")}
            {field("mesh_terms_extra", "Tags MeSH (anglais)")}
            {field("keywords_extra", "Mots-clés")}
            {field("preferred_journals", "Revues préférées")}
            <div className="field">
              <label>Niveau de preuve min.</label>
              <select
                value={p.min_evidence_level ?? ""}
                onChange={(e) =>
                  setP({ ...p, min_evidence_level: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Tous</option>
                <option value="1">1 — élevé</option>
                <option value="2">≤ 2</option>
                <option value="3">≤ 3</option>
                <option value="4">≤ 4</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "…" : "Enregistrer"}
            </button>
            {msg && <span className="meta" style={{ margin: 0 }}>{msg}</span>}
          </div>
        </form>
      )}
    </main>
  );
}
