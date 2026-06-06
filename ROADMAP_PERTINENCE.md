# X-Med - Feuille de route pertinence

Ce tableau sert de référence pour améliorer la pertinence de la recherche.
Le système actuel constitue la baseline `A`. Toute évolution doit être comparée
à cette baseline sur le gold set médical avant son activation en production.

| Sujet | Ce qui existe actuellement | Ce qu'il faudrait ajouter | Priorité |
|---|---|---|---|
| Corpus PubMed | Articles PubMed ingérés | Terminer l'ingestion, privilégier les données récentes et mesurer la couverture par année et spécialité | Critique |
| Vectorisation | Une partie des articles vectorisée | Vectoriser 100 % du corpus utile avec `bge-m3` et détecter les articles manquants | Critique |
| Gold set médical | 13 questions gynéco/ophtalmo préparées, interface d'annotation | Ajouter les questions réelles des médecins, terminer les annotations et compiler `gold_fr.json` | Critique |
| Evaluation | `Recall@100`, `nDCG@10`, `MRR`, `P@10` | Comparer automatiquement chaque nouvelle configuration au système actuel | Critique |
| Modèle d'embedding | `bge-m3` multilingue par défaut | Le conserver comme baseline ; ne changer que si le gold set démontre un gain | Haute |
| Contenu vectorisé | Un vecteur par article sur `titre + abstract` | Tester une représentation enrichie : titre, MeSH, type d'étude et abstract | Haute |
| Découpage en chunks | Aucun | Mesurer d'abord la troncature ; découper uniquement les abstracts réellement trop longs | Basse |
| Requête utilisateur | Question française encodée directement | Ajouter synonymes médicaux anglais, termes MeSH et expansion clinique structurée | Haute |
| Sécurité de la reformulation | Sans objet | Rechercher avec la question originale et la version enrichie pour ne perdre aucun détail | Haute |
| Recherche sémantique | Top-k par similarité cosinus avec `pgvector` | Récupérer un vivier plus large, par exemple 50 à 100 candidats | Haute |
| Recherche plein texte | Toujours disponible dans l'API et le benchmark | La laisser hors du parcours français tant qu'une approche adaptée n'est pas validée | Basse |
| Classement final | Ordre produit directement par `bge-m3` | Ajouter un reranker médical ou cross-encoder sur les candidats | Haute |
| Métadonnées | Année, MeSH, type d'étude et niveau de preuve stockés | Permettre filtres et bonus explicites selon la question | Moyenne |
| Explicabilité | Score de similarité + panneau factuel : concepts MeSH, population, intervention et type d'étude quand identifiables | Evaluer la qualité des explications avec les médecins, puis les relier au futur reranker | Moyenne |
| Suivi terrain | Annotation médicale dédiée | Journaliser anonymement requêtes, clics et jugements utile ou non pertinent | Moyenne |
| Comparaison | Modèles comparés dans le benchmark | Comparer `A` actuel, `B` enrichi, `C` expansion de requête et `D` reranking | Haute |

## Configurations à comparer

- `A` : recherche sémantique `bge-m3` actuelle.
- `B` : documents enrichis avec les métadonnées médicales.
- `C` : documents enrichis et expansion contrôlée de la requête.
- `D` : récupération large suivie d'un reranking médical.
