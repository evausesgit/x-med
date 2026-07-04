# Benchmark v1 vs v2 — Recherche PubMed + IA — Synthèse

_Généré le 2026-07-04. Fenêtre 2025-01-01 → 2026-07-04. 8 requêtes cliniques FR jouées via la vraie fonction de production `_run_deep_search` (aucun endpoint HTTP, aucune notif)._

## Ce qui est comparé

Rappel : **v1 et v2 n'existent plus comme deux pipelines séparés**. Ce sont deux **réglages du sélecteur de candidats** de l'unique méthode « deep » (esearch PubMed → filtre local FTS → jugement codex). Le tri final est **toujours** le score codex ; v1/v2 ne changent que *quels* articles sont soumis au jugement.

| | v1 « score IA » | v2 « fusion RRF » |
|---|---|---|
| `k_pubmed` (candidats PubMed) | **12** | **100** |
| Fusion PubMed + local | PubMed d'abord | **RRF** (rang réciproque, pour ne pas enterrer le local) |
| Lot jugé par codex | 50 | 50 |
| Communs | `max_local=200`, `min_score=2` | idem |

## Le résultat qui change tout : le vivier local ne répond jamais

Sur **les 8 requêtes**, le garde-fou local (8 s en prod) a **coupé la recherche locale** → `local = 0` candidats partout, donc `local-seul = 0` partout.

J'ai relancé 3 requêtes avec le garde-fou **relevé à 60 s** : le local est **encore coupé** (`local = 0`), la recherche prend juste ~40 s de plus pour rien.

Diagnostic direct en base : un **simple `COUNT`** de la requête locale (une dizaine de mots-clés en `OR`, sans même le tri `ts_rank` ni de `LIMIT`) **dépasse 150 s** sur le miroir de 25 M articles avant d'être annulé.

**Conséquence** : pour des sujets cliniques réalistes, les mots-clés générés par codex forment un `OR` de 20-30 termes (synonymes, molécules, sels) qui matche **des millions** de lignes ; `ts_rank` doit toutes les trier. La base locale est donc, en pratique, **muette** sur ce type de requêtes — exactement le mode d'échec que le code redoutait déjà pour le MeSH.

> Donc l'axe sur lequel v2 est censée battre v1 (**repêcher des articles présents seulement dans notre base**) **n'a jamais pu jouer** dans ce benchmark. Aujourd'hui, la différence v1 vs v2 se réduit à *« codex juge-t-il 12 ou 100 candidats PubMed ? »*.

## Résultats chiffrés (run principal, garde-fou 8 s = prod)

| Requête | Retenus v1 | Retenus v2 | Communs | Jaccard | Temps v1 → v2 |
|---|--:|--:|--:|--:|--:|
| SGLT2 / IC-FEp | 3 | 13 | 3 | 0.23 | 89 → 93 s |
| Sémaglutide oral / DT2 | 1 | 18 | 1 | 0.06 | 39 → 89 s |
| Dépistage HPV col utérus | 9 | 34 | 9 | 0.27 | 39 → 91 s |
| DMLA néovasculaire | 9 | 30 | 9 | 0.30 | 45 → 90 s |
| Pneumonie communautaire | 6 | 21 | 5 | 0.23 | 46 → 76 s |
| Anticoagulation / FA | 12 | 36 | 12 | 0.33 | 45 → 85 s |
| Corticoïdes COVID sévère | 1 | 11 | 0 | 0.00 | 58 → 80 s |
| Immunothérapie mélanome III | 5 | 17 | 4 | 0.22 | 48 → 89 s |

**Moyennes**

| Mesure | v1 | v2 |
|---|--:|--:|
| Temps moyen | **51 s** | **87 s** (+70 %) |
| Candidats jugés | 12 | 50 |
| Retenus (moy.) | **5,8** | **22,5** (×3,9) |
| dont local-seul | 0 | 0 |
| Tokens codex (moy.) | 58 000 | 80 000 (+38 %) |

## Lecture franche

1. **v2 retient ~4× plus d'articles** (5,8 → 22,5) parce qu'elle en **juge 4× plus** (12 → 50). Mécanique, pas magique.
2. **Recouvrement faible (Jaccard ~0,06–0,33)** : v2 ne « raffine » pas la liste de v1, elle l'**élargit**. Les retenus de v1 sont presque tous inclus dans v2 (colonne « Communs » ≈ « Retenus v1 »), plus une longue traîne de nouveaux.
3. **Cette traîne penche vers le score 2** (« pertinent » sans plus), pas le score 3 (« très pertinent »). Ex. dépistage HPV : v2 ajoute surtout du 2 (11×s3 / 23×s2 vs 7/2 pour v1). Donc v2 = **plus de rappel, précision en moyenne plus basse**.
4. **Coût** : +70 % de latence et +38 % de tokens codex par recherche. Non négligeable à l'échelle.
5. **Le local est inerte.** Le vrai argument de vente de v2 (RRF pour sauver le local) est aujourd'hui **théorique** sur cette machine + ce miroir.

## Ce que ça implique (décisions à prendre)

- **Ce benchmark ne tranche PAS la pertinence clinique.** Il mesure le comportement (volumes, temps, recouvrement, provenance). Pour savoir si les ~17 articles en plus de v2 valent le coup, il faut un **médecin en aveugle** sur un échantillon v1-seul / v2-seul.
- **Choix v1 vs v2 = curseur rappel/précision/coût**, rien de plus tant que le local est muet : v2 si on préfère « ne rien rater » (quitte à trier plus de score-2 et payer +70 % de temps) ; v1 si on préfère une short-list serrée et rapide.
- **Le vrai chantier n'est ni v1 ni v2, c'est le pré-filtre local.** Tant qu'un `OR` de 25 mots-clés met >150 s à 25 M lignes, RRF n'a rien à fusionner. Pistes : borner le nombre de mots-clés envoyés au FTS, requête FTS en `AND`/phrases plutôt que `OR` massif, index/partitionnement par année, ou pré-filtre sémantique (pgvector) sur le sous-ensemble récent au lieu du FTS plein-corpus. **À creuser séparément.**

## Fichiers

- `report.md` — rapport auto complet (run principal, 8 requêtes).
- `results.json` — mesures brutes du run principal.
- `local_ext/results.json` — run étendu (garde-fou 60 s, 3 requêtes) montrant que le local reste coupé.
