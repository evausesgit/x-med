# X-Med — Veille médicale automatisée

## Le problème

Chaque jour, PubMed publie des centaines de nouveaux articles scientifiques. Un médecin ne peut pas surveiller manuellement les publications dans sa spécialité. Les alertes PubMed existantes sont génériques, peu lisibles, et arrivent en masse sans tri intelligent.

---

## Ce que fait X-Med

X-Med est un système de veille automatique qui vous envoie chaque matin un résumé des articles publiés la veille, sélectionnés selon vos spécialités d'intérêt.

**Vous recevez un email quotidien contenant :**

- Le titre de chaque nouvel article pertinent
- Son résumé (abstract) complet
- Le journal de publication et la date
- Les auteurs
- Un lien direct vers l'article complet (gratuit quand disponible)

---

## D'où viennent les articles ?

La source est **PubMed / MEDLINE**, la base de données de référence mondiale en médecine, gérée par la **NLM (National Library of Medicine, NIH)**.

Elle contient plus de 37 millions d'articles issus de plus de 5 000 revues médicales. Chaque jour, 2 000 à 4 000 nouveaux articles y sont ajoutés.

Les articles sont indexés par des termes médicaux standardisés appelés **MeSH (Medical Subject Headings)** — ce sont ces termes que X-Med utilise pour filtrer les articles selon votre spécialité.

---

## Comment est fait le tri ?

Chaque spécialité est associée à une liste de termes MeSH précis. Par exemple :

**Cardiologie →** `Heart Diseases`, `Myocardial Infarction`, `Arrhythmias`, `Heart Failure`, `Atrial Fibrillation`…

**Neurologie →** `Stroke`, `Parkinson Disease`, `Alzheimer Disease`, `Multiple Sclerosis`…

Quand un nouvel article est indexé avec un de ces termes, il est automatiquement ajouté à votre digest du lendemain.

Vous pouvez vous abonner à **plusieurs spécialités**. Vous ne recevez **jamais deux fois le même article**.

---

## Ce que vous recevez — exemple d'email

```
─────────────────────────────────────────────
X-Med · Votre veille du 25 mai 2026
Cardiologie · 3 nouveaux articles
─────────────────────────────────────────────

1. Efficacy of a novel oral anticoagulant in non-valvular
   atrial fibrillation: a randomized controlled trial

   Journal : New England Journal of Medicine · Mai 2026
   Auteurs : Dupont A, Martin B, Cohen R et al.

   RÉSUMÉ
   Background: [...] We evaluated the efficacy and safety
   of XYZ compared to apixaban in 4 200 patients...
   Conclusion: XYZ demonstrated non-inferiority with a
   significantly lower rate of major bleeding events (p<0.01).

   [Lire l'article complet →]  [PubMed →]

─────────────────────────────────────────────
2. ...
```

---

## Ce que nous vous demandons

Pour configurer votre profil, nous avons besoin de :

1. **Votre adresse email**
2. **Vos spécialités d'intérêt** (liste ci-dessous)
3. **Des retours au fil du temps** : est-ce que les articles proposés sont pertinents ? Y a-t-il des sujets à ajouter ou retirer ?

### Spécialités disponibles au lancement

- Cardiologie
- Oncologie
- Neurologie
- Pneumologie
- Infectiologie
- Endocrinologie / Diabétologie
- Rhumatologie

D'autres spécialités peuvent être ajoutées rapidement sur demande.

---

## Ce que X-Med ne fait pas

- X-Med ne résume pas les articles avec une IA — vous lisez le vrai abstract, écrit par les auteurs
- X-Med n'a pas accès aux articles sous abonnement payant — il fournit un lien vers l'article, l'accès dépend de votre institution
- X-Med ne remplace pas une revue systématique ou une veille exhaustive — il couvre les nouveaux articles indexés dans PubMed

---

## Prochaines étapes

| Étape | Description |
|---|---|
| **1. Inscription** | Vous communiquez vos spécialités d'intérêt |
| **2. Lancement pilote** | Vous recevez votre premier digest |
| **3. Retours** | Vous nous signalez ce qui est pertinent ou non |
| **4. Affinage** | On ajuste les termes de filtrage selon vos retours |

---

*X-Med est un projet en développement. Pour toute question, contactez l'équipe.*
