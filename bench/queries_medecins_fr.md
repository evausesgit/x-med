# Questions collectées auprès des médecins testeurs (gold set FR)

Source des requêtes réelles pour la calibration de la pertinence (cf. PLAN_EVAL.md).
À injecter dans `/annotate` (table `eval_pool`) quand l'embedding 2025-2026 sera terminé,
puis notation 0/1/2 par les médecins → calage des seuils sémantiques.

## Ophtalmologie

1. Je voudrais une rétrospective de toutes les études et cas publiés d'accident vasculaire cérébral ischémique par vasospasme ou embolie graisseuse sur lipofilling facial.
   - test live (bge-m3) : top 0.567 — « Severe Ophthalmologic Complications Following Plastic and Cosmetic Procedures » (2025), pile sujet ; reste = bruit. Sujet très niche.

## Gynécologie-obstétrique

1. Effets du relugolix (« regulolix ») sur la prise en charge de l'endométriose.
   - top 0.601 — elagolix add-back (même classe) ; trouve aussi relugolix (fibromes). Bon.
2. Impact des anti-adhérentiels dans la diminution du risque de synéchie en hystéroscopie.
   - top 0.553 — intrauterine adhesions (pertinent) puis bruit. Faible.
3. Alcoolisation des endométrioses versus kystectomie.
   - top 0.556 — résultats sur consommation d'alcool/cancer (raté : « alcoolisation » mal compris). Tester en mode Mots-clés.
4. Isthmocèle et risque de rupture utérine.
   - top 0.638 — « Isthmocele: Detection to Treatment » + rupture utérine. Excellent.
5. Impact de la radiofréquence des fibromes sur la fertilité.
   - top 0.614 — RF ablation transvaginale chez patientes infertiles. Très bon.

---
Constat provisoire : bonnes réponses ~0.60-0.64, requêtes ratées ~0.55-0.56 → décrochage vers ~0.58-0.60.
