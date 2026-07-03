# Communication — Comment fonctionne la recherche X-Med

Deux messages prêts à l'emploi expliquant le fonctionnement de la recherche PubMed + IA,
et en particulier ses **deux sources** (PubMed en direct + base locale). Détail technique
complet et fidèle au code : voir [`ALGO_RECHERCHE.md`](../ALGO_RECHERCHE.md).

---

## 1. Message pour les médecins (non technique)

**Comment X-Med cherche vos articles**

Quand vous lancez une recherche, X-Med interroge **deux bibliothèques en même temps** :

1. **PubMed en direct** — la base mondiale de référence, en temps réel. On y capte les
   toutes dernières publications, où qu'elles soient.
2. **Notre bibliothèque interne** — une copie de PubMed hébergée chez nous,
   **~25 millions d'articles**, que l'on interroge en une fraction de seconde.

On **réunit les résultats des deux**, puis une **IA lit réellement le résumé de chaque
article** et note sa pertinence par rapport à votre question (de « hors sujet » à « très
pertinent »). Vous ne voyez que les articles jugés pertinents, du plus au moins.

Deux choses à savoir :

- Une recherche prend **~1 minute** : l'essentiel du temps, c'est l'IA qui *lit* les
  articles (pas une simple liste de mots-clés).
- Sur un **sujet très large** (ex. « saignements »), notre bibliothèque interne renverrait
  des centaines de milliers d'articles : dans ce cas on privilégie PubMed en direct pour
  rester rapide. Pour un sujet **précis**, les deux sources sont exploitées à fond.

Résultat : la **fraîcheur** de PubMed + la **rapidité** de notre base + un **tri par une IA
qui a vraiment lu** les articles.

---

## 2. Message pour l'associé (technique)

**Recherche PubMed + IA — les deux sources et leurs limites**

Une recherche (`/search/pubmed/deep`) tourne en 3 temps et interroge **2 sources en
parallèle** avant un jugement Codex.

**Temps 1 — requête + 2 viviers**
- Codex (GPT-5.4) traduit la question FR en requête PubMed experte (MeSH + synonymes +
  molécules). *Timeout 180 s*, sinon repli sur la question brute.
- **Source A = PubMed live** (E-utilities `esearch`, tri Best Match, filtre `pdat`).
  `k_pubmed = 20`. Échec esearch = **502** (seul cas qui stoppe tout).
- **Source B = base locale** = notre miroir Postgres, **~25 M articles / 63 Go**.
  Pré-filtre **plein-texte FTS** (index GIN, tri `ts_rank`), `max_local ≤ 200`.

**Temps 2 — fusion A∪B**, dédup, récupération des résumés manquants (`esummary`/`efetch`,
best-effort).

**Temps 3 — jugement** : Codex lit `judge_batch = 50` résumés (tronqués à 1200 car.), note
0–3, on garde `≥ min_score = 2`, tri final **toujours par score Codex**. *Timeout jugement
420 s* → sinon `skipped` (tri lexical, pas de score).

**Ce qu'on vient de corriger (base passée de 2,3 M à 25 M) :**
- Le pré-filtre local combinait `FTS OR mesh_terms && ARRAY[...]`. Un descripteur MeSH
  courant (« Heart Failure ») matche des millions de lignes → tri `ts_rank` à **206 s** sur
  la même requête. **Passé en FTS seul → 0,4 s.** (mesh reste utilisé pour la requête PubMed.)
- **Garde-fou** : requête locale bornée à **8 s** (`statement_timeout` dans un savepoint) ;
  au-delà (mots ultra-courants, lents même en FTS seul → mesuré jusqu'à ~493 s), on
  abandonne le vivier local et on continue sur PubMed. Message `filter_timeout`.
- **Tuning Postgres** (`docker-compose.yml`) : `shared_buffers` 128 Mo → **8 Go**,
  `work_mem` 64 Mo, `effective_cache_size` 24 Go, `random_page_cost` 1.1, index FTS (5,7 Go)
  préchauffé via `pg_prewarm`. Requête étroite : **13 s à froid → 0,4 s**.
- Message `filter_start` émis **avant** la requête locale (plus d'écran figé).

**Mesuré, e2e :** SGLT2/HFpEF → local 0,5 s, 150 candidats ; sujet large → coupé à ~9 s,
repli PubMed, 14 articles retenus.

**Question de fond ouverte** (à trancher ensemble) : pour accélérer *aussi* les sujets
larges sans garde-fou → **RUM index** (FTS classé par l'index, garde la sémantique lexicale)
vs **pgvector/HNSW** (sémantique, l'archi cible de `PIPELINE_EMBEDDINGS.md`, mais embeddings
à compléter sur 25 M docs et qualité à valider).

Détail complet fidèle au code : `ALGO_RECHERCHE.md`. Commits : `0fabd6b` (code), `62fdd0c` (doc).
