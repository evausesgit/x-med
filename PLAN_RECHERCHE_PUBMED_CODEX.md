# X-Med - Plan de recherche PubMed avec Codex

## Entrees

- `PRM` : phrase recherchee du medecin
- `st` : date de debut
- `ed` : date de fin

## Algorithme

### 1. Recherche PubMed -> A

GPT-5.4 transforme `PRM` en requete PubMed structuree avec des mots-cles,
des termes MeSH et la periode `st-ed`.

PubMed execute cette requete et retourne une liste de liens vers les articles :
`A`.

### 2. Recherche locale par Codex -> B

Recuperer les abstracts locaux des articles publies entre `st` et `ed`.

Decouper ces abstracts en lots dont la taille respecte la fenetre de contexte
de GPT-5.4. Pour chaque lot, Codex :

- compare semantiquement chaque abstract a `PRM`, en evaluant la proximite de
  sens et la pertinence medicale, meme lorsque des termes differents sont
  employes ;
- attribue un score de pertinence selon une grille identique ;
- conserve les articles coherents avec `PRM`.

L'ensemble des articles retenus forme la liste `B`.

### 3. Fusion et classement -> C

Fusionner `A + B`, puis dedupliquer les articles par PMID.

Codex verifie la coherence des articles avec `PRM`, puis les classe selon :

1. la pertinence ;
2. la qualite scientifique ;
3. la recence.

La liste obtenue est `C`.

### 4. Production finale

Pour les meilleurs articles de `C` :

- traduire ;
- resumer ;
- evaluer la qualite ;
- creer un contenu vocal.

## Vue synthetique

```text
PRM + st + ed
      |
      +--> PubMed structure par GPT-5.4 ----------------> A
      |
      +--> Abstracts locaux analyses par lots Codex ----> B
                                                           |
                                  A + B -> deduplication -> C
                                                           |
                         traduction -> resume -> qualite -> vocal
```
