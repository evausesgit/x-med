# Diagnostic « moins de résultats qu'avant » — le juge est hors de cause (06/08/2026)

Diagnostic ponctuel, **hors du programme des 30 essais** (voir `RESULTS.md`) : il ne
propose aucun candidat à la promotion. Il répond à une plainte produit — « on a
beaucoup moins de résultats qu'avant » — et il **écarte** une piste.

## La question posée

La recherche du 05/08 « association floppy eyelid syndrome et glaucome a pression
normale » a rendu **0 résultat** : 50 abstracts jugés, 48 notés 0, 2 notés 1, seuil de
rétention à 2. Les deux articles notés 1 sont les deux moitiés du pont clinique que la
question appelle :

| PMID | article | score prod |
|---|---|---|
| 42454079 | *Relationship Between Floppy Eyelid Syndrome and Obstructive Sleep Apnea Syndrome: An Umbrella Review* | 1 (35 %) |
| 39930146 | *Association between normal tension glaucoma and the risk of obstructive sleep apnoea* | 1 (40 %) |

Le juge avait motivé : « lien **indirect** avec le floppy eyelid syndrome ». D'où
l'hypothèse testée ici : **le jugement s'est-il durci ?** Deux causes candidates, toutes
deux datées du 23/07 et **non défaites par la PR #73** :

1. le commit `4f6de6b` ajoute « niveau de preuve 1-4 » au payload du juge — or **38 des
   50** articles du pool portent un niveau 4, le plus faible ;
2. `codex_judge._PROMPT_HEAD` contient trois exemples de style permanents, **tous**
   consacrés au floppy eyelid syndrome et à l'apnée du sommeil, dans un prompt qui sert
   toutes les questions.

## Protocole

`run_judge_screen` sur le pool exact des 50 abstracts de cette recherche. Sidecar : ni
retrieval, ni PostgreSQL, ni traduction. **Un seul facteur change par bras**, vérifié par
diff des prompts (6 lignes pour D ; seul le suffixe « · niveau de preuve N » pour C).
3 répétitions par bras, le juge n'étant pas déterministe.

Deux variantes ont été ajoutées au harnais pour ce diagnostic : `--metadata-mode
no_evidence` et `--prompt-style neutral`. La seconde est dérivée par substitution du
prompt de production et **échoue bruyamment** si les exemples y changent de forme, pour
qu'un écart mesuré ne puisse jamais venir d'autre chose.

## Résultats — 4 bras × 3 répétitions

| bras | ce qui change | retenus/50 | moyenne | distribution |
|---|---|---|--:|---|
| A | rien (prod : `gpt-5.6-terra` / medium) | 0, 2, 0 | 0,7 | 0:135 1:13 2:2 |
| B | `gpt-5.4` / high — **= PR #73** | 0, 0, 2 | 0,7 | 0:106 1:42 2:2 |
| C | sans « niveau de preuve » | 0, 0, 0 | **0,0** | 0:109 1:41 |
| D | exemples du prompt neutralisés | 0, 0, 0 | **0,0** | 0:134 1:16 |

Scores des deux articles « pont », par répétition :

| bras | PMID 42454079 | PMID 39930146 |
|---|---|---|
| A | 1, 2, 1 | 1, 2, 1 |
| B | 1, 1, 2 | 1, 1, 2 |
| C | 1, 1, 1 | 1, 1, 1 |
| D | 1, 1, 1 | 1, 1, 1 |

## Conclusions

1. **Les deux hypothèses sont réfutées.** Retirer le niveau de preuve (C) et neutraliser
   les exemples (D) ne font franchir le seuil à aucun article — les deux bras rendent
   **0 retenu sur les 3 répétitions**, contre 0,7 pour la production.
2. **La PR #73 ne change rien sur ce cas.** Le bras B rend la même moyenne que A (0,7)
   et la même distribution aux deux articles pont. Cela confirme par la mesure
   l'observation « même avec le rollback, pas de résultats ». Son coût est traité
   séparément plus bas — il n'est pas celui qu'on croit.
3. **Le juge est stable et cohérent.** Sur 12 exécutions et 4 configurations, il note
   ces articles 1 presque systématiquement. Ce n'est pas une dérive : c'est un jugement
   tenu. Et il est défendable — aucun des deux articles ne traite directement de
   l'association FES ↔ glaucome à pression normale.
4. **Le problème est donc en amont, dans le retrieval.** Le vivier de 50 ne contient
   aucun article répondant directement à la question, parce qu'il n'en existe que
   **4 dans tout PubMed** — et que le défaut de fenêtre du front (`2025-01-01`) les
   exclut tous les quatre.
5. **Variance à signaler séparément** : à configuration identique, A rend 0, 2 puis 0
   articles. La même recherche relancée donne 0 ou 2 résultats. C'est un problème
   produit en soi, indépendant de tout ce qui précède.

## Coût : gpt-5.4 contre gpt-5.6-terra, modèle × effort

Le bras B changeait deux choses à la fois (modèle **et** effort), comme la PR #73.
Deux bras supplémentaires ferment le carré. Médianes sur 3 répétitions, par appel de
50 abstracts :

| modèle | effort | latence | total remonté | **frais** | retenus |
|---|---|--:|--:|--:|---|
| gpt-5.6-terra | medium | **57 s** | 34 207 | 34 207 | 0, 2, 0 |
| gpt-5.4 | medium | 73 s | 32 668 | **30 748** | 0, 0, 0 |
| gpt-5.6-terra | high | 64 s | 34 628 | 34 628 | 0, 0, 0 |
| gpt-5.4 | high (PR #73) | **160 s** | 140 659 | 34 744 | 0, 0, 2 |

`frais` = entrée **non** mise en cache + sortie, c'est-à-dire la part réellement
recalculée. La distinction est décisive :

- **En tokens frais, les quatre réglages sont équivalents** (30–35 k). gpt-5.4/medium
  est même le moins cher (−10 % face à la production). Il n'y a pas d'écart de coût
  entre les deux modèles.
- **Le « ×3,3 » du total remonté est un artefact de cache.** Détail par répétition en
  gpt-5.4/high : total **36 664 · 140 659 · 158 661**, mais frais **34 744 · 44 403 ·
  14 917**. L'entrée gonflée est à 96–144 k de tokens **déjà en cache** : le modèle
  enchaîne des tours de raisonnement et le contexte relu est recompté à chaque tour.
  Facturé à taux plein, ce serait catastrophique ; en cache, c'est marginal.
- **Le vrai coût de la PR #73 est la latence** : **160 s contre 57 s**, soit
  **×2,8**, et cette fois c'est stable (144, 168, 160 s sur les trois répétitions).
  Cent secondes d'attente en plus par lot de 50, pour un résultat identique.
- **Aucun réglage ne change le résultat clinique.** Les quatre rendent ~0 retenu.

Réserve : x-med passe par le CLI `codex` (quota d'abonnement), pas par l'API
facturée. On ne sait pas si ce quota décompte l'entrée en cache au tarif plein — si
c'est le cas, la conclusion « coût équivalent » tombe et gpt-5.4/high redevient 4×
plus cher. À vérifier auprès du fournisseur avant d'arbitrer #73 sur le coût.

## Ce que ce diagnostic ne dit pas

Une seule question, un seul pool, et le repère « ces deux articles sont les bons » est
un raisonnement clinique d'agent, **pas une annotation médicale**. Il suffit à écarter
les deux hypothèses testées — elles ne déplacent aucun score — mais il ne mesure pas la
qualité du juge en général. Le round 17 de `RESULTS.md` reste la référence pour ça
(nDCG@10 0,9443 sur 326 articles aveugles).

## Reproduire

```bash
bash run_arms.sh            # 4 bras × 3 répétitions (~16 min, ~640k tokens)
PYTHONPATH=. uv run python analyse_bras.py
```

Le pool (`pool_fes.jsonl`) et les artefacts ne sont pas versionnés : ils contiennent des
abstracts et des sorties de modèle. Le pool se régénère depuis `search_runs` (trace
`judgements` du run du 05/08 14:17) jointe à la table `articles` du corpus.
