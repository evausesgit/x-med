# Communication — Comment fonctionne la recherche X-Med

Deux messages prêts à l'emploi. Ils expliquent d'abord les **deux types de recherche**
proposés au médecin (barre « MÉTHODE »), puis, pour la recherche PubMed + IA, ses **deux
sources** (PubMed en direct + base locale). Détail technique complet et fidèle au code :
voir [`ALGO_RECHERCHE.md`](../ALGO_RECHERCHE.md).

> Rappel des méthodes de l'UI : **PubMed + IA** et **Par sens** sont les deux types
> principaux ; **Mots-clés / MeSH** est une option experte (recherche manuelle par tags),
> mentionnée en fin de message.

---

## 1. Message pour les médecins (non technique)

**Les deux façons de chercher dans X-Med**

Vous choisissez votre méthode en haut de la page (« MÉTHODE ») :

**① PubMed + IA — la recherche approfondie (~1 minute)**
Vous posez votre question en français. X-Med interroge **deux bibliothèques en même
temps** :
- **PubMed en direct** — la base mondiale de référence, en temps réel (les toutes
  dernières publications, où qu'elles soient) ;
- **notre bibliothèque interne** — une copie de PubMed hébergée chez nous,
  **~25 millions d'articles**, interrogée en une fraction de seconde.

On **réunit les résultats des deux**, puis une **IA lit réellement le résumé de chaque
article** et note sa pertinence (de « hors sujet » à « très pertinent »). Vous ne voyez
que les articles pertinents, du plus au moins. C'est la méthode la plus complète : la
seule où l'IA *lit* vraiment les articles.

**② Par sens — la recherche instantanée**
X-Med comprend le **sens** de votre question plutôt que les mots exacts, et retrouve
immédiatement les articles proches — même formulés autrement (« crise cardiaque » retrouve
« infarctus du myocarde »). **Pas d'attente**, mais elle cherche uniquement dans notre
bibliothèque interne (pas de lecture par l'IA, pas de PubMed en direct). Idéale pour
explorer vite ou quand vous ne connaissez pas le terme médical exact.

**En résumé :** *PubMed + IA* quand vous voulez le **meilleur tri, exhaustif et à jour**
(vous avez ~1 min) ; *Par sens* quand vous voulez une **réponse immédiate** par proximité
de sens.

*(Une troisième option, « Mots-clés / MeSH », permet une recherche manuelle par
mots-clés et étiquettes médicales officielles, pour les usages experts.)*

**Bon à savoir (PubMed + IA) :** sur un sujet **très large** (ex. « saignements »), notre
bibliothèque interne renverrait des centaines de milliers d'articles ; dans ce cas on
privilégie PubMed en direct pour rester rapide. Sur un sujet **précis**, les deux sources
sont exploitées à fond.

---

## 2. Message pour l'associé (technique)

X-Med expose **deux types de recherche principaux** (+ une recherche MeSH manuelle) :

### Type 1 — Recherche sémantique (« Par sens ») · `/search/semantic`
- **Un seul appel, instantané, pas d'IA générative.** On encode la question en vecteur
  (**embeddings bge-m3**), puis plus proches voisins par **distance cosinus** (pgvector
  `<=>`, index **HNSW**).
- **Périmètre = base locale uniquement** (table `embeddings_<modèle>`), pas de PubMed live.
- **Limite** : ne couvre que les articles **déjà embeddés** (embedding ~1 doc/s → pas tout
  le corpus ; bge-m3 couvre 2025-2026). Seuils de pertinence provisoires (à caler sur le
  gold set annoté).
- **Force** : rattrape synonymes cliniques, franco-anglais, reformulations là où le
  lexical échoue.

### Type 2 — Recherche PubMed + IA (« deep ») · `/search/pubmed/deep`
3 temps, **2 sources en parallèle**, puis jugement Codex.

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

### Type 3 (expert) — Mots-clés / MeSH · `/search/mesh`
Recherche manuelle par descripteurs MeSH (ET/OU) + plein-texte optionnel + filtres
(année, niveau de preuve). Instantané, pas d'IA.

**Question de fond ouverte** (à trancher ensemble) : pour accélérer *aussi* les sujets
larges de la recherche PubMed + IA sans garde-fou → **RUM index** (FTS classé par l'index,
garde la sémantique lexicale) vs **pgvector/HNSW** (sémantique, l'archi cible de
`PIPELINE_EMBEDDINGS.md`, mais embeddings à compléter sur 25 M docs et qualité à valider).

Détail complet fidèle au code : `ALGO_RECHERCHE.md`. Commits : `0fabd6b` (code), `62fdd0c` (doc).
