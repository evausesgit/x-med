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
}

export interface SearchResponse {
  total: number;
  results: ArticleResult[];
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
