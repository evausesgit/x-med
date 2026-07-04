# Évaluation franche — Recherche PubMed + IA : v1 vs v2

_8 requêtes cliniques FR · fenêtre 2025-01-01 → 2026-07-04 · données brutes :
`results.json` (bout-en-bout) et `selection.json` (contrôlé). Reproductible :
`scripts/bench_v1_v2.py` et `scripts/bench_selection.py`._

> **En une phrase.** Les deux versions marchent et l'IA classe bien ce qu'elle voit, mais
> ce benchmark met au jour un problème plus important que « v1 ou v2 » : **notre
> bibliothèque locale de 25 M d'articles ne contribue quasiment jamais** (le filtre
> plein-texte n'aboutit pas sur les sujets à termes fréquents), si bien qu'aujourd'hui
> « PubMed + IA » ≈ « **PubMed en direct + IA** » sur la plupart des recherches.

## Comment on a mesuré

Deux passages complémentaires :

1. **Bout-en-bout (production réelle)** — même code que le produit (`_run_deep_search`),
   garde-fou local 8 s compris. Mesure temps, volumes, articles retenus, provenance.
2. **Contrôlé (isolation des méthodes)** — on réutilise la requête déjà construite (pas de
   variance Codex) et on relance le local avec un **timeout généreux de 120 s**, pour voir
   v1/v2 « comme conçues » et chiffrer ce que le garde-fou fait perdre.

⚠️ **Ce que ce benchmark mesure = le comportement** (vitesse, volumes, recouvrement,
provenance). Il **ne juge pas la pertinence clinique** : dire si les articles retenus sont
*les bons* demande un médecin en aveugle (étape suivante, cf. plus bas).

## Résultat 1 — Temps & volumes (bout-en-bout, moyennes sur 8 requêtes)

| Mesure | v1 (score IA) | v2 (fusion RRF) |
|---|--:|--:|
| **Temps moyen** | **54 s** | **92 s** |
| Articles PubMed récupérés | 12 | 100 |
| Candidats fusionnés | 37 | 100 |
| Jugés par l'IA | 12 | 50 |
| **Articles retenus** | **8,1** | **24,0** |
| dont « local-seul » | 1,9¹ | 0,0 |
| Tokens Codex | ~59 800 | ~71 400 |

¹ ces 1,9 viennent d'**une seule** requête (SGLT2) ; sur les 7 autres, v1 = 0 local aussi.

**Lecture.** v2 = « **plus, mais plus lent** » : ~3× plus de résultats (24 vs 8) pour ~1,7×
le temps (+38 s), parce qu'elle juge 50 articles au lieu de 12. Presque tout vient de
**PubMed en direct**, pas de notre base.

## Résultat 2 — Recouvrement v1 ↔ v2

Jaccard des articles retenus par requête : **0,09 à 0,29** (moyenne ~0,2). Autrement dit
**v1 et v2 renvoient des listes très différentes** — se recouvrant à ~20 %. Ce n'est donc
pas « la même chose en plus long » : ce sont deux résultats distincts, et **il faut un
médecin pour dire lequel est meilleur**.

## Résultat 3 — Le point critique : la base locale ne répond pas

Passage contrôlé, local à **timeout généreux 120 s** :

| Requête | Local ramené | Temps local |
|---|--:|--:|
| SGLT2 (noms de molécules = termes **rares**) | **200** | 31 s |
| Sémaglutide / diabète type 2 | **0** | >120 s |
| Dépistage HPV col utérus | **0** | >120 s |
| DMLA néovasculaire | **0** | >120 s |
| Pneumonie communautaire | **0** | >120 s |
| Anticoagulation / fibrillation atriale | **0** | >120 s |
| Corticoïdes / COVID-19 | **0** | >120 s |
| Immunothérapie / mélanome | **0** | >120 s |

**7 requêtes sur 8 ne ramènent AUCUN article local, même avec 120 s.** Cause : à 25 M
articles, le coût du filtre plein-texte dépend de la **fréquence des mots** ; un mot courant
(« diabetes », « bleeding »…) a une liste d'index énorme à trier. Seuls les sujets à
**termes rares** (noms de molécules) passent. **Ce n'est pas un problème de réglage du
garde-fou** — même à 120 s ça ne passe pas — mais de **méthode** (lexical à cette échelle).

Conséquence : en production (garde-fou 8 s), le local est coupé sur **15 des 16
exécutions**. Notre différenciateur — les 25 M d'articles — est aujourd'hui **inexploité**
sur la quasi-totalité des recherches.

## Résultat 4 — La fusion RRF de v2 ne favorise PAS le local (contre-intuitif)

Sur SGLT2 (la seule requête où le local répond), part d'articles **locaux-seuls** dans le
lot de 50 jugés :

| | v1 | v2 |
|---|--:|--:|
| Local-seul dans les 50 jugés | **38** | **9** |

v2 fait **moins** bien que v1 ! Avec `k_pubmed=100` et `local_floor=0`, les 100 articles
PubMed **écrasent** le local dans la fusion RRF. La promesse « v2 remonte mieux le local »
est donc **fausse telle que configurée** — il faudrait un `local_floor > 0` (le curseur
existe, mais vaut 0 par défaut). Point mineur tant que le local ne répond pas, mais à noter.

---

## Verdict

- **Vitesse** : maîtrisée. v1 ~54 s, v2 ~92 s. Dominée par les 2 appels Codex, pas par la base.
- **v1 vs v2, en pratique aujourd'hui** : v2 = plus de résultats, plus lent, **quasi 100 %
  PubMed** ; v1 = plus rapide, plus resserré. Ils divergent beaucoup (Jaccard ~0,2).
- **Le vrai sujet** : la **base locale ne contribue pas** (7/8 requêtes), donc l'atout censé
  distinguer v2 ne se matérialise pas, et le produit est de fait « PubMed live + IA ».
- **Pertinence** : **non mesurée** ici. On sait *combien* et *d'où*, pas *si c'est juste*.

## Recommandations (par priorité)

1. **🔴 Rendre la base locale exploitable** — remplacer le pré-filtre local **lexical** par
   une recherche **sémantique (pgvector/HNSW)** dont le coût ne dépend pas de la fréquence
   des mots (temps ~constant), ou un **index RUM**. C'est LA condition pour que les 25 M
   servent et que v2 ait un sens. Preuve chiffrée ci-dessus.
2. **🔴 Mesurer la pertinence** — gold set de ~30-50 questions annotées par des médecins **en
   aveugle**, puis nDCG@10 / P@10 sur la liste affichée et rappel des pertinents dans les 50
   jugés. Sans ça, on ne peut ni prouver la qualité ni choisir v1/v2 rationnellement.
3. **🟠 Si on garde v2 avec local** : passer `local_floor > 0` (sinon k_pubmed=100 écrase le
   local, cf. Résultat 4).
4. **🟠 Nettoyer l'outillage** : `scripts/compare_v1_v2.py` est périmé (utilise l'ancien
   `OR MeSH` retiré + k=20) et `bench/pubmed_ab.py` compare une méthode supprimée →
   remplacés par `bench_v1_v2.py` + `bench_selection.py`.

## À partager aux médecins — version simple

- Notre outil pose votre question à **PubMed en direct** et une **IA lit et classe** chaque
  article. Ça marche et c'est rapide (~1 min).
- **Deux réglages** : *v1* (rapide, liste resserrée) et *v2* (plus large, plus de résultats,
  un peu plus lent).
- **Transparence** : la « bibliothèque interne de 25 M d'articles » que nous voulons ajouter
  **n'est pas encore effective** sur la plupart des sujets — nous savons pourquoi et c'est
  notre priorité n°1. Aujourd'hui, la valeur vient de **PubMed en direct + le tri par l'IA**.
- Prochaine étape : faire **noter par des médecins** un échantillon de résultats pour prouver,
  chiffres à l'appui, que ce qui remonte est **cliniquement pertinent**.
