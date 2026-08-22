# Recommandations de sociétés savantes dans X-Med

22 août 2026. Étape 1 **implémentée** (cette branche) ; étapes 2 à 5 à arbitrer.

## Constat de départ

`grep -rin guideline app/ web/` renvoyait zéro résultat, alors que
`PRESENTATION_MEDECINS.md` promet aux médecins les « recommandations de sociétés
savantes » comme type d'étude sélectionnable (ligne 24) et affiche
« recommandations ESC/AHA » dans le profil type (ligne 112).

Or ces recommandations sont **déjà dans le corpus** : les grandes sociétés
internationales publient dans des revues indexées MEDLINE. Échantillonnage de
pages sur `articles` (`TABLESAMPLE SYSTEM`, deux tirages, 40 recos sur 38 374
lignes) → **~26 000 recommandations en base**, dont ~3 000 à 5 000 depuis 2020.
Marge large : l'échantillon est petit, le comptage exact demande une passe de
fond hors heures d'ingestion (pas d'index sur `publication_types` avant la
migration 0012).

Elles étaient invisibles pour trois raisons cumulées :

1. `_EVIDENCE_BY_TYPE` (`app/tasks/parse_articles.py`) ne connaissait aucun type
   de recommandation → `min(levels) if levels else 4` les classait **niveau 4**,
   à égalité avec un éditorial ;
2. le tri final de la recherche (`app/api/search.py`) trie par `evidence_level`
   croissant → une reco ESC 2024 passait derrière tous les RCT ;
3. le juge codex recevait « niveau de preuve 4 » dans ses métadonnées, et le
   metaprompt du digest lui demande de « privilégier les méta-analyses et essais
   randomisés (niveau 1) » quand le profil exige un niveau élevé.

Ce n'était pas une exclusion dure — `min_evidence_level` n'est pas un `WHERE`
SQL — mais une **relégation systématique**, sur les trois maillons à la fois.

## Étape 1 — corriger le typage (fait)

`app/services/doc_kind.py` : table de vérité unique
(`Practice Guideline`/`Guideline` → 1, `Consensus Development Conference` → 2),
`is_guideline()` et `effective_evidence_level()`.

Le point de conception qui a guidé le reste : **corriger l'ingestion ne répare
que l'avenir**. Les 26 000 recommandations déjà en base gardent leur niveau 4, et
un `UPDATE` global sur 30 Go de heap n'est pas envisageable en production (cache
Postgres à 8 Go de `shared_buffers`, latence de `article_search` déjà tendue).
D'où la correction **à la lecture**, depuis `publication_types` déjà stocké :
aucun backfill, aucun verrou, effet immédiat sur tout l'historique.

Touché : ingestion, `ArticleResult` et `DeepHit` (nouveau champ `is_guideline`),
les deux `_judge_item` du pipeline de recherche, le prompt du juge codex, le
metaprompt du digest, le panneau « Pourquoi ce résultat ? », migration 0012
(index GIN sur `publication_types`).

## Étape 2 — surfacer avant de construire

Onglet ou filtre « Recommandations » dans la recherche, alimenté **uniquement**
par ce qui est déjà dans le corpus. Zéro nouvelle source, l'index 0012 rend le
filtre instantané. Le champ `is_guideline` est déjà exposé par l'API ; il reste
un badge à afficher côté `web/` (là où `level={hit.evidence_level}` est passé
aujourd'hui, `web/app/recherches/shared.tsx:59` et `web/app/page.tsx:1186`).

Objectif : **mesurer l'appétence avant d'écrire un ingesteur**. Si les médecins
de la liste de septembre ne cliquent pas, les étapes 3 et 4 ne valent pas leur
coût.

## Étape 3 — modèle `guidelines` (si l'étape 2 est concluante)

Une recommandation n'est pas un article, sur trois points qui cassent le modèle
`articles` :

- **Versionnement.** Un PMID est un événement immuable ; une recommandation est
  un état courant. ESC FA 2024 *remplace* ESC FA 2020. Il faut
  `status` (en vigueur / remplacée / retirée) et `superseded_by`. Afficher une
  reco de 2016 sans signaler qu'elle est possiblement remplacée est pire que ne
  rien afficher.
- **Granularité.** Un abstract fait 250 mots, une recommandation 80 à 200 pages :
  elle ne tient pas dans un prompt. La bonne unité n'est pas le document mais
  **l'énoncé** — texte court + classe (I / IIa / IIb / III) + niveau de preuve
  (A/B/C). Donnée structurée, bien plus exploitable que la prose. D'où une table
  fille `guideline_statements`.
- **Droit d'auteur.** HAS : documents publics, réutilisation libre. ESC/AHA :
  copyright OUP/AHA. Citer + lier + métadonnées est sûr partout ; stocker et
  reservir le texte intégral se décide société par société. Contrainte de
  conception, pas formalité juridique de fin de chantier.

Emplacement : **bloc corpus** au sens de la refonte
`2026-07-24-infra-deux-composes-previews.md` — contenu externe, écrit par un
worker, lu en lecture seule par la prod et toutes les previews. Contre-argument
recevable : la table est minuscule (quelques milliers de lignes contre 25 M),
donc la cloner par preview serait indolore, ce qui plaiderait pour le bloc
application le temps d'itérer sur le schéma.

## Étape 4 — sources hors PubMed

Trois adaptateurs, par difficulté croissante :

1. **PubMed** — quasi gratuit : `("Practice Guideline"[PT] OR "Guideline"[PT])
   AND <spécialité>` via E-utilities, ou filtre sur le flux FTP quotidien. Donne
   les sociétés internationales avec des métadonnées propres.
2. **HAS** — publie en open data sur data.gouv.fr et expose une API de
   métadonnées de ses publications (typées : recommandations de bonne pratique,
   évaluations, études). Documents publics librement réutilisables.
3. **Sociétés françaises de spécialité** (SFC, CNGOF, SPILF, SFAR, SFD…) — ni
   API ni flux : scraping ciblé, fragile, à limiter aux 3 à 5 sociétés de la
   **spécialité pilote**. Ne pas généraliser d'emblée.

Décision bloquante pour cette étape : **quelle spécialité pour la liste de
médecins de septembre ?** Si c'est la cardiologie, SFC + ESC et le terrain est
facile ; en médecine générale, c'est HAS + CNGE et un autre chantier.

## Étape 5 — l'axe produit

C'est ici que la recommandation cesse d'être un résultat de plus.

- **Digest** : « cet article porte sur la FA ; la reco en vigueur est ESC 2024,
  classe I pour l'anticoagulation si CHA₂DS₂-VASc ≥ 2 ; l'article rapporte X. »
  La question du médecin n'est pas « quoi de neuf » mais **« est-ce que ça change
  ma pratique »** — et la pratique, c'est la recommandation.
- **Lecture critique** (fonctionnalité différenciante V2) : la comparaison
  **article ↔ recommandation** est plus utile au clinicien que article ↔ article,
  et c'est ce qu'un moteur de recherche ne sait pas faire.
- **Alerte de divergence** : un essai de niveau 1 dont la conclusion s'oppose à
  une recommandation classe I. Rare — et c'est exactement l'information pour
  laquelle un médecin ouvre un email.

## Garde-fou

`app/services/linkedin_post.py:78` pose déjà « ne JAMAIS donner de conseil
clinique ». Sur les recommandations l'exigence monte d'un cran : toujours citer
société + date + lien vers le document officiel, ne jamais afficher un énoncé
reformulé par l'IA sans le texte original à côté, ne jamais présenter une
recommandation périmée comme en vigueur.
