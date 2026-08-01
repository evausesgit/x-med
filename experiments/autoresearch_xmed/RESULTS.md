# Journal des essais autoresearch X-Med

Branche : `codex/autoresearch-benchmark`. Les artefacts bruts sont locaux et ignorés
par Git car ils peuvent contenir questions, abstracts et sorties de modèles.

| Round | Statut | Porte | Résultat | Décision |
|---:|---|---|---|---|
| 1 | en cours | baseline | Capture durcie q01–q08 sur scope récent : p50 usable **162,5 s**, p50 complet **350,5 s**, **75 916 tokens** moyens, **3/8 timeouts FTS**. Le rapport du 04/07 reste périmé. | qualité/replay exploitables ; performance finale attend le clone complet et q09–q18 |
| 2 | **keep warm** | auto → fidélité | Cache query-builder exact/versionné, 3 questions : cold médian **16,893 s / 15 482 tokens** (16,793–28,526 s), hit médian **0,0002 s / 0 token**, sortie identique. | conserver pour requêtes strictement identiques ; mesurer cold/warm séparément |
| 3 | reject vitesse | auto → fidélité immédiate | Cache `esearch` exact TTL 5 min : cold **0,790 s / 1 appel**, hit **0,0001 s / 0 appel**, mêmes PMID, mais <1 % de la latence E2E. | sous le seuil utilisateur de 10 % ; ne pas ajouter de cache de fraîcheur pour ce seul gain |
| 4 | reject vitesse | auto → fidélité | `esummary + efetch` parallèles : **0,862 → 0,622 s** localement (**−27,8 %**), soit ~0,24 s et <1 % E2E. | sous le seuil de 10 % ; retries/limiteur restent requis si parallélisme futur |
| 5 | reject | auto → fidélité | Trace q01 : esearch **0,60 s**, FTS **77,69 s**, usable **159,01 s**. Même avec chevauchement parfait et zéro overhead, gain maximal usable ~**0,37 %**. | complexité non justifiée sous le seuil de 10 % |
| 6 | reject vitesse | auto → fidélité | q01, 5 replays : prompt/résultats/traductions byte-identiques ; post-traitement **0,741 → 0,203 s**, mais seulement **~0,54 s absolue** sur 318–404 s live. | exact mais très sous le seuil E2E de 10 % ; ne pas promouvoir isolément |
| 7 | reject | auto → fidélité | 20 répétitions AB/BA sur table TEMP : upsert boucle **3,78 ms**, executemany **1,44 ms**, soit **2,34 ms** gagnées face à 403,6 s live. | optimisation décorative, très sous le seuil utilisateur de 10 % |
| 8 | reject actuel | auto → fidélité | Projection SQL byte-identique sur q01, mais médiane replay **0,2031 → 0,2015 s** (~**−0,7 %**) avec une dispersion supérieure au gain. | sous le seuil pré-déclaré de 10 % ; retester éventuellement sur clone complet non projeté |
| 9 | reject vitesse / keep robustesse | auto → fidélité | 4 blocs AB/BA NCBI : réponses exactes, client neuf **0,271 s**, partagé **0,433 s** ; un premier run avait subi un reset TLS non géré. | ne pas promouvoir le singleton pour la vitesse ; intégrer retries bornés + limiteur avec le round 4 |
| 10 | reject actuel | auto | `articles` et `article_search` : **8/8 timeouts à 10 s** avec les mêmes expansions historiques, donc aucune parité top-200 mesurable et aucun gain observé. | ne pas activer la table étroite sur cette preuve |
| 11 | **keep screening / finaliste** | clinical proxy | Contrôle retrieval A-B-A : table complète p50 **75,3 s**, table étroite **23,8 s**, retour table complète **56,5 s** ; **3/8 → 0/8 timeouts**. Sur le pool commun de **634 qrels proxy**, nDCG@10 inchangé (**0,5480**) et Recall@50 **0,4892 → 0,6840**, diversité globale/stratifiée non inférieure sous les deux bornes des inconnus. | seul gain retrieval >10 % thermiquement crédible ; confirmer E2E sur clone complet avant toute promotion |
| 12 | reject vitesse/queue | clinical proxy | Sur `article_search`, `max_local=200 → 50` : p50 **23,8 → 23,2 s** seulement ; mêmes 50 PMID sur 8/8, ordre différent sur 2/8. Les moyennes passent, mais la nouvelle porte pré-déclarée rejette une perte concentrée d'entropie de source dans le pire quartile (**−0,192**, plancher −0,10). | gain sous 10 % et perte de queue ; garder max_local=200 |
| 13 | reject incrémental/queue | clinical proxy | `k_pubmed=32, max_local=100` garde nDCG@10 **0,5480** et Recall@50 **0,6848**. Face au finaliste k=20, le recall ne gagne que **+0,0007** ; la queue échoue sur entropies journal/année et couverture journal, avec **9–12/50** remplacements et uniquement une mesure à cache chaud. | bénéfice trop faible, diversité concentrée en baisse et vitesse froide non démontrée |
| 14 | reject qualité | clinical proxy | `k_pubmed=50, max_local=50` n'a que **20–25/50** articles communs avec k=20 ; Recall@50 atteint **0,5997**, mais la porte échoue sur l'entropie de source globale et dans la strate `broad` (ainsi que l'entropie d'année `broad`). | réduction trop agressive du vivier local ; perte de diversité observée |
| 15 | **keep qualité conditionnel** | clinical proxy | RRF k=60 conserve exactement le même ensemble de 50 PMID sur 8/8 et réordonne seulement : nDCG@10 proxy **0,5480 → 0,6559** (+0,1078 absolu), Recall@50 et diversité non inférieurs. Le p50 chaud n'est pas une preuve de vitesse. | combiner uniquement comme hypothèse qualité avec la table étroite ; l'effet positionnel sur le juge LLM doit encore passer le live apparié |
| 16 | reject no-op | clinical | Le lot k=20 contient déjà exactement **30 locaux-seuls sur 50** pour les 8 requêtes après récupération locale. Tout `local_floor ≤ 30` est donc sans effet ; au-delà il retire des candidats PubMed. | ne pas ajouter de plancher sur ce profil ; réévaluer seulement sur le holdout historique |
| 17 | baseline juge capturée | clinical | Juge prod (`gpt-5.6-terra`, medium) sur 326 articles aveugles : nDCG@10 **0,9443**, P@10 **0,8875**, F1 **0,9276**, p50 **50,18 s**, **33 045 tokens** moyens par requête. | référence fixe des variantes juge ; proxy Sol high, pas vérité clinique |
| 18 | reject pré-écran | clinical | `judge_batch=32` ferait **14 appels séquentiels** au lieu de 9 et augmente déjà le texte total des prompts **473 147 → 479 624 caractères** par répétition. | aucune voie crédible vers −10 % E2E ; ne pas payer 5 appels LLM supplémentaires |
| 19 | reject vitesse | clinical | `head+tail` conserve la même borne de 1 200 caractères et ajoute seulement un séparateur ; aucun gain de tokens ou de latence possible isolément. | peut changer l'information clinique mais ne répond pas à l'objectif d'efficacité |
| 20 | reject vitesse | clinical | Prompt compact, mêmes 9 appels : **473 147 → 466 604 caractères** (**−1,38 %**) avant tokenisation. | borne très sous le seuil de 10 % ; pas de run LLM coûteux |
| 21 | reject | clinical | Deux shards parallèles : p50 **50,18 → 34,84 s** (**−30,6 %**) mais tokens **+54,6 %** ; nDCG **0,9443 → 0,9381**, F1 **0,9276 → 0,9053**, pire quartile ΔnDCG **−0,0657**. | échoue qualité et efficacité non compensatoire |
| 22 | reject | clinical | Reasoning juge `medium → low` : p50 **50,18 → 50,03 s** (**−0,3 %**), tokens **−0,13 %** ; nDCG **0,9443 → 0,9413**, F1 **0,9276 → 0,8998**, pire quartile **−0,0685**. | aucun gain mesurable et porte qualité échouée |
| 23 | reject vitesse E2E | clinical | Query-builder `low`, pilote q01–q03 : **16,29 / 9,28 / 12,90 s** contre **24,84 / 14,08 / 14,32 s** sur le live baseline ; médiane ~**−9,9 %** de cette phase, tokens **+2,1 %**. | ~1,4 s médiane gagnée, <1 % du complet et ~1 % du usable ; ne pas payer le risque sémantique |
| 24 | reject vitesse pré-écran | clinical | Après chauffage, la phase FTS du finaliste étroit a un p50 de **0,222 s** face à **162,5 s** usable sur le live récent. Même une suppression parfaite de son coût ne gagnerait qu'environ **0,14 % E2E**. | très sous le seuil de 10 % ; ne pas changer les candidats ni payer un nouveau pool qrels pour ce plafond |
| 25 | reject vitesse pré-écran | clinical | Les ancres AND peuvent réduire le vivier et la latence SQL, mais partagent le même plafond de **0,14 % E2E** à chaud ; elles changeraient en plus la sémantique de rappel. | aucune voie vers 10 % sur l'incumbent ; hypothèse à réserver à un benchmark de cold-start distinct |
| 26 | reject vitesse/complexité | clinical | Le `tsvector` actuel concatène titre et résumé sans poids séparé. Un boost titre calculé dans l'`ORDER BY` relirait les titres du heap ; un vrai boost efficace exigerait une nouvelle colonne/index pondéré. | aucun gain d'efficacité crédible dans le schéma actuel ; changement d'index lourd hors finaliste |
| 27 | reject E2E / keep débit | clinical | Deux shards exécutent les mêmes six prompts de 10 : latence pool **638,9 → 440,4 s** (**−31,1 %**), tokens **141 340 → 140 765** (**−0,4 %**). Mais la production traduit chaque requête en **un seul appel de ≤20** ; ce test parallélise trois paires inter-lots. La vraie baseline batch=20 a en outre échoué strictement sur un lot (4/20 sorties), donc aucune latence prod complète n'est comparable. | signal de robustesse/débit seulement ; exclure de la combinaison E2E tant qu'un essai apparié par requête contre l'appel unique prod n'existe pas |
| 28 | finaliste live | auto → clinical | Combinaison minimale des keeps : `use_narrow_search=true` seulement. Le RRF du round 15 est écarté de la confirmation car il n'apporte aucune preuve d'efficacité et ajouterait un second changement sémantique. Capture B complète sur **18/18** requêtes, même corpus/manifeste/machine, sans erreur. | soumettre le seul finaliste d'efficacité au contrôle A–B–A complet |
| 29 | **reject confirmation** | clinical | A1–B–A complet. Face au centre A1/A2, B gagne **12,7 %** au p50 usable, **3,1 %** au p95 usable, **6,8 %** au p50 complet, **4,5 %** au p95 complet et **1,2 %** en tokens. Mais A1→A2 varie lui-même de **12,8 %** au p50 usable ; le gain >10 % n'est donc pas séparé du bruit. La phase FTS p50 gagne **30,5 %** (**84,9 → 59,0 s**) mais son p95 reste bloqué à ~120 s et les timeouts restent **8/18**. | ne pas promouvoir : signal médian E2E fragile, queues inchangées, régressions confirmées sur q09/q10/q17 |
| 30 | **reject promotion / ineligible clinique** | auto verrouillée | Les scorers A1→B et A2→B sont comparables et robustes opérationnellement, mais le pire quartile échoue deux fois sur l'entropie de source et d'année. B ajoute aussi **12 traductions manquantes sur q10** sous le même contrat v2. Les 18 listes diffèrent, donc les qrels seraient requis pour noter la pertinence ; ils ne sont pas générés car les échecs non compensatoires précédents rendent déjà toute promotion impossible. | conserver `baseline-ui-v1`; aucune modification production, aucun candidat promu |

## Livrable final hors nouvelle hypothèse

Le keep déterministe du round 2 est validé de bout en bout comme optimisation warm,
sans ouvrir un 31e essai. Le scorer intra-trace remplace uniquement la phase
query-builder par le pire hit exact réellement mesuré (**0,185 ms**) et conserve
littéralement tous les candidats, jugements et traductions de chaque baseline.

- A1 : p50 usable **138,6 → 123,0 s** (**−11,2 %**), p95 usable
  **174,0 → 155,0 s** (**−10,9 %**), tokens moyens
  **73 807 → 57 863** (**−21,6 %**).
- A2 : p50 usable **156,4 → 140,6 s** (**−10,1 %**), p95 usable
  **168,1 → 150,4 s** (**−10,5 %**), tokens moyens
  **76 712 → 58 663** (**−23,5 %**).
- Les p50/p95 complets gagnent aussi **3,3–6,0 %**, sans axe régressé.

Verdict : **keep warm** pour une question byte-identique déjà en cache. Aucun résultat,
jugement ou texte traduit n'est mis en cache ; un miss froid conserve strictement la
pipeline actuelle. Le taux de hit du trafic réel reste inconnu, et l'adaptateur livré
reste un sidecar non branché à la production.

Smoke d'intégration réel sur le clone récent, avec `--require-warm` : **1 hit, 0 miss,
0 token query-builder**, phase query-builder **0,0003 s**, 29 résultats, aucune erreur,
usable **102,3 s** et complet **341,1 s**. Ce smoke prouve le câblage et la facturation,
pas une performance full supplémentaire.

## Notes de méthode

- Protocole v2 gelé avant le holdout complet :
  `81085a3aca5c80b81382ea59f3aeb7d161889cf5ecb4de8213871bbb2d6e4bfa`
  (18 questions, 45 fichiers immuables). Aucun seuil, scorer ou runner ne peut être
  retouché sans invalider les captures suivantes.
- Une différence de candidats n'est pas une régression en soi. La porte `auto`
  bascule vers les qrels cliniques lorsque le replay diffère.
- L'identité byte-à-byte n'est exigée que pour les refactors mécaniques
  déterministes. Autour d'un LLM, une liste différente peut être meilleure ou
  équivalente ; elle doit passer le pool symétrique aveugle, les marges globales,
  stratifiées, de pire quartile et de bootstrap. Un échec préalable non compensatoire
  (ici traduction manquante et diversité de queue) permet d'arrêter avant une
  annotation coûteuse qui ne pourrait plus changer la décision de promotion.
- Un PMID absent du pool annoté ne reçoit jamais implicitement la note zéro : le run
  devient `ineligible` jusqu'à annotation.
- Les gains cache chaud ne sont jamais mélangés aux statistiques cache froid.
- Deux lives q01 sans changement de code ont gardé 28 puis 25 articles : 18 communs
  (Jaccard 0,51), 7/10 communs dans le top 10 et 34/50 entrées juge communes. Cette
  variance LLM impose le pool commun et interdit d'utiliser l'identité live comme gate.
- Un replay q01–q08 s'est arrêté correctement sur q07 : le live avait timeouté son
  FTS, le replay chaud a introduit 30 PMID non jugés. L'artefact reste `complete=false`
  et ne peut pas être scoré.
- Le premier proxy aveugle couvre 209 résultats retenus, avec trois passes complètes :
  165/209 accords exacts, 44 écarts d'un grade, aucun écart supérieur. Le pool enrichi
  ajoute les hard negatives puis les nouveaux PMID retrieval ; il reste un proxy LLM,
  pas une validation médicale.
- Les temps froids et chauds sont séparés. Les écrans k=32/k=50/RRF ont été lancés
  après chauffage de `article_search` et ne sont donc pas comparés directement au
  premier passage froid pour une décision de performance.
