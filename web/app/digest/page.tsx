// Page « Digest quotidien » — APERÇU (mockup). Montre à quoi ressemblera le
// digest lié à un profil sauvegardé : chaque article sélectionné pourra être
// traduit, résumé et écouté en vocal. Ces fonctionnalités ne sont PAS encore
// implémentées : les actions sont affichées en « Bientôt ». Données factices.
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "X-Med — Digest quotidien",
  description: "Aperçu du digest quotidien personnalisé (fonctionnalités à venir).",
};

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

const PROFILE = {
  name: "Dr Eva Attal",
  specialty: "Gynécologie-obstétrique",
  interests: ["Grossesse à risque", "Endométriose", "Cancer du col", "Pré-éclampsie"],
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
  return (
    <main className="container">
      <h1>Digest quotidien</h1>
      <p className="tagline">Vos nouveaux articles, choisis pour votre profil</p>
      <p className="subtitle">
        Chaque matin, X-Med parcourt les nouvelles publications PubMed et
        sélectionne celles qui comptent pour votre pratique.
      </p>

      <div className="preview-banner">
        Aperçu — cette page et les actions ci-dessous (traduction, résumé, écoute
        vocale) arrivent bientôt.
      </div>

      {/* Profil sauvegardé */}
      <div className="panel profile-card">
        <div>
          <div className="profile-name">{PROFILE.name}</div>
          <div className="journal">{PROFILE.specialty}</div>
          <div className="chips" style={{ marginTop: 10, marginBottom: 0 }}>
            {PROFILE.interests.map((i) => (
              <span className="chip" key={i}>
                {i}
              </span>
            ))}
          </div>
        </div>
        <button type="button" className="action" disabled title="Fonctionnalité à venir">
          Modifier le profil <span className="soon">Bientôt</span>
        </button>
      </div>

      <p className="meta">Digest du 31 mai 2026 · {ARTICLES.length} nouveaux articles</p>

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
