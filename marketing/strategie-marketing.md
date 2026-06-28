# X-Med — Stratégie marketing

> Plan en 3 phases (source : brainstorm initial), suivi de notes critiques et des
> décisions prises pour l'exécution. Voir aussi `linkedin-page-profile.md` et
> `automatisation-linkedin.md`.

## Positionnement central

Ne pas vendre « une IA médicale » (marché saturé). Vendre :

> **Une plateforme qui transforme la littérature scientifique en décisions
> exploitables pour les médecins, les laboratoires et les investisseurs.**

Slogan de pitch : *X-Med — The Bloomberg Terminal for Medical Intelligence.*

Cibles : médecins spécialistes · Medical Affairs Pharma · investisseurs biotech · fonds santé.

---

## Phase 1 — Devenir visible (0 → 100 clients)

Objectif : être identifié comme une référence en intelligence médicale.

### LinkedIn (priorité absolue) — 1 post/jour, 30 jours, 30 sujets

**Format 1 — What does the science really say?**
> Ex : *Do GLP-1 drugs increase kidney stone risk?*
> 1 question · 5 études analysées · 3 conclusions · lien vers X-Med

**Format 2 — Medical Myth of the Week**
> Ex : *Does Ozempic cause depression?*

**Format 3 — X-Med Research Brief**
> Ex : *We analyzed 12,457 publications on Alzheimer's disease. Top 5 findings.*

## Phase 2 — Générer des leads (100 → 1 000 utilisateurs)

Landing pages spécialisées (démo + cas d'usage + témoignage + formulaire) :
- **X-Med for Physicians** — "Get evidence-based answers in minutes"
- **X-Med for Pharma** — "Accelerate medical intelligence"
- **X-Med for Investors** — "Perform scientific due diligence at AI speed"

## Phase 3 — Autorité scientifique

- **Livre blanc trimestriel** (ex : *State of GLP-1 Research 2026*, 50 pages, 500 études) — téléchargement contre email.
- **Newsletter hebdo « X-Med Weekly »** : 5 études importantes · 3 essais cliniques · 1 controverse.
- **Démo virale** : vidéo « PubMed vs X-Med » (chrono 45 min vs 45 s).
- **Programme ambassadeurs** : 10 médecins + 5 chercheurs + 5 investisseurs (accès gratuit + visibilité contre feedback/témoignages).
- **Conférences** (plus tard, coûteux) : Viva Technology, BIO International, DIA, ISPOR.

## KPI 6 mois (cible initiale — optimiste)

| Mois | Objectif |
|---|---|
| 1 | 30 posts LinkedIn · 500 abonnés |
| 2 | 100 utilisateurs |
| 3 | 500 utilisateurs |
| 4 | 1er livre blanc |
| 5 | 10 ambassadeurs |
| 6 | 1 000 utilisateurs qualifiés |

---

## Notes critiques (à garder en tête)

- **Un seul persona en Phase 1** : médecins spécialistes (cœur produit, ton le plus crédible). Pharma/investisseurs en Phase 2 avec les landing pages dédiées. Mélanger les 3 d'emblée dilue le message.
- **Risque médico-légal / crédibilité = priorité n°1.** Les titres type « Does Ozempic cause depression? » avec « 3 conclusions » sont du contenu santé sensible. Un spécialiste repère une simplification abusive → perte d'autorité. Règle non négociable, câblée dans le générateur de posts : citer les études (PMID/DOI), distinguer association/causalité, **jamais de conseil clinique**, disclaimer systématique.
- **Dogfooding** : le contenu des posts sort de **vraies recherches X-Med** (authenticité + preuve produit + zéro invention). C'est implémenté (voir `automatisation-linkedin.md`).
- **KPI optimistes** : 1 000 utilisateurs en 6 mois via LinkedIn organique seul est agressif. Les conférences sont chères et tardives → hors Phase 1.
- **Meilleur asset du plan** : la vidéo « PubMed vs X-Med ». Une démo chronométrée vaut 100 posts.

## Décisions d'exécution actées (2026-06-20)

- Page **entreprise** X-Med (pas profil perso).
- Posts **bilingues FR + EN**.
- Mode **brouillon → validation humaine** (rien n'est publié automatiquement).
- Canal de réception du brouillon : **Telegram via Hermes**.
- Source de contenu : **recherches X-Med réelles**.
- Cadence : **1 post/jour, 6h00**, cron local.

## Ce que je ferais dès lundi (checklist de lancement)

1. [ ] Créer la page entreprise LinkedIn (cf. `linkedin-page-profile.md`).
2. [ ] Logo + bannière (« PubMed vs X-Med » / chrono 45 min vs 45 s).
3. [ ] Publier le 1er post (généré automatiquement, déjà envoyé sur Telegram).
4. [ ] Produire la vidéo « PubMed vs X-Med ».
5. [ ] Lister 50 investisseurs biotech + 50 responsables Medical Affairs à contacter en direct.
6. [ ] Préparer la newsletter « X-Med Weekly ».
