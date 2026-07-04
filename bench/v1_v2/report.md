# Benchmark franc — Recherche PubMed + IA : v1 vs v2

_Généré le 2026-07-04 06:04 · fenêtre **2025-01-01 → 2026-07-04** · 8 requêtes cliniques._

## Méthode

Chaque requête est rejouée dans les deux versions via la **même fonction que la production** (`_run_deep_search`). Paramètres identiques à l'UI :

- **v1 · score IA** (défaut) : `k_pubmed=12`, fusion « PubMed d'abord », lot 50.
- **v2 · fusion RRF** : `k_pubmed=100`, fusion RRF (local non enterré), lot 50.
- Communs : `max_local=200`, `min_score=2`, même fenêtre de dates.

Le **tri final est toujours le score Codex** dans les deux cas ; v1/v2 ne changent que **quels candidats sont jugés**.

## Résultats par requête

| Requête | Ver. | Temps | PubMed | Local | Fusion | Jugés | **Retenus** | dont local-seul | Score 3/2 | Local coupé (8s) |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| Inhibiteurs du SGLT2 dans l'insuff | v1 | 75s | 12 | 200 | 210 | 50 | **19** | 15 | 8/11 | — |
|  | v2 | 93s | 100 | 0 | 100 | 50 | **22** | 0 | 8/14 | ⏱️ oui |
| Efficacité du sémaglutide oral dan | v1 | 67s | 12 | 0 | 12 | 12 | **2** | 0 | 2/0 | ⏱️ oui |
|  | v2 | 80s | 100 | 0 | 100 | 50 | **16** | 0 | 7/9 | ⏱️ oui |
| Dépistage du cancer du col de l'ut | v1 | 45s | 12 | 0 | 12 | 11 | **10** | 0 | 6/4 | ⏱️ oui |
|  | v2 | 78s | 100 | 0 | 100 | 50 | **30** | 0 | 10/20 | ⏱️ oui |
| Prise en charge de la dégénérescen | v1 | 53s | 12 | 0 | 12 | 12 | **7** | 0 | 5/2 | ⏱️ oui |
|  | v2 | 103s | 100 | 0 | 100 | 50 | **30** | 0 | 14/16 | ⏱️ oui |
| Antibiothérapie de la pneumonie ai | v1 | 50s | 12 | 0 | 12 | 12 | **8** | 0 | 5/3 | ⏱️ oui |
|  | v2 | 118s | 100 | 0 | 100 | 50 | **27** | 0 | 17/10 | ⏱️ oui |
| Anticoagulation et risque hémorrag | v1 | 46s | 12 | 0 | 12 | 12 | **12** | 0 | 11/1 | ⏱️ oui |
|  | v2 | 94s | 100 | 0 | 100 | 50 | **42** | 0 | 21/21 | ⏱️ oui |
| Corticoïdes dans le traitement de  | v1 | 55s | 12 | 0 | 12 | 12 | **2** | 0 | 0/2 | ⏱️ oui |
|  | v2 | 85s | 100 | 0 | 100 | 50 | **10** | 0 | 3/7 | ⏱️ oui |
| Immunothérapie adjuvante dans le m | v1 | 46s | 12 | 0 | 12 | 12 | **5** | 0 | 3/2 | ⏱️ oui |
|  | v2 | 85s | 100 | 0 | 100 | 50 | **15** | 0 | 7/8 | ⏱️ oui |

## Recouvrement v1 ↔ v2 (articles retenus)

| Requête | Retenus v1 | Retenus v2 | Communs | Jaccard | Temps v1→v2 |
|---|--:|--:|--:|--:|--:|
| Inhibiteurs du SGLT2 dans l'insuffisance | 19 | 22 | 6 | 0.171 | 75s → 93s |
| Efficacité du sémaglutide oral dans le d | 2 | 16 | 2 | 0.125 | 67s → 80s |
| Dépistage du cancer du col de l'utérus p | 10 | 30 | 8 | 0.25 | 45s → 78s |
| Prise en charge de la dégénérescence mac | 7 | 30 | 7 | 0.233 | 53s → 103s |
| Antibiothérapie de la pneumonie aiguë co | 8 | 27 | 6 | 0.207 | 50s → 118s |
| Anticoagulation et risque hémorragique d | 12 | 42 | 12 | 0.286 | 46s → 94s |
| Corticoïdes dans le traitement de la COV | 2 | 10 | 1 | 0.091 | 55s → 85s |
| Immunothérapie adjuvante dans le mélanom | 5 | 15 | 4 | 0.25 | 46s → 85s |

## Agrégats (moyennes)

| Mesure | v1 | v2 |
|---|--:|--:|
| Temps moyen | 54.5s | 92.1s |
| PubMed récupérés (moy.) | 12.0 | 100.0 |
| Candidats fusionnés (moy.) | 36.8 | 100.0 |
| Retenus (moy.) | 8.1 | 24.0 |
| dont local-seul (moy.) | 1.9 | 0.0 |
| Tokens codex (moy.) | 59843.0 | 71365.8 |

## Lecture (à valider par des médecins)

- **Temps** : mesuré ci-dessus, dominé par les 2 appels Codex (requête + jugement).
- **Rappel du local** : `dont local-seul` = articles retenus présents UNIQUEMENT dans notre base (invisibles de la fenêtre PubMed). C'est l'axe où v2 est censée battre v1.
- **Jaccard v1↔v2** : proche de 1 = les deux versions renvoient la même chose ; bas = elles divergent (et il faut un médecin pour dire laquelle a raison).

> ⚠️ Ce benchmark chiffre le COMPORTEMENT (vitesse, volumes, recouvrement, provenance). Il **ne juge pas la pertinence clinique** : seul un médecin, en aveugle, peut dire si les articles retenus sont les bons. C'est l'étape suivante.
