# Guide d'annotation — gold set X-Med

> À lire avant de remplir la colonne **`grade`** de `pool_fr.csv`. Objectif :
> juger, pour chaque requête, à quel point chaque article proposé y répond.
> Ces jugements servent de « corrigé » pour mesurer la qualité des recherches.

## Ce qu'on vous demande

Le fichier `pool_fr.csv` contient des lignes `requête → article candidat`. Pour
**chaque ligne**, mettez une note dans la colonne `grade` :

| Note | Sens | Critère |
|---|---|---|
| **2** | Très pertinent | Répond directement et précisément à la requête. C'est typiquement l'article qu'on aimerait voir **en tête** des résultats. |
| **1** | Pertinent | En rapport et utile, mais partiel, indirect, ou secondaire (sous-thème, population différente, aspect annexe). |
| **0** | Non pertinent | Hors sujet, ou lien trop ténu pour être utile en pratique. |

Laissez **vide** seulement si vous ne pouvez vraiment pas juger (ex. abstract
manquant). Une case vide = article non jugé (ignoré dans le calcul).

## Comment juger

- **Sur le fond clinique**, du point de vue d'un médecin de la spécialité.
- À partir du **titre + résumé (abstract)**. Inutile d'ouvrir l'article entier.
- Jugez la **pertinence par rapport à la requête**, pas la qualité de l'étude
  ni son ancienneté. (Le niveau de preuve est traité séparément par le système.)
- **La langue ne compte pas** : les articles sont en anglais, les requêtes en
  français — c'est normal. On évalue justement la capacité à faire le pont.
- En cas d'hésitation entre deux notes, prenez la **plus basse**.

## Exemples

**Requête : « saignements vaginaux après la ménopause »**
- `2` — étude sur le diagnostic des métrorragies post-ménopausiques / cancer de l'endomètre.
- `1` — article sur les saignements utérins en général (pré-ménopause incluse).
- `0` — article sur les saignements digestifs, ou sur la ménopause sans rapport avec les saignements.

**Requête : « traitement du glaucome à angle ouvert »**
- `2` — essai comparant des traitements du glaucome à angle ouvert.
- `1` — revue générale sur la pression intra-oculaire ou un autre type de glaucome.
- `0` — article d'ophtalmologie sans rapport (ex. cataracte), ou hors ophtalmo.

## En pratique

- Visez la **cohérence** entre annotateurs plus que la perfection : mieux vaut
  une règle simple appliquée pareil par tous.
- Comptez ~10–15 s par ligne. Une requête a en général 20–60 candidats.
- Quand le fichier est rempli : `uv run python -m scripts.build_pool --compile`
  génère `bench/gold_fr.json`, puis `uv run python -m scripts.run_benchmark`
  met à jour le tableau de la page **Évaluation**.
