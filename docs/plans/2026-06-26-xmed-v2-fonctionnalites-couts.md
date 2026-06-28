# X-Med V2 — Plan produit et évaluation des coûts

> **Pour Hermes :** utiliser ce document comme base produit/technique avant d’implémenter les nouvelles fonctionnalités. Le but n’est pas de coder tout de suite, mais de cadrer la valeur, les coûts et le périmètre testable pour une mise entre les mains de médecins en septembre.

**Date :** 2026-06-26  
**Source :** échange Eva + schéma manuscrit + retour devis/prestataire  
**Horizon cible :** construire en juillet-août, test médecins en septembre après les vacances.

---

## 1. Décision produit issue de l’échange

Le retour principal est que le produit est pertinent, mais que la valeur perçue augmente fortement si X-Med ne reste pas seulement un outil de recherche d’articles.

La proposition cible devient une suite de **5 fonctionnalités X-Med** :

1. **Recherche** — trouver les articles pertinents à partir d’une question médicale en français.
2. **Traduction** — traduire titre/abstract/article en français.
3. **Audio** — écouter un résumé ou un article traduit.
4. **Résumé** — produire un résumé clinique structuré.
5. **Critique** — produire une lecture critique d’un article ou comparer plusieurs articles.

La fonctionnalité qui semble créer le plus de valeur différenciante est la **lecture critique** :
- ce qui est solide ;
- ce qui est faible ;
- biais / limites méthodologiques ;
- qualité du design ;
- taille d’effet et applicabilité clinique ;
- conclusion pratique pour un médecin.

---

## 2. Schéma fonctionnel cible

### Parcours médecin cible

```text
Question médicale
  ↓
Recherche X-Med
  ↓
Liste d’articles pertinents
  ↓
Sélection de 1 à 3 articles
  ↓
Actions IA disponibles :
  - Traduire
  - Résumer
  - Générer audio
  - Lecture critique
  - Comparer les 3 articles
  ↓
Sortie exploitable : synthèse médicale + limites + décision de lecture
```

### Interface cible côté utilisateur

Ajouter une logique de sélection d’articles :

```text
[ ] Article A
[ ] Article B
[ ] Article C

Actions :
[Traduire] [Audio] [Résumé] [Critique] [Comparer]
```

La comparaison doit permettre de sélectionner jusqu’à **3 articles** et de demander :
- lequel est le plus robuste ;
- ce que chaque article apporte ;
- où les conclusions divergent ;
- quelle conclusion clinique prudente peut être retenue.

---

## 3. MVP recommandé pour septembre

Objectif : ne pas construire une plateforme complète avant validation. Construire le minimum utile pour tester la valeur auprès de médecins.

### MVP septembre — contenu

- Recherche PubMed/X-Med existante consolidée.
- Sélection de 1 à 3 articles depuis les résultats.
- Bouton **Résumé** pour 1 article.
- Bouton **Traduction** pour 1 article.
- Bouton **Lecture critique** pour 1 article.
- Bouton **Comparer** pour 2 ou 3 articles.
- Audio uniquement sur le résumé, pas sur l’article complet au départ.
- Journalisation du coût par requête et par fonctionnalité.
- Bouton feedback médecin : utile / pas utile / commentaire.

### Hors MVP septembre

À repousser après validation :
- lecture audio d’articles complets longs ;
- parsing PDF full-text complexe ;
- comptes utilisateurs complets et paiement ;
- recommandations automatiques proactives par spécialité ;
- personnalisation fine par profil médecin ;
- intégration hospitalière ou dossier patient.

---

## 4. Plan d’implémentation juillet-août

### Phase 0 — Cadrage coût et données, 2 à 3 jours

**Objectif :** mesurer le coût réel de chaque action IA avant de généraliser.

Actions :
- Ajouter un modèle de logs `ai_usage_events` ou un fichier de logs JSONL si plus rapide.
- Stocker pour chaque appel : fonctionnalité, modèle, provider, tokens input/output/cache, durée, coût estimé, nombre d’articles.
- Définir 20 requêtes médicales représentatives sur gynéco, ophtalmo, médecine générale, dermato, cardio.
- Mesurer coût réel sur : recherche, résumé, traduction, critique, comparaison.

Livrable : tableau coût moyen par action.

### Phase 1 — Sélection multi-articles, 3 à 5 jours

**Objectif :** permettre au médecin de sélectionner 1 à 3 articles depuis les résultats.

Frontend :
- Ajouter checkbox sur chaque résultat.
- Afficher un bandeau “1/3 articles sélectionnés”.
- Désactiver la comparaison si moins de 2 articles ou plus de 3.

Backend :
- Endpoint pour récupérer le détail complet des articles sélectionnés par PMID.

### Phase 2 — Résumé + traduction, 5 à 7 jours

**Objectif :** fournir les deux fonctions les plus simples et utiles.

Fonctions :
- Résumé clinique structuré : contexte, méthode, résultats, conclusion, intérêt pratique.
- Traduction française : titre + abstract, éventuellement full text si disponible plus tard.

Optimisation coût :
- Cache par PMID + langue + modèle + version de prompt.
- Ne jamais regénérer si le même résumé existe déjà.

### Phase 3 — Lecture critique article unique, 7 à 10 jours

**Objectif :** créer la fonctionnalité à forte valeur médicale.

Sortie structurée :
- Question clinique adressée.
- Type d’étude et niveau de preuve.
- Population / intervention / comparateur / outcome si détectable.
- Points forts.
- Limites / biais.
- Résultats principaux.
- Applicabilité clinique.
- Ce qu’un médecin doit retenir.
- Niveau de confiance : faible / modéré / élevé.

Garde-fou :
- Mention explicite : synthèse d’aide à la lecture, ne remplace pas le jugement médical.

### Phase 4 — Comparaison de 2 à 3 articles, 7 à 10 jours

**Objectif :** comparer plusieurs articles sur une même question.

Sortie structurée :
- Tableau comparatif : design, population, taille, intervention, outcome, résultat, limites.
- Points de convergence.
- Points de divergence.
- Article le plus robuste et pourquoi.
- Conclusion clinique prudente.
- Questions restantes.

Optimisation coût :
- Réutiliser les critiques individuelles déjà mises en cache.
- Pour comparer, envoyer au modèle les critiques structurées plutôt que les abstracts complets si disponibles.

### Phase 5 — Audio résumé, 3 à 5 jours

**Objectif :** permettre au médecin d’écouter le résumé.

Version MVP :
- Générer audio uniquement à partir du résumé ou de la critique courte.
- Stocker le fichier audio par PMID + langue + version.
- Éviter audio full article au départ car coût et durée augmentent vite.

### Phase 6 — Beta médecins, septembre

**Objectif :** tester la valeur perçue.

Panel cible :
- 10 à 20 médecins.
- Plusieurs spécialités : gynéco, ophtalmo, cardio, dermato, médecine générale, chirurgie si possible.

Mesures :
- recherche utile ?
- résumé fiable ?
- critique réellement utile ?
- gain de temps estimé ?
- confiance dans les réponses ?
- fonctionnalité la plus utilisée ?
- seuil de prix acceptable ?

---

## 5. Plan pour évaluer le coût

### 5.1 Unité économique à mesurer

Chaque action doit produire une ligne de coût :

```text
coût_total = coût_input + coût_output + coût_cache + coût_TTS + coût_infra
```

À mesurer par fonctionnalité :

| Fonction | Driver principal de coût | Cache possible ? | Risque coût |
|---|---|---:|---:|
| Recherche | construction requête + jugement articles | partiel | élevé si beaucoup d’abstracts jugés |
| Traduction | longueur abstract/article | oui | moyen |
| Résumé | longueur abstract/article | oui | moyen |
| Critique | longueur article + complexité prompt | oui | élevé |
| Comparaison | nombre d’articles × longueur | oui | élevé |
| Audio | longueur texte généré | oui | faible à moyen |

### 5.2 Instrumentation minimale

Ajouter une structure de log type :

```json
{
  "timestamp": "2026-06-26T12:00:00Z",
  "feature": "critical_appraisal",
  "model": "gpt-5.4 / claude / autre",
  "pmids": ["..."],
  "article_count": 1,
  "input_tokens": 12000,
  "cached_input_tokens": 2000,
  "output_tokens": 1800,
  "latency_seconds": 18.4,
  "estimated_cost_eur": 0.0,
  "cache_hit": false
}
```

Au départ, stocker en JSONL suffit : `logs/ai_usage_events.jsonl`. Ensuite seulement, passer en table SQL.

### 5.3 Scénarios à calculer

Calculer le coût mensuel selon 4 scénarios :

1. **Prototype interne** : 1 à 3 utilisateurs, 20 recherches/jour.
2. **Beta médecins** : 20 médecins, 5 actions IA/jour/médecin.
3. **Petit SaaS** : 100 médecins, 3 actions IA/jour/médecin.
4. **Usage intensif** : 100 médecins, 10 actions IA/jour/médecin.

Pour chaque scénario :
- coût par recherche ;
- coût par résumé ;
- coût par critique ;
- coût par comparaison 3 articles ;
- coût audio ;
- coût total jour/mois ;
- marge si abonnement à 29€, 49€, 99€, 199€/mois.

### 5.4 Politique produit anti-explosion des coûts

À intégrer dès le MVP :

- Limiter la recherche IA à 50 abstracts jugés par défaut.
- Bouton “analyser 50 de plus” avec coût suivi.
- Cache obligatoire par PMID pour traduction/résumé/critique.
- Comparaison basée sur critiques cachées quand possible.
- Quotas par utilisateur beta.
- Afficher côté admin : coût moyen par médecin et par session.
- Tester des modèles moins chers pour tâches simples : traduction, résumé court, extraction PICO.
- Garder modèle premium uniquement pour lecture critique et comparaison.

---

## 6. Questions ouvertes à trancher

1. Le devis couvre-t-il seulement le développement UI/backend, ou aussi les coûts API en production ?
2. Lecture critique sur abstract seulement ou full text quand disponible ?
3. Quelle granularité de critique est attendue par les médecins : courte, détaillée, ou checklist type CASP/CONSORT/STROBE ?
4. Faut-il citer directement les passages de l’abstract pour justifier la critique ?
5. Le test septembre doit-il être gratuit, ou limité avec compteur d’usage ?
6. Quelle promesse commerciale : “trouver les articles”, “gagner du temps”, “lecture critique augmentée”, ou “assistant de veille médicale” ?

---

## 7. Recommandation stratégique

Ne pas vendre X-Med comme un simple moteur de recherche PubMed. La proposition de valeur la plus forte est :

> **X-Med aide les médecins à trouver, comprendre et critiquer rapidement la littérature médicale pertinente.**

La recherche seule est utile, mais probablement copiable. La combinaison **recherche + résumé + traduction + audio + lecture critique + comparaison** crée un produit plus défendable, plus visible et plus directement testable auprès de médecins.

---

## 8. Livrables attendus avant septembre

- Prototype web utilisable.
- 5 fonctionnalités accessibles depuis les résultats : recherche, traduction, audio, résumé, critique.
- Comparaison de 2 à 3 articles.
- Logs de coût par fonctionnalité.
- Dashboard simple de coût / usage.
- Questionnaire beta médecins.
- Liste de médecins testeurs par spécialité.
- Synthèse de feedback après 2 semaines d’usage.
