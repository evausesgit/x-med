# X-Med — Votre assistant de veille médicale personnalisé

## Le problème que X-Med résout

En médecine, rester à jour est une obligation professionnelle. Mais c'est devenu presque impossible à faire seul.

Chaque jour, PubMed publie entre 2 000 et 4 000 nouveaux articles scientifiques. Sur l'année, c'est plus d'un million de publications. Aucun médecin ne peut surveiller ça manuellement. Les alertes email existantes (PubMed, Google Scholar) envoient trop d'articles, sans tri, sans résumé, sans traduction — et finissent ignorées.

**X-Med résout ce problème** : il lit PubMed à votre place, trie ce qui vous concerne vraiment, le résume en français, et vous l'envoie sous une forme lisible en quelques minutes.

---

## Ce que X-Med fait concrètement

### 1. Veille automatique quotidienne
Chaque matin, X-Med récupère tous les nouveaux articles publiés la veille sur PubMed. Il les analyse selon votre profil et ne vous envoie que ceux qui correspondent à votre pratique.

### 2. Filtrage intelligent par profil
X-Med ne filtre pas seulement par spécialité. Il tient compte de l'ensemble de votre profil :

- Votre spécialité principale et vos sous-spécialités
- Les pathologies que vous suivez en consultation
- Les traitements ou molécules qui vous intéressent
- Les types d'études que vous préférez (essais randomisés, méta-analyses, revues systématiques, études de cohorte, recommandations de sociétés savantes…)
- Le niveau de preuve attendu (études de phase III, niveau I/II uniquement, etc.)
- Les revues que vous considérez comme références dans votre domaine

### 3. Résumés clairs et synthétiques
Pour chaque article sélectionné, X-Med génère un résumé structuré en français :
- L'objectif de l'étude en une phrase
- La méthode et la population étudiée
- Les résultats principaux
- La conclusion et son impact clinique potentiel

Ce résumé vous permet de décider en 30 secondes si vous souhaitez lire l'article complet.

### 4. Traduction dans votre langue
Les articles médicaux sont publiés en anglais. X-Med traduit automatiquement les résumés dans votre langue natale — français, arabe, espagnol, portugais ou autre — sans déformer le sens clinique.

### 5. Classement par priorité
X-Med identifie les articles les plus importants pour vous. Une méta-analyse dans votre revue de référence sur une pathologie que vous traitez chaque semaine sera mise en avant. Un article de recherche fondamentale sur un sujet périphérique sera classé plus bas.

### 6. Alertes personnalisées
Vous pouvez définir des alertes spécifiques : "Je veux être notifié immédiatement dès qu'une étude sur la fibrillation atriale et les nouveaux anticoagulants est publiée dans le NEJM ou le Lancet."

### 7. Recherche ponctuelle dans PubMed
En dehors de la veille automatique, vous pouvez interroger PubMed directement depuis X-Med avec des filtres avancés, et obtenir des résultats déjà résumés et traduits.

---

## Ce que vous recevez — exemple de digest quotidien

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
X-Med · Mardi 26 mai 2026
Dr Martin — Cardiologie · 4 articles aujourd'hui
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⭐ PRIORITAIRE

1. Efficacité d'un nouvel anticoagulant oral dans la FA
   non valvulaire : essai contrôlé randomisé multicentrique

   New England Journal of Medicine · Mai 2026
   Dupont A, Martin B, Cohen R et al. — 4 200 patients

   TYPE D'ÉTUDE : Essai contrôlé randomisé (Phase III)
   NIVEAU DE PREUVE : I

   RÉSUMÉ
   Objectif : Comparer XYZ à l'apixaban chez des patients
   en fibrillation atriale non valvulaire à risque modéré-élevé.
   Méthode : 4 200 patients randomisés sur 24 mois dans
   18 pays. Critère principal : AVC ou embolie systémique.
   Résultats : XYZ démontre la non-infériorité avec un taux
   de saignements majeurs significativement plus faible (1,2%
   vs 2,1%, p<0,01).
   Impact clinique : Potentiel de modification des pratiques
   pour les patients à risque hémorragique élevé.

   [Lire l'article →]  [Accès libre PMC →]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. Revue systématique : ablation par cathéter vs traitement
   médical dans l'insuffisance cardiaque avec FA

   European Heart Journal · Mai 2026
   TYPE D'ÉTUDE : Méta-analyse (12 essais, 3 800 patients)
   NIVEAU DE PREUVE : I

   [Résumé →]  [Article →]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3–4. [Autres articles · Cardiologie générale]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Voir tous les articles →]  [Modifier mon profil →]
```

---

## Votre profil — ce que nous configurons ensemble

| Paramètre | Exemples |
|---|---|
| Spécialité principale | Cardiologie |
| Sous-spécialités | Rythmologie, Insuffisance cardiaque |
| Pathologies suivies | FA, STEMI, IC à FE réduite |
| Traitements d'intérêt | Anticoagulants, ICD, resynchronisation |
| Types d'études préférés | RCT, méta-analyses, recommandations ESC/AHA |
| Niveau de preuve minimum | Niveau I et II uniquement |
| Revues de référence | NEJM, Lancet, European Heart Journal, Circulation |
| Fréquence | Quotidien / Hebdomadaire |
| Langue de réception | Français |

Ce profil est entièrement modifiable à tout moment.

---

## D'où viennent les articles ?

La source unique est **PubMed / MEDLINE**, la base de référence mondiale en médecine scientifique, gérée par la **NLM (National Library of Medicine)** aux États-Unis.

- Plus de **37 millions d'articles** référencés
- Plus de **5 000 revues médicales** indexées
- Mise à jour **quotidienne** par la NLM
- Indexation par termes MeSH standardisés et validés

X-Med télécharge directement les flux officiels NLM chaque jour. Il n'y a pas d'intermédiaire entre PubMed et vous.

---

## Ce que X-Med ne remplace pas

- X-Med n'est **pas un outil de diagnostic** — il informe, il ne prescrit pas
- X-Med ne **garantit pas l'exhaustivité** — il couvre les articles indexés dans PubMed, pas la littérature grise
- L'accès au **texte intégral** dépend de votre institution (certains articles sont en open access, d'autres sont derrière abonnement)
- X-Med **ne se substitue pas** à votre jugement clinique ou à une revue de littérature systématique

---

## Ce que nous vous demandons pour commencer

**Étape 1 — Remplir le formulaire de profil** (15 minutes)
Spécialité, sous-spécialités, pathologies, types d'études, revues de référence, langue, fréquence.

**Étape 2 — Recevoir votre premier digest**
Dans les 24h suivant la configuration, vous recevez votre premier digest.

**Étape 3 — Nous donner vos retours**
Après 2 semaines : quels articles étaient pertinents ? Lesquels non ? Ces retours nous permettent d'affiner votre profil et d'améliorer le système pour tous.

---

## Spécialités disponibles au lancement pilote

Cardiologie · Oncologie · Neurologie · Pneumologie · Infectiologie · Endocrinologie · Rhumatologie · Gastro-entérologie · Néphrologie · Hématologie

D'autres spécialités sont ajoutées sur demande en moins d'une semaine.

---

*X-Med est un projet en phase pilote. Vos retours sont essentiels pour construire un outil vraiment utile à votre pratique.*
*Pour toute question : [contact]*
