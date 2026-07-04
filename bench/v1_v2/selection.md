# Passage contrôlé — sélection des candidats (v1 vs v2, sans Codex-juge)

_Fenêtre 2025-01-01 → 2026-07-04 · local timeout généreux 120s · lot de 50._

« local-seul dans le lot » = articles de NOTRE base (absents de la fenêtre PubMed) qui entrent dans les 50 candidats jugés. C'est le rappel local que chaque méthode apporte **quand le local n'est pas coupé**.

| Requête | PubMed | Local (complet) | temps local | v1 local-seul /50 | v2 local-seul /50 |
|---|--:|--:|--:|--:|--:|
| Inhibiteurs du SGLT2 dans l'insuffisan | 100 | 200 | 31.0s | 38 | 9 |
| Efficacité du sémaglutide oral dans le | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Dépistage du cancer du col de l'utérus | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Prise en charge de la dégénérescence m | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Antibiothérapie de la pneumonie aiguë  | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Anticoagulation et risque hémorragique | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Corticoïdes dans le traitement de la C | 100 | 0 ⚠️>timeout | 120.1s | 0 | 0 |
| Immunothérapie adjuvante dans le mélan | 81 | 0 ⚠️>timeout | 120.1s | 0 | 0 |

**Total local-seul dans le lot (8 req.) : v1 = 38 · v2 = 9 (Δ = -29).**

Rappel : en **production (garde-fou 8 s)**, le local est coupé sur la quasi-totalité de ces requêtes → local-seul jugé = **0** des deux côtés. Ce tableau montre donc à la fois (a) l'écart de conception v1↔v2 et (b) ce que le garde-fou 8 s fait perdre aujourd'hui.
