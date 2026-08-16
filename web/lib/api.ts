// Appels relatifs : ils passent par le proxy Next (/api → FastAPI), donc ils
// fonctionnent quel que soit l'hôte depuis lequel le navigateur ouvre le site.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

// Verdict de codex sur UN article soumis au juge — y compris les rejetés, qui
// n'apparaissent nulle part ailleurs (ni dans les résultats, ni dans le reste
// du vivier). `score: null` = article soumis mais absent de la réponse de codex.
export interface Judgement {
  pmid: number;
  title: string;
  score: number | null; // 0–3
  relevance_pct: number | null; // 0–100
  reason: string | null;
  kept: boolean; // score ≥ seuil de conservation
}

export interface PubmedLog {
  phase: string;
  msg: string;
  elapsed_s?: number; // temps écoulé depuis le début du run, en secondes
  pubmed_query?: string;
  mesh_terms?: string[];
  judgements?: Judgement[]; // jalon `judge_detail` uniquement
}

// Un jalon prêt à afficher dans le déroulé : temps CUMULÉ depuis le début du
// run et ÉCART avec le jalon précédent (le temps qu'a coûté cette étape).
export interface TimedLog extends PubmedLog {
  text: string; // msg nettoyé du suffixe « (12.3s) » des runs d'avant
  elapsed: number | null; // cumulé
  delta: number | null; // écart avec le jalon précédent
}

// Runs enregistrés avant que le temps ne devienne une donnée du jalon : il
// n'existait que collé au texte. On le récupère et on le retire du message,
// sinon la même durée s'afficherait deux fois.
const TRAILING_ELAPSED = /\s*\((\d+(?:\.\d+)?)s\)\s*$/;

export function withTimings(logs: PubmedLog[]): TimedLog[] {
  let prev = 0; // dernier cumulé affiché
  let offset = 0; // décalage du flux courant (voir plus bas)
  let lastRaw = 0; // dernier temps brut reçu
  return logs.map((l) => {
    const msg = l.msg ?? "";
    const legacy = TRAILING_ELAPSED.exec(msg);
    const raw =
      typeof l.elapsed_s === "number"
        ? l.elapsed_s
        : legacy
          ? parseFloat(legacy[1])
          : null;
    const text = legacy ? msg.slice(0, legacy.index) : msg;
    let elapsed: number | null = null;
    if (raw !== null) {
      // « Analyser 50 de plus » ouvre un NOUVEAU flux, dont le chrono repart de
      // zéro alors que ses jalons s'ajoutent au même déroulé : un temps brut qui
      // recule signale ce passage, on enchaîne à partir du cumulé courant plutôt
      // que de faire redescendre la colonne.
      if (raw < lastRaw) offset = prev;
      lastRaw = raw;
      elapsed = offset + raw;
    }
    // Le premier jalon a pour écart le temps écoulé depuis le début (prev = 0).
    const delta = elapsed === null ? null : Math.max(0, elapsed - prev);
    if (elapsed !== null) prev = elapsed;
    return { ...l, text, elapsed, delta };
  });
}

// « 4,2 s » / « 1 min 07 s » — durée courte lisible d'un coup d'œil.
export function fmtSeconds(s: number): string {
  if (s >= 60) {
    const m = Math.floor(s / 60);
    return `${m} min ${String(Math.round(s % 60)).padStart(2, "0")} s`;
  }
  return `${s.toFixed(1).replace(".", ",")} s`;
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
  score: number | null; // 0–3 (tri stable)
  relevance_pct?: number | null; // 0–100 (affichage fin de l'anneau)
  reason: string | null; // « apport » : ce que l'article apporte au lecteur
  abstract: string | null; // abstract original (EN)
  abstract_fr: string | null; // traduction FR (cache ou streamée)
  title_fr?: string | null; // titre traduit FR (cache ou streamé)
  /** hors de la fenêtre de dates demandée : PubMed n'est plus borné par les
      dates (rappel maximal), donc un article ancien peut remonter s'il est le
      seul pertinent — affiché avec un badge « hors période ». */
  out_of_window?: boolean;
}

export interface DeepSearchResponse {
  query: string;
  pubmed_query: string | null;
  mesh_terms: string[];
  keywords_en: string[];
  query_builder: "codex" | "fallback";
  judge: "codex" | "skipped";
  codex_limit?: boolean;
  codex_tokens?: Record<string, number>; // tokens GPT-5.6 (query / judge / total)
  counts: Record<string, number>;
  results: DeepHit[];
  // PMID jugeables pas encore soumis à codex : permet « Analyser 50 de plus ».
  remaining?: number[];
}

// Réponse d'un lot supplémentaire « Analyser N de plus » (/search/pubmed/deep/more).
export interface DeepMoreResponse {
  judge: "codex" | "skipped";
  codex_limit?: boolean;
  codex_tokens?: Record<string, number>;
  judged: number;
  kept: number;
  results: DeepHit[];
}

// Non streaming : filtre lexical local borné, puis un seul appel codex de jugement.
export async function searchPubmedDeep(
  query: string,
  dateFrom: string | undefined,
  dateTo: string | undefined,
  k = 20,
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

// Handlers du contrat SSE partagé recherche v2 / digest :
// `log`* → `result` → `translations`* → `complete` (ou `stopped` / `error`).
export interface DeepStreamHandlers<T> {
  onLog: (log: PubmedLog) => void;
  onResult: (res: T) => void;
  onError: (msg?: string) => void;
  // Traductions FR arrivant APRÈS les résultats (au fur et à mesure).
  onTranslations?: (
    fr: Record<string, { title_fr: string; abstract_fr: string }>,
  ) => void;
  // Recherche arrêtée côté serveur (bouton stop — en général le front a déjà
  // fermé le flux ; couvre les arrêts venus d'ailleurs, ex. autre onglet).
  onStopped?: () => void;
  // Fin du flux (traductions comprises) — le spinner peut s'éteindre ici.
  onComplete?: () => void;
}

// Écoute d'un flux au contrat partagé. On ne ferme QUE sur `complete`, `stopped`
// ou `error` : fermer sur `result` (comportement historique) perdait les
// traductions streamées ensuite. Une coupure réseau APRÈS `result` est traitée
// comme une fin de flux, pas comme une erreur (les résultats sont déjà là).
function listenDeepStream<T>(es: EventSource, handlers: DeepStreamHandlers<T>): EventSource {
  let gotResult = false;
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
    gotResult = true;
    try {
      handlers.onResult(JSON.parse((e as MessageEvent).data));
    } catch {
      /* payload illisible : l'événement error/complete suivra */
    }
  });
  es.addEventListener("complete", () => {
    es.close();
    handlers.onComplete?.();
  });
  es.addEventListener("stopped", () => {
    handlers.onStopped?.();
    es.close();
  });
  es.addEventListener("error", (e) => {
    es.close();
    if (gotResult) {
      handlers.onComplete?.();
      return;
    }
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
  });
  return es;
}

// ---------- Digest en arrière-plan ----------
// La génération tourne côté serveur, détachée de la page : on POSTe pour la
// lancer, puis on POLLE le run (la table digest_runs est la source de vérité).
// La « query » est composée CÔTÉ SERVEUR depuis le profil du médecin connecté
// (metaprompt + facettes) — elle ne transite jamais par l'URL.

export type DigestRunStatus =
  | "running"
  | "translating" // payload déjà disponible, traductions FR en cours
  | "complete"
  | "error"
  | "stopped";

export interface DigestRunSummary {
  id: string;
  digest_date: string; // YYYY-MM-DD (journée du digest, heure de Paris)
  days: number;
  status: DigestRunStatus;
  n_results: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface DigestRun extends DigestRunSummary {
  logs: PubmedLog[];
  payload: DeepSearchResponse | null;
}

export interface DigestHistory {
  // Run actif éventuel ; il peut coexister avec le digest complet du même jour
  // (l'ancien reste affiché tant que la régénération n'a pas abouti).
  current: DigestRunSummary | null;
  days: DigestRunSummary[]; // dernier run complet de chaque journée, récent d'abord
}

// Lance une génération. Rejette avec le message API en cas de 409 (une
// génération est déjà en cours) ou de profil manquant (404).
export async function generateDigest(days: number): Promise<DigestRunSummary> {
  const res = await fetch(`${API_BASE}/digest/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days }),
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new Error(detail || `Erreur API (${res.status})`);
  }
  return res.json();
}

export async function getDigestRun(id: string): Promise<DigestRun> {
  const res = await fetch(`${API_BASE}/digest/runs/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// Best-effort : renvoie false (sans jeter) si rien n'était à annuler.
export async function stopDigestRun(id: string): Promise<boolean> {
  try {
    const res = await fetch(
      `${API_BASE}/digest/runs/${encodeURIComponent(id)}/stop`,
      { method: "POST" },
    );
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.stopped;
  } catch {
    return false;
  }
}

// null si aucun profil rattaché au compte (404) — même convention que getMe.
export async function getDigestHistory(): Promise<DigestHistory | null> {
  const res = await fetch(`${API_BASE}/digest/history`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// ---------- Recherche en arrière-plan ----------
// Même modèle que le digest : la recherche PubMed + IA tourne côté serveur,
// détachée de la page — verrouiller son téléphone ou changer d'onglet ne
// l'interrompt plus. On POSTe pour lancer, puis on POLLE le run ; chaque run
// abouti devient une entrée de l'historique de recherche du compte.

export interface SearchRunParams {
  k_pubmed?: number;
  rrf?: boolean;
  judge_batch?: number;
  local_floor?: number;
}

export interface SearchRunSummary {
  id: string;
  query: string;
  date_from: string | null; // YYYY-MM-DD
  date_to: string | null;
  params: SearchRunParams;
  status: DigestRunStatus; // même cycle de vie que le digest
  n_results: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface SearchRun extends SearchRunSummary {
  logs: PubmedLog[];
  payload: DeepSearchResponse | null;
}

export interface SearchRunHistory {
  current: SearchRunSummary | null; // run actif éventuel (running/translating)
  runs: SearchRunSummary[]; // derniers runs aboutis, récent d'abord
}

// Lance une recherche en arrière-plan. Rejette avec le message API en cas de
// 409 (une recherche est déjà en cours pour ce compte — s'y raccrocher).
export async function createSearchRun(body: {
  query: string;
  date_from?: string;
  date_to?: string;
  k_pubmed?: number;
  rrf?: boolean;
  judge_batch?: number;
  local_floor?: number;
}): Promise<SearchRunSummary> {
  const res = await fetch(`${API_BASE}/search/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new Error(detail || `Erreur API (${res.status})`);
  }
  return res.json();
}

export async function getSearchRun(id: string): Promise<SearchRun> {
  const res = await fetch(`${API_BASE}/search/runs/${encodeURIComponent(id)}`);
  if (!res.ok) {
    // Le statut HTTP permet au polling de distinguer un hoquet réseau (on
    // réessaie) d'une erreur définitive comme 401/404 (on abandonne le suivi).
    const err = new Error(`Erreur API (${res.status})`) as Error & {
      status?: number;
    };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// Best-effort : renvoie false (sans jeter) si rien n'était à annuler.
export async function stopSearchRun(id: string): Promise<boolean> {
  try {
    const res = await fetch(
      `${API_BASE}/search/runs/${encodeURIComponent(id)}/stop`,
      { method: "POST" },
    );
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.stopped;
  } catch {
    return false;
  }
}

export async function getSearchRunHistory(): Promise<SearchRunHistory> {
  const res = await fetch(`${API_BASE}/search/runs`);
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}

// Bouton stop : annule la requête FTS locale en cours (identifiée par le jeton
// passé au stream). La recherche continue avec les seuls résultats PubMed.
// Best-effort : renvoie false (sans jeter) si rien n'était à annuler.
export async function stopLocalSearch(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/search/local/stop/${encodeURIComponent(token)}`, {
      method: "POST",
    });
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.stopped;
  } catch {
    return false;
  }
}

// « Analyser N de plus » : juge un lot supplémentaire de PMID (issus de
// DeepSearchResponse.remaining) en SSE — même raison que ci-dessus (codex long).
export function searchPubmedDeepMoreStream(
  query: string,
  pmids: number[],
  handlers: DeepStreamHandlers<DeepMoreResponse>,
  dateFrom?: string,
  dateTo?: string,
): EventSource {
  // Les dates ne filtrent pas ce lot : elles servent à marquer « hors période »
  // les articles anciens, exactement comme dans la recherche initiale.
  const sp = new URLSearchParams({ query, pmids: pmids.join(",") });
  if (dateFrom) sp.set("date_from", dateFrom);
  if (dateTo) sp.set("date_to", dateTo);
  const es = new EventSource(
    `${API_BASE}/search/pubmed/deep/more/stream?${sp.toString()}`,
  );
  return listenDeepStream(es, handlers);
}

// --- Analyse critique comparative (V1) : 2–3 articles sélectionnés → tableau ---
export interface CompareRow {
  pmid: number;
  title: string | null;
  study_type: string;
  population: string;
  primary_outcome: string;
  effect_size: string;
  limits: string;
}

export interface CompareResult {
  query: string;
  rows: CompareRow[];
  concordance: string;
  synthesis: string;
  codex_limit?: boolean;
  codex_tokens?: Record<string, number>;
}

// Analyse critique en SSE (codex ~1 min → keep-alives, comme la recherche v2) :
// émet le déroulé via onLog puis onResult (forme CompareResult).
export function analyzeCompareStream(
  query: string,
  pmids: number[],
  handlers: {
    onLog: (log: PubmedLog) => void;
    onResult: (res: CompareResult) => void;
    onError: (msg?: string) => void;
  },
): EventSource {
  const sp = new URLSearchParams({ query, pmids: pmids.join(",") });
  const es = new EventSource(`${API_BASE}/analyze/compare/stream?${sp.toString()}`);
  es.addEventListener("log", (e) => {
    try {
      handlers.onLog(JSON.parse((e as MessageEvent).data));
    } catch {
      /* ignore une ligne malformée */
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
      throw new Error("Limite d'usage GPT-5.6 atteinte — réessayez plus tard.");
    throw new Error(`Erreur API (${res.status})`);
  }
  return res.json();
}

// Traduit FR un lot d'articles en un seul appel (bascule d'une vue en français).
// Sert le cache côté API et ne traduit que ce qui manque. La map renvoyée est
// indexée par PMID (string) ; un PMID sans traduction possible y est simplement absent.
export interface TranslateBatchItem {
  pmid: number;
  title?: string | null;
  abstract?: string | null;
}

export async function translateBatch(
  items: TranslateBatchItem[],
): Promise<Record<string, TranslationResult>> {
  const res = await fetch(`${API_BASE}/translate/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    if (res.status === 429)
      throw new Error("Limite d'usage GPT-5.6 atteinte — réessayez plus tard.");
    throw new Error(`Erreur API (${res.status})`);
  }
  const data = await res.json();
  return data.translations ?? {};
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
// Mon profil, en LECTURE PURE : null si aucun médecin rattaché au compte (404).
// Ne crée jamais rien — le rattachement (bootstrap) est réservé à la page
// Profil ; visiter une page qui lit le profil ne doit pas écrire en base.
export async function getMe(): Promise<Doctor | null> {
  const res = await fetch(`${API_BASE}/me`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}
// Mon profil : le médecin rattaché au compte Google connecté (identité posée
// par proxy.ts dans les headers, rien à envoyer côté client).
export async function bootstrapMe(): Promise<Doctor> {
  const res = await fetch(`${API_BASE}/me/bootstrap`, { method: "POST" });
  if (!res.ok) throw new Error(`Erreur API (${res.status})`);
  return res.json();
}
export async function updateMyProfile(profile: DoctorProfile): Promise<Doctor> {
  const res = await fetch(`${API_BASE}/me/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
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
// Le tri (sélecteur « TRI ») fait partie de l'identité de la recherche : la même
// question peut être sauvegardée une fois en v1 et une fois en v2, chacune
// retrouvée par son propre tri.
export type SearchSort = "v1" | "v2";

// Libellés du tri, identiques à ceux du sélecteur « TRI » de l'accueil. Ici
// plutôt que dans une page : accueil, liste et lien partagé les affichent tous.
export const SORT_LABEL: Record<SearchSort, string> = {
  v1: "tri v1 · score IA",
  v2: "tri v2 · fusion RRF",
};

// Tri d'une recherche sauvegardée, prêt à afficher. Les lignes d'avant le champ
// n'en portent pas : on n'invente rien et on n'affiche alors aucune étiquette.
export function sortLabel(sort: SearchSort | string | null | undefined): string | null {
  return sort === "v1" || sort === "v2" ? SORT_LABEL[sort] : null;
}

export interface SavedSearchSummary {
  id: string;
  doctor_id: string | null;
  doctor_name: string | null;
  query: string;
  method: string;
  sort: SearchSort | null; // null = sauvegardée avant l'ajout du tri
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
  sort?: SearchSort;
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
// un snapshot identique a déjà été sauvegardé — même question, mêmes dates ET
// même tri. Renvoie le plus récent, ou null.
export async function lookupSavedSearch(params: {
  query: string;
  method?: string;
  date_from?: string;
  date_to?: string;
  sort?: SearchSort;
}): Promise<SavedSearchDetail | null> {
  const sp = new URLSearchParams({ query: params.query, method: params.method ?? "v2" });
  if (params.date_from) sp.set("date_from", params.date_from);
  if (params.date_to) sp.set("date_to", params.date_to);
  if (params.sort) sp.set("sort", params.sort);
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
