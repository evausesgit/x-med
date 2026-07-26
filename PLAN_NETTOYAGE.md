# Plan de nettoyage — retrait des chantiers abandonnés

> **Statut : proposition, non exécutée.** Ce document décrit ce qui sera supprimé,
> dans quel ordre, et quels tests écrire **avant** de toucher au code.
> Rien n'a encore été modifié dans le code applicatif.
>
> Document jumeau : [`PLAN_BASES_SEPAREES.md`](PLAN_BASES_SEPAREES.md) — la séparation
> en deux bases de données, à faire **après** ce nettoyage.

## Pourquoi

Quatre chantiers datent des débuts du projet et ne servent plus :

| Chantier | Ce que c'était | Pourquoi ça part |
|---|---|---|
| **Embeddings** (2 modèles : bge-m3, MedCPT) | pré-tri sémantique du corpus par vecteurs pgvector | jugé peu cohérent en pratique ; la recherche v2 (lexical + MeSH → codex juge) ne s'en sert pas |
| **Page Vectorisation** (`/embeddings`) | suivi de l'avancement du job de vectorisation | sans objet une fois les embeddings retirés |
| **Évaluation** (`/evaluation`, benchmarks) | leaderboard de comparaison des modèles d'embedding | mesurait des modèles qu'on ne garde pas |
| **Annotation** (`/annotate`, gold set) | notation manuelle de la pertinence par des médecins | **0 annotation saisie à ce jour** — le chantier n'a jamais démarré |

Gain attendu : **~1 500 lignes de code en moins**, **4,3 Go de base récupérés**, et
**torch retiré de l'image Docker de l'API** (plusieurs centaines de Mo).

## Contrainte absolue : la recherche ne doit pas bouger

`app/api/search.py` (1 633 lignes) est le cœur du produit. Il doit continuer à
fonctionner **dans ses deux modes**, qui sont deux réglages du même endpoint
`POST /search/pubmed/deep` :

- **v1 « score IA »** — `rrf=false`, `k_pubmed=20`, `local_floor=0`
- **v2 « fusion RRF »** — `rrf=true`, `k_pubmed=50`, tri des candidats par rang réciproque

### Vérification faite avant d'écrire ce plan

Les embeddings **ne sont pas sur le chemin de la recherche**. C'est écrit dans le code
(`search.py:425` : *« Les embeddings ne sont PAS sur le chemin critique (pré-tri
pgvector peu cohérent) »*) et **vérifié fonction par fonction** : ni `_run_deep_search`
ni `_run_deep_more` n'appellent `get_model`, `_embed_query` ou les tables `emb_*`.

Le seul point d'attention est `_fetch_articles` (`search.py:285`), un helper partagé :
il est utilisé par les endpoints supprimés **et** par le chemin deep (lignes 741 et 959).
**Il est conservé.** C'est le piège classique de ce genre de nettoyage.

Concrètement, dans `search.py` tout ce qui part est confiné aux **lignes ~115 à 414**.
**Rien en dessous de la ligne 419 n'est touché.**

---

# Étape 0 — Les tests, AVANT tout le reste

Le principe : on écrit les tests sur le code **actuel** et on vérifie qu'ils sont
**verts avant** de toucher à quoi que ce soit. Un test écrit après le nettoyage ne
prouve rien — il décrit le code déjà cassé. Écrit avant, il devient un contrat :
« voilà ce que la recherche fait aujourd'hui, elle doit faire pareil demain ».

Le projet a déjà 4 tests (`test_digest_query`, `test_explainability`,
`test_search_notifications`, `test_window_keep`) qui ne touchent à rien de supprimé :
ils doivent rester verts de bout en bout.

**Lancer la suite :** `uv run --group dev pytest -q` → **54 tests, ~3 s.**
*(le projet n'est pas installé comme paquet dans le venv ; `[tool.pytest.ini_options]`
dans `pyproject.toml` ajoute la racine au `pythonpath` pour que `import app` marche.)*

**État : l'étape 0 est terminée.** Les quatre tests sont écrits et verts sur le code
**d'avant** nettoyage. C'est le point de référence : après chaque lot, la même commande
doit redonner 54 verts.

### Test 1 — Inventaire des routes (`tests/test_api_surface.py`) — ✅ **écrit, vert**

On importe `app.main` et on vérifie que les endpoints qui doivent survivre sont
toujours là :

```python
CORE_ROUTES = {
    ("POST", "/search/pubmed/deep"),
    ("POST", "/search/pubmed/deep/more"),
    ("GET",  "/search/pubmed/deep/more/stream"),
    ("POST", "/search/pubmed/deep/stop/{token}"),
    ("POST", "/search/local/stop/{token}"),
    ("POST", "/translate"), ("POST", "/translate/batch"),
    ("POST", "/analyze/compare"), ("GET", "/analyze/compare/stream"),
    ("GET",  "/articles/{pmid}"),
    # + /saved-searches, /search/runs, /digest, /doctors, /me
}

def test_core_routes_still_exist():
    got = {(m, r.path) for r in app.routes for m in getattr(r, "methods", [])}
    assert CORE_ROUTES <= got
```

**Attrape** : une route supprimée par erreur, ou `app/main.py` qui ne s'importe plus
après le retrait du routeur `eval`.
**Coût** : ~30 min. Pas de base, pas de réseau, s'exécute en 0,2 s.

Le test écrit va un cran plus loin que le croquis : il fige **32 routes du cœur** et
ajoute un garde-fou inverse (`test_no_unexpected_route_appeared`) — toute route hors du
cœur doit figurer dans la liste des routes explicitement destinées à disparaître. Une
route inattendue fait donc échouer le test, ce qui évite qu'un endpoint mort réapparaisse
en douce.

### Test 2 — Contrat de réponse, sur de vraies données (`tests/test_deep_search_contract.py`) — ✅ **écrit, vert**

La base contient **42 recherches sauvegardées** dont le champ `payload` (jsonb) est une
vraie réponse v2 complète. On en fige 2 ou 3 dans `tests/fixtures/` et on vérifie
qu'elles se relisent toujours :

```python
def test_saved_snapshot_still_parses():
    payload = json.loads(FIXTURE.read_text())
    resp = DeepSearchResponse.model_validate(payload)   # ne doit pas lever
    assert resp.hits and resp.hits[0].score is not None
```

**Attrape** : toute modification du format de réponse. Double intérêt — si le contrat
change, ce ne sont pas seulement les tests qui cassent, ce sont les **42 recherches
sauvegardées des utilisateurs** qui deviennent illisibles sur `/recherches`.
**Coût** : ~30 min.

Trois fixtures figées dans `tests/fixtures/`, choisies pour couvrir des générations
différentes du format : `deep_v2_vismodegib` (14 résultats, `counts` complet avec
`kept_pubmed`/`kept_local`/`kept_both`), `deep_v2_translated` (6 résultats, traductions
FR présentes), `deep_v2_single_hit` (1 résultat, `counts` d'ancienne génération, sans
`judgeable`). Quatre tests : relecture dans le modèle, champs d'affichage, aller-retour
sans perte de champ ni changement d'ordre, et préservation des traductions FR.

**Deux constats relevés en écrivant ce test**, qui n'étaient pas dans le plan initial :

- **les 42 snapshots en base sont tous en méthode v2** — aucune recherche v1 n'a jamais
  été sauvegardée. Ce test ne peut donc pas distinguer v1 de v2. Ce n'est pas grave (le
  format de réponse est le *même objet* `DeepSearchResponse` dans les deux modes, seule
  la sélection des candidats diffère), mais ça confirme que **le test 3 est le seul à
  couvrir vraiment la différence v1/v2** ;
- **`relevance_pct` est absent de 201 des 444 résultats sauvegardés** (le champ est plus
  récent que `score`). Il doit rester facultatif dans le modèle : le rendre obligatoire
  casserait la moitié des recherches sauvegardées. C'est exactement le genre de piège que
  ce test existe pour attraper — il l'a attrapé dès la première exécution.

### Test 3 — La logique v1 vs v2 (`tests/test_deep_search_selection.py`) — ✅ **écrit, vert**

C'est le seul test qui **demande de modifier `search.py`**. La fusion RRF était écrite
en ligne au milieu d'une fonction de 350 lignes : impossible à tester isolément.

Deux fonctions pures ont été extraites — **code déplacé tel quel**, sans base ni réseau :

```python
def _candidate_order(a_pmids, local_pmids, rrf, k=60) -> list[int]      # search.py:577
def _pick_judge_batch(judgeable, pubmed_pmids, batch_n, floor)          # search.py:606
```

`_candidate_order` prend le paramètre `rrf` et couvre donc les **deux** modes dans une
seule fonction : c'est littéralement le point où v1 et v2 divergent, et le reste du
pipeline est commun. (Le plan initial parlait d'un `_rrf_order` limité à v2 ; couvrir les
deux modes au même endroit rend la différence testable directement.)

**13 tests** : v1 conserve l'ordre « PubMed d'abord » ; v2 fait remonter l'article bien
classé des deux côtés ; **v1 et v2 rendent des ordres différents sur la même entrée** —
l'assertion qui compte, celle qui échouerait si la fusion était neutralisée ; stabilité
du tri sur les scores ex æquo ; déduplication ; listes vides ; et pour le plancher :
réservation effective de N places locales, ordre du vivier préservé, plancher borné par
la taille du lot, cas « pas assez de locaux », et un balayage `batch_n` × `floor` qui
vérifie qu'aucun lot ne déborde ni ne contient de doublon.

**Preuve que l'extraction n'a rien changé** : l'ancienne implémentation (reprise depuis
`git show`) et la nouvelle ont été comparées sur des entrées aléatoires —
**40 000 comparaisons d'ordre et 500 000 comparaisons de lot, 0 divergence**.

Fait en **commit séparé**, avant tout retrait de code, pour qu'un éventuel problème sur
le fichier sensible soit immédiatement attribuable.

**Coût** : ~45 min.

### Test 4 — Bout en bout avec doublures (`tests/test_deep_search_smoke.py`) — ✅ **écrit, vert**

`_run_deep_search` fait ses imports **à l'intérieur** de la fonction : les trois appels
externes sont donc faciles à remplacer par des doublures — le constructeur de requête
GPT-5.6, PubMed E-utilities, et le juge codex. On lance ensuite la vraie fonction en v1
puis en v2 contre la base de dev.

**Attrape** : tout le reste — le pré-filtre FTS, le routage `articles` / `article_search`,
la fenêtre de dates, l'assemblage de la réponse. C'est le test le plus proche du réel.
**Contrainte** : nécessite Postgres (`skip` automatique sinon). **Coût** : ~1 h.

**12 tests, 3,8 s.** Le chemin nominal (le pipeline tourne, le pré-filtre local trouve
des candidats, le tri final reste le score du juge, la fenêtre de dates est respectée,
les sources `pubmed`/`local`/`both` sont correctement étiquetées, `remaining` ne
reproposera jamais un article déjà jugé) ; **la différence v1/v2 observée sur ce que le
juge reçoit réellement** ; le plancher `local_floor` vérifié dans le vrai pipeline et
plus seulement en unitaire ; les deux replis (constructeur HS → `fallback` sans vider la
recherche, juge HS → `skipped` en rendant le vivier brut) ; les jalons de progression ;
et le routage `articles` / `article_search` selon la fenêtre.

Deux choix qui rendent le test robuste ailleurs que sur ce poste :

- **aucun PMID n'est codé en dur** : le test interroge la base au démarrage pour se
  constituer deux jeux de candidats sur deux sujets rares et disjoints (`vismodegib`,
  `isthmocele`), et se met en `skip` si le corpus local est trop pauvre ;
- **`esummary` et `efetch_abstracts` sont câblés pour lever une erreur** : si un jour un
  article censé être en base déclenche un aller-retour réseau, le test le dit au lieu de
  le masquer.

### Côté front

Rien à inventer : `npm run build` compile en TypeScript strict, donc **toute référence
à une fonction supprimée de `web/lib/api.ts` fait échouer le build**. C'est déjà un
test de non-régression.

### Ce que ces tests ne verront pas

À dire clairement : aucun de ces tests ne juge la **qualité** des résultats. Ils
vérifient que la mécanique tourne et que les formats tiennent, pas que la recherche
reste pertinente — le classement final dépend de codex. **Un essai manuel v1/v2 sur une
vraie requête clinique reste obligatoire en fin de parcours.**

---

# Étape 1 — Archive de sécurité

Avant tout `DROP`, dump des tables supprimées :

```bash
docker exec x-med-db-1 pg_dump -U xmed -d xmed \
  -t eval_pool -t eval_annotations \
  -t bench_queries -t bench_qrels -t bench_runs -t bench_results \
  > archive_eval_bench_$(date +%F).sql
```

État réel des données concernées (relevé le 2026-07-25) :

| Table | Lignes |
|---|---|
| `eval_annotations` | **0** |
| `eval_pool` | 400 |
| `bench_runs` | 2 |
| `bench_queries` / `bench_qrels` / `bench_results` | 0 |

Aucune saisie humaine n'est perdue : le pool de 400 candidats a été généré
automatiquement, et **aucune annotation médecin n'a jamais été faite**.

Les tables `emb_bge_m3` (4,1 Go) et `emb_medcpt` (120 Mo) ne sont **pas** dumpées :
ce sont des vecteurs recalculables, et 4,2 Go d'archive n'auraient aucune valeur.

---

# Étape 2 — Lot 1 : embeddings

**Fichiers supprimés**

| Fichier | Lignes |
|---|---|
| `app/services/embeddings.py` | 112 |
| `scripts/embed_corpus.py` | 176 |
| `scripts/align_embeddings.py` | 86 |

**Retiré de `app/api/search.py`**

- import `from app.services.embeddings import REGISTRY, get_model` (l. 24)
- constante `DEFAULT_MODEL` (l. 30)
- helpers `_vec_literal` (l. 46) et `_embed_query` (l. 51)
- modèle Pydantic `SemanticSearchRequest`
- endpoints `GET /models`, `GET /embeddings/progress`, `POST /search/semantic`, `GET /search/hybrid`

**Conservé** : `_fetch_articles` (l. 285) — utilisé par le chemin deep.

**Configuration** : `embedding_models` et `embedding_model_list` retirés de `app/config.py`.

**Dépendances — le gain le plus visible**

- `pyproject.toml` : suppression du groupe optionnel `ml` (torch, transformers,
  sentence-transformers, ir-datasets, ranx) et du bloc `[tool.uv]` d'index torch CPU
- `pyproject.toml` : suppression de `pgvector>=0.3.6` des dépendances cœur
  (vérifié : importé uniquement par les deux scripts supprimés)
- `Dockerfile:45` : `uv sync --frozen --no-dev --group ml` → `uv sync --frozen --no-dev`
- `nixpacks.toml` : commentaire l. 18 à mettre à jour

---

# Étape 3 — Lot 2 : évaluation et annotation

**Fichiers supprimés**

| Fichier | Lignes |
|---|---|
| `app/api/eval.py` (4 endpoints) | 156 |
| `app/models/benchmark.py` | 46 |
| `scripts/build_pool.py` | 221 |
| `scripts/run_benchmark.py` | 62 |
| `scripts/bench_selection.py` | 162 |
| `scripts/load_translations.py` | 82 |
| `scripts/refresh_eval_pool.sh` | 54 |
| dossier `bench/` complet | — |

Le dossier `bench/` contient `runner.py`, `datasets.py`, `pubmed_ab.py`, `pool_fr.csv`,
`queries_fr.json`, `GUIDE_ANNOTATION.md` et `translations/`.

**Modifié**

- `app/main.py` : retrait de l'import et du `include_router(eval.router)`
- `app/models/__init__.py` : retrait des 4 entrées `Bench*`
- `app/api/search.py` : retrait de l'endpoint `GET /bench/leaderboard`

---

# Étape 4 — Lot 3 : anciens endpoints de recherche

Hors du périmètre initial, ajoutés après vérification : **plus aucune page du front ne
les appelle** depuis le passage de la page d'accueil en « PubMed + IA » seul.

**Retiré de `app/api/search.py`** : `GET /search/mesh`, `GET /search` (plein-texte),
`GET /mesh/autocomplete`.

> ⚠️ `app/services/explainability.py` est **conservé** (avec son test
> `test_explainability.py`). Après ce lot, `_to_result` et `explain_article` ne servent
> plus qu'à `GET /articles/{pmid}`, qui reste.

---

# Étape 5 — Lot 4 : front

**Pages supprimées** : `web/app/embeddings/` (149 l.), `web/app/evaluation/` (129 l.),
`web/app/annotate/` (212 l.).

**Visite guidée** : `web/public/recherche-guidee/` (page HTML statique).

**`web/app/Nav.tsx`** : 4 entrées retirées du menu « Plus de pages » (lignes 19-21 et 23 :
Annoter, Évaluation, Vectorisation, Visite guidée). Restent : Sauvegardées, Profils,
Comment ça marche.

**`web/lib/api.ts`** (814 lignes) : suppression des helpers `listModels`,
`getEmbeddingProgress`, `searchHybrid`, `searchSemantic`, `listLeaderboard`,
`listEvalQueries`, `getEvalPool`, `annotate`, `searchMesh`, `meshAutocomplete` et de
leurs types (`EmbeddingModelInfo`, `EmbeddingCoverage`, `EmbeddingYearRow`,
`EmbeddingProgress`, `BenchRow`, `EvalQueryProgress`, `EvalCandidate`, `EvalPool`).

---

# Étape 6 — Lot 5 : base de données

Migration `alembic/versions/0011_drop_ml_eval.py` :

```sql
DROP TABLE emb_bge_m3, emb_medcpt;                    -- 4,3 Go récupérés
DROP TABLE bench_results, bench_runs, bench_qrels, bench_queries;
DROP TABLE eval_annotations, eval_pool;
DROP EXTENSION vector;
```

Rappel de provenance : les tables `emb_*` et `bench_*` sont créées par la migration
`0001_initial_schema.py`, les tables `eval_*` par `0003_eval_annotation.py`.

**Conservé** : la table `article_fr` (904 lignes) et `app/services/translate.py` —
c'est le cache de traduction FR utilisé **en production**. Seul son chargeur de test
(`scripts/load_translations.py`, qui lisait `bench/translations/`) disparaît.

---

# Étape 7 — Lot 6 : documentation

**Supprimés** : `PIPELINE_EMBEDDINGS.md`, `PLAN_EVAL.md`

**Mis à jour** : `CLAUDE.md` (il présente encore le pré-filtre sémantique pgvector comme
la voie officielle — c'est le fichier qui pilote l'assistant, il doit être exact),
`ARCHITECTURE.md`, `ALGO_RECHERCHE.md`, `ROADMAP_PERTINENCE.md`, `ETAT_DEMO.md`,
et la description du projet dans `pyproject.toml`.

**Conservé** : `documents/google-agentic-rag.md` (veille archivée, hors périmètre).

---

# Ce qu'on garde, contrairement à ce que le nom laisse croire

Trois scripts ont « bench » ou « v1_v2 » dans le nom mais servent **le cœur de la
recherche**, pas le gold set. Vérifié : aucun ne touche aux tables `eval_*`, `bench_*`
ou `emb_*`.

| Script | Ce qu'il fait vraiment |
|---|---|
| `scripts/bench_v1_v2.py` | rejoue des requêtes cliniques FR via `_run_deep_search` — l'outil d'arbitrage v1 vs v2 |
| `scripts/compare_v1_v2.py` | compare la sélection des candidats sous les deux algos, en lecture seule |
| `scripts/pubmed_coverage.py` | mesure la couverture locale du top PubMed (chantier algo V2) |

---

# Vérification finale

Dans cet ordre :

1. `uv run pytest` — les 4 tests existants **et** les nouveaux doivent être verts
2. `uv run ruff check` — attrape tout import devenu orphelin
3. `cd web && npm run build` — attrape toute référence front oubliée
4. `grep -rn "emb_\|eval_pool\|bench_queries\|embeddings" app/ web/app web/lib` → doit être vide
5. **Essai manuel : même requête clinique en v1 puis en v2**, résultats cohérents

---

# Récapitulatif

| Étape | Contenu | Risque |
|---|---|---|
| 0 | ✅ Tests 1 et 2 sur le code actuel (commit `e3c24a1`) | aucun |
| 1 | ✅ Extraction `_candidate_order` / `_pick_judge_batch` + test 3 (`62c7f3c`) | touche `search.py` — vérifié iso-comportement |
| 1 bis | ✅ Test 4 — bout en bout avec doublures | aucun |
| 2 | Dump d'archive éval/bench | aucun |
| 3 | Lot 1 — embeddings | faible |
| 4 | Lot 2 — évaluation / annotation | faible |
| 5 | Lot 3 — anciens endpoints de recherche | faible |
| 6 | Lot 4 — front | nul (le build tranche) |
| 7 | Lot 5 — migration DB | **irréversible** (d'où l'étape 1) |
| 8 | Lot 6 — documentation | aucun |
| 9 | Vérification + PR en draft | — |

Un commit par lot, sur une branche dédiée.

**Total : ~1 500 lignes supprimées · 4,3 Go de base récupérés · torch hors de l'image API.**
