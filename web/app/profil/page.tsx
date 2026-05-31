"use client";

// Gestion des profils médecins (CRUD sur /api/doctors). Un profil pilote le
// digest personnalisé (spécialité, pathologies, tags MeSH…).
import { useEffect, useState } from "react";
import {
  createDoctor,
  Doctor,
  DoctorProfile,
  listDoctors,
  updateProfile,
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
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [p, setP] = useState<DoctorProfile>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reload() {
    listDoctors().then(setDoctors);
  }
  useEffect(reload, []);

  function reset() {
    setEditingId(null);
    setName("");
    setEmail("");
    setP(EMPTY);
    setMsg(null);
  }

  function edit(d: Doctor) {
    setEditingId(d.id);
    setName(d.name);
    setEmail(d.email);
    setP(d.profile ?? EMPTY);
    setMsg(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      if (editingId) {
        await updateProfile(editingId, p);
        setMsg("Profil mis à jour ✓");
      } else {
        await createDoctor({ email, name, profile: p });
        setMsg("Profil créé ✓");
        reset();
      }
      reload();
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
      <h1>Profils</h1>
      <p className="tagline">Qui reçoit le digest, et sur quoi</p>
      <p className="subtitle">
        Un profil décrit la pratique d&apos;un médecin (spécialité, pathologies,
        tags MeSH…). Il pilotera la sélection des articles du digest.
      </p>

      <form className="panel" onSubmit={submit}>
        <h2 className="bench-ds" style={{ marginTop: 0 }}>
          {editingId ? "Modifier le profil" : "Nouveau profil"}
        </h2>
        <div className="filters" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
          <div className="field" style={{ flex: "1 1 240px" }}>
            <label>Nom</label>
            <input value={name} onChange={(e) => setName(e.target.value)} disabled={!!editingId} required />
          </div>
          <div className="field" style={{ flex: "1 1 240px" }}>
            <label>Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} disabled={!!editingId} required />
          </div>
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
            {busy ? "…" : editingId ? "Enregistrer" : "Créer le profil"}
          </button>
          {editingId && (
            <button type="button" onClick={reset}>
              Annuler
            </button>
          )}
          {msg && <span className="meta" style={{ margin: 0 }}>{msg}</span>}
        </div>
      </form>

      <p className="meta">{doctors.length} profil(s)</p>
      {doctors.map((d) => (
        <article className="result" key={d.id}>
          <h3 style={{ gridTemplateColumns: "1fr auto" }}>
            <span>{d.name}</span>
            <button onClick={() => edit(d)} style={{ minHeight: 32, fontSize: 13 }}>
              Modifier
            </button>
          </h3>
          <div className="journal">
            {d.profile?.specialty_main || "Spécialité non renseignée"} · {d.email}
          </div>
          {d.profile && (
            <div className="chips" style={{ marginTop: 10, marginBottom: 0 }}>
              {[...d.profile.subspecialties, ...d.profile.pathologies, ...d.profile.mesh_terms_extra]
                .slice(0, 10)
                .map((t, i) => (
                  <span className="chip" key={`${t}-${i}`}>
                    {t}
                  </span>
                ))}
            </div>
          )}
        </article>
      ))}
    </main>
  );
}
