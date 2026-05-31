# PLAN_EVAL.md — Évaluer la pertinence des recherches X-Med

> Objectif : pouvoir **comparer objectivement** deux configurations (modèle
> d'embedding, méthode de recherche, réglages) et **savoir si les résultats sont
> pertinents** — pas seulement « à l'œil ». Ce document est le plan de référence
> pour l'évaluation ; voir aussi `PIPELINE_EMBEDDINGS.md` (choix des modèles).

## 1. Deux façons de comparer

- **Qualitatif (au fil de l'eau)** : on tape des requêtes types, on regarde si
  c'est bon. Rapide, mais subjectif et non chiffré — sert de garde-fou.
- **Mesuré (reproductible)** : on se donne un **« corrigé »** (jeu de référence :
  requêtes + articles vraiment pertinents, jugés par un humain) et des
  **métriques** qui chiffrent la qualité. C'est ce qui permet de dire « config A
  > config B » et de suivre les progrès. **C'est la cible de ce plan.**

## 2. Les métriques (en clair)

| Métrique | Question à laquelle elle répond | À quoi elle sert |
|---|---|---|
| **Recall@100** | Parmi les 100 articles ramenés, a-t-on attrapé les bons ? | Qualité du **pré-filtre** (les candidats envoyés à Claude) |
| **nDCG@10** | Les bons articles sont-ils bien **placés** dans les 10 premiers ? | Qualité du **classement affiché** (tient compte du grade de pertinence) |
| **MRR** | À quelle position arrive le **premier** bon résultat ? | Confort : le 1ᵉʳ résultat est-il utile ? |
| **P@10** | Quelle fraction des 10 premiers est pertinente ? | Densité de pertinence en tête |

Implémentées via `ranx` dans `bench/runner.py` (`METRICS`).

## 3. Le jeu de référence (« gold set ») FR

C'est le cœur. NFCorpus (déjà branché) est **en anglais** : utile comme repère
standard, mais notre produit c'est *phrase FR → article*. Le verdict vient donc
d'un gold set **français**.

Décisions actées :
- **Annotation par les médecins** (ce sont eux qui jugent la pertinence clinique).
- **Pertinence graduée** : `0` = non pertinent, `1` = pertinent, `2` = très
  pertinent / idéal. (nDCG exploite ces grades.)
- **Corpus d'évaluation thématique** : on cible deux spécialités —
  **gynécologie/obstétrique** et **ophtalmologie** — sélectionnées par tags MeSH.

### Pourquoi un corpus thématique
On ne peut pas (encore) vectoriser les 1,2 M articles. On embedde donc d'abord un
sous-ensemble ciblé (gynéco ~59 k, ophtalmo ~23 k articles disponibles) : ainsi
les requêtes du gold set ont de vrais articles pertinents *dans le corpus
vectorisé*, et le recall n'est pas faussé. Filtre = `mesh_terms && <liste curée>`
(voir `THEMES` dans `scripts/embed_corpus.py`).

## 4. Workflow de bout en bout

```
1. EMBEDDER le corpus thématique (gynéco + ophtalmo), modèles bge_m3 + medcpt
   uv run python -m scripts.embed_corpus --model all --theme gyneco ophtalmo --index

2. ÉCRIRE les requêtes FR réalistes  ->  bench/queries_fr.json
   [{ "id": 1, "theme": "gyneco", "query": "saignements après la ménopause" }, ...]
   (objectif 30–50 requêtes, réparties sur les 2 spécialités, types variés)

3. POOLING des candidats à juger  ->  bench/pool_fr.csv
   uv run python -m scripts.build_pool
   (union des top-K de : plein-texte, bge_m3, medcpt — évite le biais d'un seul système)

4. ANNOTATION par les médecins : remplir la colonne `grade` (0/1/2) de pool_fr.csv

5. COMPILER le gold set  ->  bench/gold_fr.json
   uv run python -m scripts.build_pool --compile

6. MESURER + comparer  ->  leaderboard (table bench_*, et GET /api/bench/leaderboard)
   uv run python -m scripts.run_benchmark
```

## 5. Ce qu'on compare (méthodes)

Le site sert la recherche **hybride** (plein-texte + sémantique, fusion RRF). Le
benchmark évalue donc, sur le gold set FR, **trois variantes** pour répondre « la
recherche par le sens apporte-t-elle vraiment quelque chose ? » :

| Variante (model_name au leaderboard) | Ce qu'on teste |
|---|---|
| `fulltext` | la baseline « mots-clés » (ts_rank) |
| `bge_m3` / `medcpt` | le sémantique pur (plus proches voisins pgvector) |
| `hybrid:bge_m3` / `hybrid:medcpt` | **ce que le médecin obtient réellement** |

Attendu : `bge_m3` (multilingue) devrait dominer `medcpt` (anglais) sur des
requêtes **FR**, et l'hybride devrait égaler ou battre chaque méthode seule.

## 6. Garde-fous permanents

- **Requêtes-sanity** : ~10 phrases dont on connaît la bonne réponse, à rejouer
  après chaque changement (détection de régression).
- Plus tard : journaliser requêtes réelles + clics (signal d'usage), page de
  comparaison côte à côte (A/B).

## 7. Fichiers

| Fichier | Rôle |
|---|---|
| `bench/queries_fr.json` | requêtes FR (entrée, à rédiger) |
| `scripts/build_pool.py` | pooling des candidats + compilation du gold set |
| `bench/pool_fr.csv` | feuille d'annotation pour les médecins (grade 0/1/2) |
| `bench/gold_fr.json` | gold set compilé (requêtes + jugements gradués) |
| `bench/datasets.py` | chargement NFCorpus + gold FR |
| `bench/runner.py` | exécution + métriques (plein-texte / sémantique / hybride) |
| `scripts/run_benchmark.py` | lance tout, remplit le leaderboard |
