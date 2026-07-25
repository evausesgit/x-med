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
import { useT } from "@/lib/i18n";
import { LOCALES, type Locale, type MessageKey } from "@/lib/locale";

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
  const { t, locale, setLocale } = useT();
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
        setLoadError(err instanceof Error ? err.message : t("common.error")),
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
      setMsg(t("profile.saved"));
    } catch (err) {
      setMsg(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  const field = (k: keyof DoctorProfile, labelKey: MessageKey) => (
    <div className="field" style={{ flex: "1 1 240px" }}>
      <label>{t(labelKey)}</label>
      <input
        type="text"
        value={toStr(p[k] as string[])}
        onChange={(e) => setP({ ...p, [k]: toArr(e.target.value) })}
        placeholder={t("profile.commaSeparated")}
      />
    </div>
  );

  return (
    <main className="container">
      <h1>{t("profile.title")}</h1>
      <p className="tagline">{t("profile.tagline")}</p>
      <p className="subtitle">{t("profile.subtitle")}</p>

      {loadError && (
        <p className="meta">{t("profile.loadFailed", { error: loadError })}</p>
      )}
      {!doctor && !loadError && <p className="meta">{t("common.loading")}</p>}

      {doctor && (
        <form className="panel" onSubmit={submit}>
          <h2 className="bench-ds" style={{ marginTop: 0 }}>
            {doctor.name}
            <span className="meta" style={{ marginLeft: 10 }}>{doctor.email}</span>
          </h2>
          {/* Langue du compte : elle est enregistrée immédiatement (pas au
              « Enregistrer » du formulaire) parce qu'elle change l'interface
              sous les yeux de l'utilisateur — attendre une validation
              donnerait un formulaire à moitié traduit. */}
          <div className="filters" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
            <div className="field" style={{ flex: "1 1 240px" }}>
              <label htmlFor="profile-language">{t("profile.languageSection")}</label>
              <select
                id="profile-language"
                value={locale}
                onChange={(e) => setLocale(e.target.value as Locale)}
              >
                {LOCALES.map((l) => (
                  <option key={l} value={l}>
                    {t(`lang.${l === "fr" ? "french" : "english"}`)}
                  </option>
                ))}
              </select>
            </div>
            <p className="meta" style={{ flex: "1 1 100%", margin: 0 }}>
              {t("profile.languageHelp")}
            </p>
          </div>
          <div className="filters" style={{ borderTop: 0, marginTop: 12, paddingTop: 0 }}>
            <div className="field" style={{ flex: "1 1 240px" }}>
              <label>{t("profile.specialty")}</label>
              <input
                value={p.specialty_main}
                onChange={(e) => setP({ ...p, specialty_main: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="filters" style={{ borderTop: 0, marginTop: 12, paddingTop: 0 }}>
            {field("subspecialties", "profile.subspecialties")}
            {field("pathologies", "profile.pathologies")}
            {field("treatments", "profile.treatments")}
            {field("mesh_terms_extra", "profile.meshTerms")}
            {field("keywords_extra", "profile.keywords")}
            {field("preferred_journals", "profile.journals")}
            <div className="field">
              <label>{t("profile.minEvidence")}</label>
              <select
                value={p.min_evidence_level ?? ""}
                onChange={(e) =>
                  setP({ ...p, min_evidence_level: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">{t("profile.evidenceAll")}</option>
                <option value="1">{t("profile.evidence1")}</option>
                <option value="2">{t("profile.evidence2")}</option>
                <option value="3">{t("profile.evidence3")}</option>
                <option value="4">{t("profile.evidence4")}</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? t("common.working") : t("profile.save")}
            </button>
            {msg && <span className="meta" style={{ margin: 0 }}>{msg}</span>}
          </div>
        </form>
      )}
    </main>
  );
}
