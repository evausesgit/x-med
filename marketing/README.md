# marketing/ — Marketing X-Med

Ressources marketing X-Med (Phase 1 : visibilité via LinkedIn).

| Fichier | Contenu |
|---|---|
| [`strategie-marketing.md`](strategie-marketing.md) | Plan en 3 phases, positionnement, KPI, notes critiques, décisions actées |
| [`linkedin-page-profile.md`](linkedin-page-profile.md) | Contenu prêt à coller de la page entreprise LinkedIn (bilingue FR/EN) |
| [`automatisation-linkedin.md`](automatisation-linkedin.md) | Doc technique du générateur de posts quotidiens (cron → Hermes/Telegram) |

## En bref

- **Positionnement** : transformer la littérature scientifique en décisions exploitables (pas « une IA médicale »).
- **Page** : entreprise X-Med · site https://x-med.ia-do-it.com/ · Paris · 2026.
- **Posts** : 1/jour, bilingues FR+EN, issus de vraies recherches X-Med, mode brouillon → validation (Telegram), cron 6h00.
- **Code** : `scripts/linkedin_daily.py`, `app/services/linkedin_post.py`, `scripts/linkedin/topics.json`.
