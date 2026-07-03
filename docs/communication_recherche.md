# Communication — La recherche PubMed + IA (v1 / v2)

Deux messages prêts à l'emploi sur **la recherche PubMed + IA** (la méthode où l'IA *lit*
et note chaque article). Elle existe en **deux versions**, choisies via le sélecteur
« TRI » : **v1 · score IA** (défaut) et **v2 · fusion RRF**. Détail fidèle au code :
[`ALGO_RECHERCHE.md`](../ALGO_RECHERCHE.md).

---

## 1. Message pour les médecins (non technique)

**Comment fonctionne la recherche PubMed + IA**

Vous posez votre question en français. X-Med interroge **deux bibliothèques en même
temps** — **PubMed en direct** (la base mondiale, temps réel) et **notre copie locale**
(~25 millions d'articles, très rapide) — puis une **IA lit réellement le résumé de chaque
article** et note sa pertinence (« hors sujet » → « très pertinent »). Vous ne voyez que
les articles pertinents, classés du plus au moins. Comptez **~30 à 90 secondes** : le
temps que l'IA *lise* les articles.

**Deux versions, selon ce que vous cherchez :**

- **v1 — « score IA » (par défaut)** : rapide et ciblée. On prend une **petite tête de
  liste PubMed** (les plus pertinents) complétée par notre base, et l'IA note. Idéale au
  quotidien.
- **v2 — « fusion équilibrée »** : plus large. On élargit à **~100 articles PubMed** et on
  **mélange équitablement** PubMed et notre base, pour ne pas passer à côté d'un bon
  article présent uniquement chez nous (près de **4 sur 10** des articles pertinents en
  viennent). Un curseur permet de garantir un minimum d'articles issus de notre base. À
  privilégier pour une recherche **exhaustive**.

Dans les deux cas, **le classement final est celui de l'IA** (sa note de pertinence). Si
vous voulez plus de résultats, le bouton **« Analyser 50 de plus »** fait lire un lot
supplémentaire à l'IA.

---

## 2. Message pour l'associé (technique)

**Recherche PubMed + IA — `/search/pubmed/deep` — v1 vs v2, contraintes**

Pipeline en 3 temps, **2 sources en parallèle** (A = PubMed live E-utilities · B = base
locale Postgres, **~25 M articles / 63 Go**), puis jugement Codex. Les deux versions ne
changent QUE la **sélection des candidats à faire juger** ; le **tri final est toujours le
score Codex**.

### Nombre d'articles à chaque étape

| Étape | v1 · score IA (défaut) | v2 · fusion RRF |
|---|---|---|
| **A — PubMed live** (`k_pubmed`) | **12** | **100** |
| **B — base locale** (`max_local`) | ≤ **200** | ≤ **200** |
| **Fusion des candidats** | A **puis** B (PubMed d'abord, local en filet) | **RRF** (rang réciproque) des 2 listes → le local n'est pas enterré |
| **Plancher local garanti** (`local_floor`) | 0 | **réglable** (curseur, 0 par défaut) |
| **Lus/notés par l'IA / lot** (`judge_batch`) | **50** (fixe) | **50**, réglable **20–100** (curseur) |
| **Seuil de conservation** (`min_score`) | ≥ **2** / 3 | ≥ **2** / 3 |
| **« Analyser 50 de plus »** | +1 lot de 50 | +1 lot de `judge_batch` |

> Rappel : ~**39 %** des articles jugés pertinents viennent du **local seul** → d'où la
> fusion RRF de v2 pour ne pas laisser PubMed monopoliser le lot des 50 jugés.

### Temps & timeouts

| Poste | Valeur | Au-delà |
|---|---|---|
| **Durée typique d'une recherche** | **30–90 s** (souvent ~1 min) | UI : « un peu plus long » > 90 s, « recherche longue » > 180 s |
| Construction requête (Codex GPT-5.4) | timeout **180 s** | repli « requête brute » |
| `esearch` PubMed (source A) | dépend de NCBI | échec → **502** (stoppe tout) |
| **Requête base locale (source B)** | **≤ 8 s** (`statement_timeout`) | B = ∅, repli PubMed (`filter_timeout`) |
| `esummary`/`efetch` (résumés manquants) | best-effort | dégrade (titre/résumé absents), pas de 500 |
| Jugement (Codex) | timeout **420 s** | repli `skipped` (pas de score, tri lexical) |
| Keep-alive SSE | toutes les **10 s** | évite la coupure proxy pendant le silence du jugement |
| Base locale (perf) | **~0,4–0,5 s** (requête normale) | 25 M lignes ; ~13 s à froid sans le tuning Postgres |

### Contraintes techniques

- **2 appels Codex** par recherche initiale (1 requête + 1 jugement de 50) ; chaque
  « 50 de plus » = **+1 appel** jugement. Prompt profil mis en cache.
- **Abstract tronqué à 1200 caractères** avant envoi au juge (tient dans un seul appel).
- **Source B = FTS seul** (index GIN, tri `ts_rank`). Le `OR mesh_terms && ARRAY[...]` a
  été retiré : un descripteur MeSH courant (« Heart Failure ») faisait passer la même
  requête de 0,4 s à **206 s**. `mesh_terms` ne sert plus qu'à la requête PubMed.
- **Garde-fou local 8 s** (mesuré jusqu'à ~493 s sur mots ultra-courants même en FTS seul).
- **Infra Postgres** (indispensable à l'échelle) : `shared_buffers` 128 Mo → **8 Go**,
  `work_mem` 64 Mo, `effective_cache_size` 24 Go, `random_page_cost` 1.1, index FTS (5,7 Go)
  préchauffé (`pg_prewarm`).
- **Streaming SSE** (`/search/pubmed/deep/stream`) : déroulé en direct (`codex` →
  `esearch` → `filter_start` → `filter`|`filter_timeout` → `judge` → `done` → `translate`).

**Mesuré, e2e :** SGLT2/HFpEF → local 0,5 s, 150 candidats, 15 retenus ; sujet large →
coupé à ~9 s, repli PubMed, 14 retenus.

**Question de fond ouverte** : accélérer *aussi* les sujets larges sans garde-fou →
**RUM index** (FTS classé par l'index) vs **pgvector/HNSW** (sémantique, archi cible de
`PIPELINE_EMBEDDINGS.md`, embeddings à compléter sur 25 M docs).

Détail complet fidèle au code : `ALGO_RECHERCHE.md`. Commits : `0fabd6b` (code), `62fdd0c` (doc).
