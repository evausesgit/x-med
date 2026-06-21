// Appels relatifs : ils passent par le proxy Next (/api → FastAPI), donc ils
// fonctionnent quel que soit l'hôte depuis lequel le navigateur ouvre le site.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

export interface ArticleResult {
  pmid: number;
  title: string;
  journal: string | null;
  pub_year: number | null;
  evidence_level: number | null;
  mesh_terms: string[] | null;
  abstract_snippet: string | null;
  doi: string | null;
  score: number | null;
  pubmed_url: string;
  // Optionnel pendant les déploiements où le frontend et l'API ne basculent
  // pas exactement au même instant.
  explanation?: ArticleExplanation;
}

export interface ArticleExplanation {
  concepts: string[];
  population: string | null;
  intervention: string | null;
  study_type: string | null;
}

export interface SearchResponse {
  total: number;
  results: ArticleResult[];
}


export interface PubmedLog {
  phase: string;
  msg: string;
  pubmed_query?: string;
  mesh_terms?: string[];
}


// --- Méthode v2 « PubMed + codex » : filtre lexical+MeSH → codex juge (deep) ---
export interface DeepHit {
  pmid: number;
  title: string;
  journal: string | null;
  pub_year: number | null;
  doi: string | null;
  pubmed_url: string;
  in_db: boolean;
  source: "pubmed" | "local" | "both";
  evidence_level: number | null;
  score: number | null; // 0–3
  reason: string | null;
  abstract: string | null; // abstract original (EN)
  abstract_fr: string | null; // traduction FR (cache ou streamée)
}

export interface DeepSearchResponse {
  query: string;
  pubmed_query: string | null;
  mesh_terms: string[];
  keywords_en: string[];
  query_builder: "codex" | "fallback";
  judge: "codex" | "skipped";
  codex_limit?: boolean;
  codex_tokens?: Record<string, number>; // tokens GPT-5.4 (query / judge / total)
  counts: Record<string, number>;
  results: DeepHit[];
}

// Non streaming : filtre lexical local borné, puis un seul appel codex de jugement.
export async function searchPubmedDeep(
  query: string,
  dateFrom: string | undefined,
  dateTo: string | undefined,
  k = 12,
): Promise<DeepSearchResponse> {
  const res = await fetch(`${API_BASE}/search/pubmed/deep`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
      k_pubmed: k,
    }),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// Version streaming (SSE) de la v2 : émet le déroulé via onLog puis onResult.
// Indispensable pour les requêtes longues (codex ~1 min) : les keep-alives du
// serveur empêchent le proxy de couper à ~30 s (ce qui donnait « Erreur API 500 »).
export function searchPubmedDeepStream(
  query: string,
  dateFrom: string | undefined,
  dateTo: string | undefined,
  k: number,
  handlers: {
    onLog: (log: PubmedLog) => void;
    onResult: (res: DeepSearchResponse) => void;
    onError: (msg?: string) => void;
    // Traductions FR arrivant après les résultats (au fur et à mesure).
    onTranslations?: (
      fr: Record<string, { title_fr: string; abstract_fr: string }>,
    ) => void;
  },
): EventSource {
  const sp = new URLSearchParams({ query, k_pubmed: String(k) });
  if (dateFrom) sp.set("date_from", dateFrom);
  if (dateTo) sp.set("date_to", dateTo);
  const es = new EventSource(`${API_BASE}/search/pubmed/deep/stream?${sp.toString()}`);
  es.addEventListener("log", (e) => {
    try {
      handlers.onLog(JSON.parse((e as MessageEvent).data));
    } catch {
      /* ignore une ligne malformée */
    }
  });
  es.addEventListener("translations", (e) => {
    try {
      handlers.onTranslations?.(JSON.parse((e as MessageEvent).data));
    } catch {
      /* ignore */
    }
  });
  es.addEventListener("result", (e) => {
    try {
      handlers.onResult(JSON.parse((e as MessageEvent).data));
    } finally {
      es.close();
    }
  });
  es.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data;
    if (data) {
      try {
        handlers.onError(JSON.parse(data).msg);
      } catch {
        handlers.onError();
      }
    } else {
      handlers.onError();
    }
    es.close();
  });
  return es;
}

// Traduction FR à la demande d'un article (bouton « Traduire en français »).
// Sert le cache côté API, sinon appelle codex et met en cache.
export interface TranslationResult {
  pmid: number;
  title_fr: string | null;
  abstract_fr: string | null;
}

export async function translateAbstract(
  pmid: number,
  title?: string | null,
  abstract?: string | null,
): Promise<TranslationResult> {
  const res = await fetch(`${API_BASE}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pmid, title, abstract }),
  });
  if (!res.ok) {
    if (res.status === 429)
      throw new Error("Limite d'usage GPT-5.4 atteinte — réessayez plus tard.");
    throw new Error(`Erreur API (${res.status})`);
  }
  return res.json();
}

export interface SearchParams {
  q?: string;
  mesh?: string[];
  mode?: "and" | "or";
  yearFrom?: number;
  yearTo?: number;
  evidenceMax?: number;
  limit?: number;
  offset?: number;
}

export async function searchMesh(p: SearchParams): Promise<SearchResponse> {
  const qs = new URLSearchParams();
  if (p.q) qs.set("q", p.q);
  (p.mesh || []).forEach((m) => qs.append("mesh", m));
  if (p.mode) qs.set("mode", p.mode);
  if (p.yearFrom) qs.set("year_from", String(p.yearFrom));
  if (p.yearTo) qs.set("year_to", String(p.yearTo));
  if (p.evidenceMax) qs.set("evidence_max", String(p.evidenceMax));
  qs.set("limit", String(p.limit ?? 20));
  qs.set("offset", String(p.offset ?? 0));
  const res = await fetch(`${API_BASE}/search/mesh?${qs.toString()}`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

export async function meshAutocomplete(q: string): Promise<string[]> {
  if (!q) return [];
  const res = await fetch(`${API_BASE}/mesh/autocomplete?q=${encodeURIComponent(q)}&limit=8`);
  if (!res.ok) return [];
  return res.json();
}

export interface EmbeddingModelInfo {
  name: string;
  dim: number;
  embedded: number;
}

export async function listModels(): Promise<EmbeddingModelInfo[]> {
  try {
    const res = await fetch(`${API_BASE}/models`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

// Avancement de la vectorisation du corpus (page /embeddings).
export interface EmbeddingCoverage {
  embedded: number;
  total: number;
}
export interface EmbeddingYearRow {
  year: number;
  total: number;
  embedded: number;
}
export interface EmbeddingProgress {
  model: string;
  global: EmbeddingCoverage;
  planned: EmbeddingCoverage;
  by_year: EmbeddingYearRow[];
}

export async function getEmbeddingProgress(
  model = "bge_m3",
): Promise<EmbeddingProgress | null> {
  try {
    const res = await fetch(
      `${API_BASE}/embeddings/progress?model=${encodeURIComponent(model)}`,
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function searchHybrid(
  q: string,
  model: string,
  limit = 20,
): Promise<SearchResponse> {
  const qs = new URLSearchParams({ q, model, limit: String(limit) });
  const res = await fetch(`${API_BASE}/search/hybrid?${qs.toString()}`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// Recherche « par sens » pure : plus proches voisins par similarité cosinus.
// Contrairement à /search/hybrid, le `score` renvoyé est la similarité cosinus
// (0–1), un signal ABSOLU et interprétable — pas un score de fusion RRF.
export async function searchSemantic(
  query: string,
  model: string,
  k = 20,
): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE}/search/semantic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, model, k }),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// Leaderboard du benchmark (table bench_*), pour la page « Évaluation ».
export interface BenchRow {
  model: string;
  dataset: string;
  created_at: string;
  metrics: Record<string, number>;
}

export async function listLeaderboard(): Promise<BenchRow[]> {
  try {
    const res = await fetch(`${API_BASE}/bench/leaderboard`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

// ---------- Annotation (gold set) ----------
export interface EvalQueryProgress {
  query_id: number;
  theme: string | null;
  query: string;
  n_candidates: number;
  n_annotated: number;
}
export interface EvalCandidate {
  pmid: number;
  title: string;
  journal: string | null;
  pub_year: number | null;
  abstract: string | null;
  title_fr: string | null;
  abstract_fr: string | null;
  pubmed_url: string;
  found_by: string | null;
  grade: number | null;
}
export interface EvalPool {
  query_id: number;
  theme: string | null;
  query: string;
  candidates: EvalCandidate[];
}

export async function listEvalQueries(): Promise<EvalQueryProgress[]> {
  const res = await fetch(`${API_BASE}/eval/queries`);
  if (!res.ok) return [];
  return res.json();
}
export async function getEvalPool(queryId: number): Promise<EvalPool> {
  const res = await fetch(`${API_BASE}/eval/pool/${queryId}`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}
export async function annotate(
  query_id: number,
  pmid: number,
  grade: number,
  annotator?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/eval/annotate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query_id, pmid, grade, annotator }),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
}

// ---------- Médecins / profils ----------
export interface DoctorProfile {
  specialty_main: string;
  subspecialties: string[];
  pathologies: string[];
  treatments: string[];
  study_types: string[];
  min_evidence_level: number | null;
  preferred_journals: string[];
  mesh_terms_extra: string[];
  keywords_extra: string[];
}
export interface Doctor {
  id: string;
  email: string;
  name: string;
  language: string;
  digest_frequency: string;
  profile: DoctorProfile | null;
}

export async function listDoctors(): Promise<Doctor[]> {
  const res = await fetch(`${API_BASE}/doctors`);
  if (!res.ok) return [];
  return res.json();
}
export async function createDoctor(body: {
  email: string;
  name: string;
  profile: DoctorProfile;
}): Promise<Doctor> {
  const res = await fetch(`${API_BASE}/doctors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}
export async function updateProfile(id: string, profile: DoctorProfile): Promise<Doctor> {
  const res = await fetch(`${API_BASE}/doctors/${id}/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// ---------- Recherches sauvegardées ----------
// On enregistre le snapshot complet d'une recherche (la réponse v2 telle
// qu'affichée) pour la rouvrir/relire plus tard sans relancer codex.
export interface SavedSearchSummary {
  id: string;
  doctor_id: string | null;
  doctor_name: string | null;
  query: string;
  method: string;
  n_results: number;
  created_at: string;
}
export interface SavedSearchDetail extends SavedSearchSummary {
  params: Record<string, unknown> | null;
  payload: DeepSearchResponse;
}

export async function saveSearch(body: {
  query: string;
  payload: DeepSearchResponse;
  doctor_id?: string | null;
  method?: string;
  params?: Record<string, unknown> | null;
}): Promise<SavedSearchDetail> {
  const res = await fetch(`${API_BASE}/saved-searches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

export async function listSavedSearches(): Promise<SavedSearchSummary[]> {
  const res = await fetch(`${API_BASE}/saved-searches`);
  if (!res.ok) return [];
  return res.json();
}

// Avant de relancer une recherche v2 (coûteuse en tokens codex), on regarde si
// un snapshot identique a déjà été sauvegardé. Renvoie le plus récent, ou null.
export async function lookupSavedSearch(params: {
  query: string;
  method?: string;
  date_from?: string;
  date_to?: string;
}): Promise<SavedSearchDetail | null> {
  const sp = new URLSearchParams({ query: params.query, method: params.method ?? "v2" });
  if (params.date_from) sp.set("date_from", params.date_from);
  if (params.date_to) sp.set("date_to", params.date_to);
  const res = await fetch(`${API_BASE}/saved-searches/lookup?${sp.toString()}`);
  if (!res.ok) return null;
  return res.json();
}

export async function getSavedSearch(id: string): Promise<SavedSearchDetail> {
  const res = await fetch(`${API_BASE}/saved-searches/${id}`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

export async function deleteSavedSearch(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/saved-searches/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
}
