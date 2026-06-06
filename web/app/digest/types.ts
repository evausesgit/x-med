/* X-Med — Digest Magazine : types des données.
   Façonnez votre réponse serveur (/api/doctors + sélection d'articles) à cette forme. */

export interface LocalizedText {
  /** Titre dans la langue */
  title: string;
  /** Chapô / accroche (1–2 phrases) */
  stand: string;
  /** Abstract complet (révélé au clic sur la carte) */
  abstract: string;
}

export interface Article {
  /** Identifiant unique (ex. PMID ou slug) — sert de clé React + état audio */
  id: string;
  journal: string;
  year: number;
  /** Niveau de preuve 1..4 (1 = méta-analyse/RCT … 4 = avis) */
  level: number;
  /** Pertinence pour le profil, 0..100 (jauge + barre) */
  match: number;
  /** Temps de lecture estimé, ex. "4 min" */
  read: string;
  /** Version française (traduction) */
  fr: LocalizedText;
  /** Version anglaise (source PubMed) */
  en: LocalizedText;
  /** Résumé IA en puces (3–4 lignes) */
  why: string[];
  /** Texte lu à voix haute (synthèse vocale FR) */
  spoken: string;
  /** Termes MeSH (chips, révélés au clic sur la carte) */
  mesh: string[];
}

export interface DigestData {
  /** Date affichée, ex. "Jeudi 31 mai 2026" */
  date: string;
  /** Heure de génération, ex. "06:00" */
  generated: string;
  /** Modèle d'embedding affiché, ex. "bge-m3" */
  model: string;
  doctor: { name: string; specialty: string };
  /** Thèmes du profil (puces en pied de page) */
  themes: string[];
  /** Article mis en avant (panneau sombre) */
  lead: Article;
  /** Reste de la sélection (grille 2 colonnes) */
  articles: Article[];
}
