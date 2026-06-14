# X-Med — Plan de recherche PubMed avec Codex

> Recherche en deux sources (PubMed live + base locale), fusionnées et jugées par
> un LLM (Codex / GPT-5.4). Objectif : **rappel maximal** (PubMed) + **tri fiable
> par lecture réelle des abstracts** (Codex), sans dépendre du pré-tri sémantique
> par embeddings qui s'est révélé peu cohérent (voir § Pourquoi pas pgvector).

## Entrées

- `PRM` : phrase recherchée du médecin (en français).
- `st` : date de début de la fenêtre de publication.
- `ed` : date de fin de la fenêtre de publication.

## Principe

L'étape 1 (GPT-5.4) ne fait qu'**une** chose : transformer `PRM` en une requête
structurée — *mots-clés anglais + synonymes + termes MeSH*. Cette requête sert
**deux fois** :

- envoyée aux serveurs **PubMed** → liste `A` (rappel sur le monde entier) ;
- rejouée sur **notre base locale** (filtre lexical + MeSH) → un petit lot de
  candidats que **Codex lit vraiment** pour juger la pertinence → liste `B`.

Les deux sont complémentaires :

| | `A` — PubMed (serveurs NIH) | `B` — base locale |
|---|---|---|
| Couvre | tout PubMed | seulement ce qu'on a déjà ingéré |
| Apporte | les nouveautés, le rappel | l'abstract complet, lisible par Codex |
| On récupère | liens + métadonnées | le texte intégral, sous la main |

## Algorithme

### Étape 1 — `PRM` → requête structurée → `A`

GPT-5.4 transforme `PRM` en `{pubmed_query, mesh_terms, keywords_en}` (déjà codé :
`app/services/query_builder.py`). PubMed exécute `pubmed_query` sur la fenêtre
`st`–`ed` et retourne une liste de liens → `A` (déjà codé : `esearch` avec
`mindate`/`maxdate`).

Pour que Codex puisse plus tard **juger** les articles de `A` qui ne sont pas
encore dans notre base, on récupère leur abstract manquant via PubMed `efetch`
(**à ajouter** : aujourd'hui on ne fait qu'`esummary`, qui ne donne pas l'abstract).

### Étape 2 — recherche locale filtrée → lecture Codex → `B`

On rejoue la **même requête** (les `keywords_en` + `mesh_terms` de l'étape 1) sur
notre base, sans LLM :

- **filtre plein-texte** : `fts @@ websearch_to_tsquery('english', keywords_en)` ;
- **filtre MeSH** : recoupement d'étiquettes `mesh_terms && article.mesh_terms` ;
- borné à la fenêtre `st`–`ed`.

Ce filtre **dégrossit** le corpus (ex. 59 763 abstracts 2025+ → ~20 à ~400
candidats), en ne gardant que ceux qui contiennent les bons mots — et en
**respectant les contraintes cliniques fines** (ex. « preserved ejection
fraction ») que le sémantique ratait.

Codex lit ensuite **ces candidats** (et eux seuls) :

- compare sémantiquement chaque abstract à `PRM` (proximité de sens et pertinence
  médicale, même si les termes diffèrent) ;
- attribue un score de pertinence selon une grille commune (à définir, voir
  § Décisions ouvertes) ;
- conserve les articles cohérents avec `PRM`.

Le lot étant borné (≤ quelques centaines), il tient dans **1 appel Codex** quelle
que soit la largeur de la fenêtre — c'est le *nombre de mots-clés* qui borne, pas
la date. Découper en plusieurs lots seulement si le filtre rend un lot trop gros
pour la fenêtre de contexte. → `B`.

### Étape 3 — fusion et classement → `C`

Fusionner `A + B`, puis **dédupliquer par PMID** (un article récent peut être dans
les deux).

Codex vérifie la cohérence des articles avec `PRM` (sur l'abstract — d'où l'`efetch`
de l'étape 1 pour les articles de `A`), puis on classe selon, dans l'ordre :

1. la **pertinence** (score Codex) ;
2. la **qualité scientifique** — réutiliser `evidence_level` (1–4), déjà calculé au
   parsing ; pas d'appel LLM pour ce critère ;
3. la **récence** (date de publication, plus récent d'abord).

→ `C`.

### Étape 4 — production finale

Pour les meilleurs articles de `C` **uniquement** (jamais sur `A + B` brut, pour
maîtriser le coût LLM) :

- traduire (FR) — table `article_fr` déjà en place pour le cache ;
- résumer ;
- évaluer la qualité (appraisal) ;
- créer un contenu **vocal** (TTS — moteur et format à spécifier plus tard).

## Vue synthétique

```text
PRM + st→ed
   │  étape 1 : GPT-5.4 → keywords_en + mesh_terms
   │
   ├── PubMed (NIH) ───────────────→ A : liens récents/exhaustifs
   │                                     (efetch des abstracts manquants)
   │
   └── base locale (FTS + MeSH) ──→ candidats bornés ──→ Codex lit & juge ──→ B
                                                                              │
                              A + B ─→ dédup PMID ─→ Codex juge cohérence
                                       tri : pertinence → qualité → récence ─→ C
                                                                              │
                          (meilleurs de C)  traduction → résumé → qualité → vocal
```

## Pourquoi pas le pré-tri pgvector (embeddings)

On dispose de 313 880 embeddings `bge_m3` (couverture quasi-totale 2025–2026),
mais utilisés en **pré-tri**, ils donnent un rappel/précision insuffisants :

- ils attrapent le *thème général* mais **ratent les contraintes cliniques fines**
  (ex. requête « HFpEF » → aucun résultat spécifiquement HFpEF dans le top-8) ;
- ils **dérivent** sur les requêtes courtes/familières (« ozempic perte de poids »
  → oxytocine, antipsychotiques, oxcarbazépine dans le top-6) ;
- les scores cosinus sont **tassés** (~0,57–0,72) → pas de seuil de coupure net.

Mettre ce filtre en amont **jetterait des articles pertinents avant que Codex les
voie** (perte de rappel). L'expansion de requête de l'étape 1 (GPT-5.4 → mots-clés
EN + synonymes + MeSH) résout le même problème (franco-anglais, synonymes) **au
niveau de la requête**, de façon déterministe et débogable.

→ Les embeddings restent une fonctionnalité **secondaire** (panneau « plus comme
ceux-ci » / voisins), **hors du chemin critique** de la recherche.

## Contraintes de coût (cf. `CLAUDE.md`)

- Pré-filtre (lexical + MeSH) **avant tout appel LLM** : Codex ne lit jamais le
  corpus brut, seulement les candidats filtrés.
- Étape 4 (trad/résumé/appraisal/vocal) **seulement sur les meilleurs de `C`**.
- Réutiliser ce qui est déjà calculé (`evidence_level`, cache `article_fr`).

## Alignement avec le code existant

| Étape | État | Fichier |
|---|---|---|
| 1 — requête structurée | ✅ codé | `app/services/query_builder.py` |
| 1 — `esearch` PubMed (`st`/`ed`) | ✅ codé | `app/services/pubmed_eutils.py`, `app/api/search.py` (`/search/pubmed`) |
| 1 — `efetch` abstracts de `A` | ⚠️ à ajouter | `app/services/pubmed_eutils.py` |
| 2 — filtre local FTS + MeSH | ⚠️ partiel (FTS via `/search`, MeSH via `/search/mesh`) à combiner pour `B` | `app/api/search.py` |
| 2 — lecture/scoring Codex des candidats | 🆕 nouveau | nouveau service |
| 3 — fusion + dédup + tri | 🆕 nouveau | `app/api/search.py` |
| 4 — trad/résumé/appraisal | 🟡 partiel (`article_fr`) ; rejoint `tasks/ai_enrichment.py` | |
| 4 — vocal (TTS) | 🆕 nouveau | à spécifier |

## Décisions ouvertes

- **Grille de score de pertinence** Codex : échelle (0–1 ? 0–3 ?) et critères.
- **Réconciliation du tri** entre rang PubMed de `A` et score Codex de `B` à la
  fusion.
- **Live vs async** : ce pipeline complet (jusqu'au vocal) dure plusieurs minutes
  → soit il remplace la recherche interactive, soit c'est un flux « veille
  approfondie » lancé en tâche de fond. À trancher.
- **Moteur vocal** (TTS) et format (langue, voix, durée).
