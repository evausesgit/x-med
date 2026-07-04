# Benchmark franc — Recherche PubMed + IA : v1 vs v2

_Généré le 2026-07-04 11:32 · fenêtre **2025-01-01 → 2026-07-04** · 8 requêtes cliniques._

## Méthode

Chaque requête est rejouée dans les deux versions via la **même fonction que la production** (`_run_deep_search`). Paramètres identiques à l'UI :

- **v1 · score IA** (défaut) : `k_pubmed=12`, fusion « PubMed d'abord », lot 50.
- **v2 · fusion RRF** : `k_pubmed=100`, fusion RRF (local non enterré), lot 50.
- Communs : `max_local=200`, `min_score=2`, même fenêtre de dates.

Le **tri final est toujours le score Codex** dans les deux cas ; v1/v2 ne changent que **quels candidats sont jugés**.

## Résultats par requête

| Requête | Ver. | Temps | PubMed | Local | Fusion | Jugés | **Retenus** | dont local-seul | Score 3/2 | Local coupé (8s) |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| Inhibiteurs du SGLT2 dans l'insuff | v1 | 89s | 12 | 0 | 12 | 12 | **3** | 0 | 2/1 | ⏱️ oui |
|  | v2 | 93s | 100 | 0 | 100 | 50 | **13** | 0 | 7/6 | ⏱️ oui |
| Efficacité du sémaglutide oral dan | v1 | 39s | 12 | 0 | 12 | 12 | **1** | 0 | 1/0 | ⏱️ oui |
|  | v2 | 89s | 100 | 0 | 100 | 50 | **18** | 0 | 7/11 | ⏱️ oui |
| Dépistage du cancer du col de l'ut | v1 | 39s | 12 | 0 | 12 | 12 | **9** | 0 | 7/2 | ⏱️ oui |
|  | v2 | 91s | 100 | 0 | 100 | 50 | **34** | 0 | 11/23 | ⏱️ oui |
| Prise en charge de la dégénérescen | v1 | 45s | 12 | 0 | 12 | 12 | **9** | 0 | 5/4 | ⏱️ oui |
|  | v2 | 90s | 100 | 0 | 100 | 50 | **30** | 0 | 12/18 | ⏱️ oui |
| Antibiothérapie de la pneumonie ai | v1 | 46s | 12 | 0 | 12 | 12 | **6** | 0 | 5/1 | ⏱️ oui |
|  | v2 | 76s | 100 | 0 | 100 | 50 | **21** | 0 | 13/8 | ⏱️ oui |
| Anticoagulation et risque hémorrag | v1 | 45s | 12 | 0 | 12 | 12 | **12** | 0 | 11/1 | ⏱️ oui |
|  | v2 | 85s | 100 | 0 | 100 | 50 | **36** | 0 | 22/14 | ⏱️ oui |
| Corticoïdes dans le traitement de  | v1 | 58s | 12 | 0 | 12 | 12 | **1** | 0 | 0/1 | ⏱️ oui |
|  | v2 | 80s | 100 | 0 | 100 | 50 | **11** | 0 | 4/7 | ⏱️ oui |
| Immunothérapie adjuvante dans le m | v1 | 48s | 12 | 0 | 12 | 11 | **5** | 0 | 4/1 | ⏱️ oui |
|  | v2 | 89s | 100 | 0 | 100 | 50 | **17** | 0 | 8/9 | ⏱️ oui |

## Recouvrement v1 ↔ v2 (articles retenus)

| Requête | Retenus v1 | Retenus v2 | Communs | Jaccard | Temps v1→v2 |
|---|--:|--:|--:|--:|--:|
| Inhibiteurs du SGLT2 dans l'insuffisance | 3 | 13 | 3 | 0.231 | 89s → 93s |
| Efficacité du sémaglutide oral dans le d | 1 | 18 | 1 | 0.056 | 39s → 89s |
| Dépistage du cancer du col de l'utérus p | 9 | 34 | 9 | 0.265 | 39s → 91s |
| Prise en charge de la dégénérescence mac | 9 | 30 | 9 | 0.3 | 45s → 90s |
| Antibiothérapie de la pneumonie aiguë co | 6 | 21 | 5 | 0.227 | 46s → 76s |
| Anticoagulation et risque hémorragique d | 12 | 36 | 12 | 0.333 | 45s → 85s |
| Corticoïdes dans le traitement de la COV | 1 | 11 | 0 | 0.0 | 58s → 80s |
| Immunothérapie adjuvante dans le mélanom | 5 | 17 | 4 | 0.222 | 48s → 89s |

## Agrégats (moyennes)

| Mesure | v1 | v2 |
|---|--:|--:|
| Temps moyen | 51.0s | 86.7s |
| PubMed récupérés (moy.) | 12.0 | 100.0 |
| Candidats fusionnés (moy.) | 12.0 | 100.0 |
| Retenus (moy.) | 5.8 | 22.5 |
| dont local-seul (moy.) | 0.0 | 0.0 |
| Tokens codex (moy.) | 58144.5 | 79987.4 |

## Lecture (à valider par des médecins)

- **Temps** : mesuré ci-dessus, dominé par les 2 appels Codex (requête + jugement).
- **Rappel du local** : `dont local-seul` = articles retenus présents UNIQUEMENT dans notre base (invisibles de la fenêtre PubMed). C'est l'axe où v2 est censée battre v1.
- **Jaccard v1↔v2** : proche de 1 = les deux versions renvoient la même chose ; bas = elles divergent (et il faut un médecin pour dire laquelle a raison).

> ⚠️ Ce benchmark chiffre le COMPORTEMENT (vitesse, volumes, recouvrement, provenance). Il **ne juge pas la pertinence clinique** : seul un médecin, en aveugle, peut dire si les articles retenus sont les bons. C'est l'étape suivante.
