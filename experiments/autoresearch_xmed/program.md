# Autoresearch X-Med — programme des 30 essais

Ce programme adapte `karpathy/autoresearch` à une pipeline médicale. Le but n'est pas
d'obtenir le meilleur score moyen : il faut réduire latence et coût **après** avoir
prouvé que qualité et diversité ne baissent pas.

## Périmètre fixe

- Branche dédiée uniquement ; ne jamais pousser sur `main`/`master`.
- Ne modifier que `experiments/autoresearch_xmed/experiment.py` pendant la boucle.
- Ne pas modifier `score.py`, `prepare_bench.py`, `queries.jsonl`, les qrels ou les
  fixtures après le round 1.
- Ne jamais écrire dans `xmed`, appeler les endpoints de production, envoyer une
  notification, redémarrer PostgreSQL, ou réutiliser `saved_searches`.
- Un run DB live ou replay doit utiliser uniquement la base clonée dont le nom
  contient `autoresearch`; les sessions doivent avoir
  `default_transaction_read_only=on`.
- Les réponses PubMed et les sorties LLM sont rejouées pendant le hill-climb. Les
  finalistes seuls passent en confirmation live appariée.

## Mise en place

1. Lire intégralement `README.md`, `prepare_bench.py`, `score.py`, `experiment.py`
   et `trial_plan.json`.
2. Vérifier la branche `codex/autoresearch-benchmark` et l'état Git. Préserver toute
   modification étrangère.
3. Générer le manifeste fixe avec `prepare_bench.py`.
4. Initialiser `results.tsv` avec :

   ```text
   round\tcommit\tstatus\tgate\tp50_s\tp95_s\ttokens\tdescription
   ```

5. Exécuter le round 1 sans changement pour établir la baseline courante. Les JSON
   historiques du 4 juillet ne sont pas une baseline actuelle (anciens paramètres).

## Portes de promotion

Trois portes existent :

- `fidelity` : la liste ordonnée des résultats, les entrées du juge, les prompts et
  les traductions doivent être byte-identiques. À réserver aux tests déterministes.
- `clinical` : exige des qrels et des annotations de traduction indépendantes. La
  moyenne candidate et chaque strate de largeur pré-déclarée (`broad`, `narrow`,
  `rare`) doivent respecter les marges de non-infériorité pré-déclarées ci-dessous
  pour nDCG@10, P@10, Recall@50 et les métriques de diversité. Les différences par
  requête sont rapportées mais ne bloquent pas isolément. Sans annotations :
  `ineligible`.

Les traductions différentes sont notées en aveugle par PMID sur fidélité clinique,
terminologie et lisibilité (1–5), avec comptage des erreurs critiques. La couverture
doit être complète et chaque moyenne candidate par PMID doit rester au moins à 3/5.
Les deltas candidats doivent être au moins à −0,15 globalement, −0,25 dans chaque
strate pré-déclarée et −0,50 dans le pire quartile. Aucune erreur critique
supplémentaire n'est admise, ni globalement ni sur un PMID. Ces marges sont fixées
avant tout jugement bilingue réel ; omissions et hallucinations non critiques restent
rapportées comme diagnostics.
Un refactor qui conserve le même protocole v2 fingerprinté et tous les knobs d'entrée
du traducteur ne se voit toutefois pas attribuer la simple variance de formulation du
LLM : la porte vérifie alors strictement que le nombre de traductions manquantes ne
progresse pas. Dès que le contrat ou l'entrée du traducteur change, le jugement
bilingue ci-dessus redevient obligatoire.
- `auto` : tente d'abord l'équivalence exacte ; si les sorties diffèrent, bascule sur
  `clinical`. C'est la porte normale des refactors autour des LLM : la variance ou une
  meilleure sélection ne sont pas pénalisées tant que la non-infériorité clinique et
  la diversité sont démontrées.

Puis seulement : taux d'erreur/timeout non supérieur, p50 et p95, tokens et appels
externes. Le candidat doit améliorer strictement au moins un axe d'efficacité sans
en dégrader un autre de plus de 5 %. Le seuil minimal d'un gain mesuré est fixé à
10 % afin de ne pas promouvoir du bruit. À égalité, la solution la plus simple gagne.

Les marges sont absolues et non compensatoires : une hausse d'une métrique ne rachète
jamais une baisse hors marge d'une autre. Pour les métriques de qualité normalisées
(nDCG@10, P@10 et Recall@50), la perte maximale est de `0,02`, globalement et dans
chaque strate. Pour le screening retrieval, la perte maximale de
`relevant_count_total` vaut `max(1, floor(0,02 * relevant_count_total_baseline))` :
on calcule 2 % du total baseline du groupe, on arrondit vers le bas à l'entier, puis
on autorise au minimum un document. `graded_gain` reste diagnostique.

Les marges de diversité dépendent de l'échelle réellement calculée. Pour l'entropie,
la perte maximale vaut `max(0,05 bit, 0,02 * entropie_baseline)`. Dans `score.py`, la
coverage `/10` mesure une proportion de métadonnées présentes et sa marge absolue est
`0,02`. Dans `score_retrieval.py`, la coverage compte des catégories uniques parmi
les résultats pertinents et sa marge vaut
`max(0,25 catégorie par requête, 0,02 * coverage_baseline)`. Ces définitions ne sont
pas interchangeables.

Pour éviter qu'une moyenne masque plusieurs dégâts, la moyenne du pire quartile des
deltas nDCG par requête doit rester au moins à `-0,05`. La borne basse unilatérale
95 % du bootstrap apparié par requête (10 000 tirages déterministes) doit rester à
`-0,02` ou plus. Le pire quartile des deltas de diversité doit rester au moins à
`-0,10 bit` pour l'entropie, `-0,10` pour la coverage `/10` de `score.py`, et
`-1 catégorie` pour la coverage de `score_retrieval.py`. Avec seulement 18 questions,
ce passage n'est une preuve que sur ce corpus et ne constitue pas une validation
clinique générale.

## Boucle bornée à 30 rounds

Pour chaque entrée de `trial_plan.json`, dans l'ordre :

1. Partir de l'incumbent conservé et formuler une hypothèse unique.
2. Modifier uniquement `experiment.py`.
3. Exécuter les tests puis le replay sur le split développement pour un refactor
   déterministe. Si le candidat introduit un PMID, un prompt ou un comportement LLM
   non capturé, exécuter des captures live appariées ; le replay doit refuser ce cas.
4. Appeler `score.py` avec la porte déclarée par le plan.
5. Journaliser `keep`, `reject`, `ineligible` ou `crash`, y compris les échecs.
6. `keep` seulement si toutes les portes passent et l'efficacité progresse.
7. Pour un rejet, remettre explicitement `experiment.py` au contenu de l'incumbent
   sans commande Git destructive et sans toucher aux fichiers du user.
8. Après les rounds 10, 20 et 29, confirmer l'incumbent trois fois en ordre AB/BA
   aléatoire. Le round 30 exécute une seule fois le holdout scellé.

Les 30 rounds sont un plafond demandé, pas une permission de promouvoir 30 idées.
Les essais 7–29 sont des hypothèses ; leurs paramètres ne sont pas des recommandations.

## Sorties de chaque round

- commit et hash du manifeste ;
- hypothèse et diff de configuration ;
- artefact brut par requête ;
- métriques et verdict de chaque porte ;
- décision et raison courte ;
- p50/p95 usable et complet, tokens par étape, cache hits, appels NCBI et DB.

Ne jamais déclarer l'objectif atteint si les finalistes n'ont pas une confirmation
live appariée et si les changements sémantiques promus n'ont pas de gold set médical.
