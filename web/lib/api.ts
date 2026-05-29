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
