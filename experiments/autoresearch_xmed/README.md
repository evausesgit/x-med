# Autoresearch X-Med

Boucle expérimentale isolée pour accélérer la chaîne :

```text
question FR → requête PubMed → PubMed + FTS local → jugement → traduction FR
```

Elle reprend la séparation volontaire de
[`karpathy/autoresearch`](https://github.com/karpathy/autoresearch), commit amont
`228791fb499afffb54b46200aca536f79142f117` (licence MIT) :

- `prepare_bench.py`, `score.py`, le corpus de requêtes et les portes de promotion
  sont fixes ;
- `experiment.py` est le seul fichier mutable pendant les 30 essais ;
- `program.md` décrit la boucle keep/reject/crash et les règles de sécurité.

Le code de production n'est ni appelé par HTTP, ni modifié, ni redémarré. Les
artefacts locaux sont ignorés par Git. Aucun runner live ou replay ne doit accepter
une base dont le nom ne contient pas explicitement `autoresearch`. Les connexions au
clone sont forcées en lecture seule ; le replay remplace le réseau et les LLM par les
captures de baseline, mais réexécute volontairement le chemin SQL sur le clone.

## Deux niveaux de preuve

1. **Équivalence déterministe** — test rapide lorsqu'un changement affirme ne toucher
   que l'orchestration, le cache, SQL ou le transport. Une identité exacte en replay
   est alors une preuve forte, mais ce n'est pas une règle générale sur les sorties
   live d'un LLM. Le replay s'arrête avec une erreur s'il rencontre un PMID sans
   jugement ou traduction dans la capture de référence.
2. **Équivalence clinique statistique** — dès que les candidats ou leurs jugements
   diffèrent, même légèrement : pool commun annoté en aveugle, répétitions et portes
   de non-infériorité qualité/diversité sur l'ensemble et dans les strates de largeur
   pré-déclarées (`broad`, `narrow`, `rare`). Les écarts par requête restent visibles
   comme diagnostics, mais ne sont pas chacun une porte bloquante. Une liste différente peut donc gagner. Sans
   qrels indépendants, elle reste `ineligible`, jamais arbitrairement rejetée comme
   « mauvaise » ni promue sur le seul avis du LLM de production.

La porte `auto` accepte l'identité exacte si elle est observée, sinon bascule sur la
preuve clinique. Un gain de vitesse ne compense jamais une perte de qualité. Les portes sont évaluées
avant la performance, dans cet ordre : contrat, fidélité/qualité, diversité,
robustesse, latence, coût.

La variance de formulation d'une étape LLM inchangée n'est pas attribuée à un
refactor d'une autre étape : deux runs v2 qui partagent le protocole fingerprinté et
les knobs du traducteur peuvent avoir des traductions textuellement différentes,
mais le nombre de traductions manquantes ne doit pas augmenter. Une modification du
prompt, du modèle ou de l'entrée du traducteur exige au contraire l'évaluation
bilingue aveugle.

Sur le corpus initial de 18 questions, une petite différence est donc explicitement
admise : marge absolue de **0,02** pour nDCG@10, P@10 et Recall@50, globalement et
par strate ; moyenne du pire quartile nDCG au moins **−0,05** ; borne basse du
bootstrap apparié à 10 000 tirages au moins **−0,02**. La diversité dispose de
marges séparées adaptées à ses unités. Ces seuils sont fixés avant le holdout et ne
peuvent pas être ajustés après observation d'un candidat. Cela étaye seulement une
non-infériorité sur ce corpus précis ; une validation médicale cachée plus large
reste nécessaire avant promotion en production.

Les variantes qui changent la récupération, la taille ou la composition du lot,
les prompts, le modèle ou l'effort de raisonnement exigent donc de nouvelles captures
live appariées. Elles ne peuvent pas « inventer » leurs sorties à partir du replay.

## Commandes

```bash
# Manifeste reproductible de la baseline (aucun réseau, aucune DB)
uv run python -m experiments.autoresearch_xmed.prepare_bench \
  --out experiments/autoresearch_xmed/artifacts/manifest.json

# Comparaison de deux artefacts de replay
uv run python -m experiments.autoresearch_xmed.score \
  baseline.json candidate.json --gate fidelity

# Smoke test fonctionnel uniquement sur le clone récent (jamais une baseline perf)
uv run python -m experiments.autoresearch_xmed.run_live_baseline \
  --database xmed_autoresearch --allow-recent-smoke --ids q01 \
  --out experiments/autoresearch_xmed/artifacts/smoke_q01.json

# Tests du harness
uv run --group dev pytest -q tests/test_autoresearch_score.py
```

`trial_plan.json` est le plan pré-enregistré des 30 essais. Les essais sémantiques
restent dans le plan pour ne pas biaiser la recherche, mais sont automatiquement
non promouvables tant que `qrels.json` n'a pas été produit par annotation médicale.

## Livrable warm après les 30 essais

Le seul keep final qui conserve exactement la sortie de son composant est le cache
versionné du query-builder. Sa clé inclut la question byte-identique, le prompt, le
schéma, le modèle et l'effort de raisonnement. Il ne met en cache ni les articles,
ni le jugement, ni la traduction : une recherche répétée reste donc fraîche en aval.

Le scorer contrefactuel intra-trace soustrait uniquement la phase query-builder des
deux baselines full A1/A2 et ajoute la pire latence de hit réellement mesurée. Les
candidats, jugements et traductions de chaque trace restent littéralement inchangés :

```bash
uv run python -m experiments.autoresearch_xmed.score_warm_query_cache \
  --baseline experiments/autoresearch_xmed/artifacts/live_full_baseline_v2.json \
  --baseline experiments/autoresearch_xmed/artifacts/live_full_baseline_a2_v2.json \
  --cache-artifact experiments/autoresearch_xmed/artifacts/query_cache_round2.json \
  --cache-artifact experiments/autoresearch_xmed/artifacts/query_cache_round2_q03.json \
  --cache-artifact experiments/autoresearch_xmed/artifacts/query_cache_round2_q09.json \
  --out experiments/autoresearch_xmed/artifacts/score_warm_query_cache_v1.json
```

Le runner d'intégration reste un sidecar et refuse optionnellement tout miss avant
d'ouvrir la DB ou d'appeler un LLM :

```bash
uv run python -m experiments.autoresearch_xmed.run_live_warm_query_cache \
  --database xmed_autoresearch_full \
  --manifest experiments/autoresearch_xmed/artifacts/manifest.json \
  --cache-dir experiments/autoresearch_xmed/artifacts/query_builder_cache \
  --require-warm \
  --out experiments/autoresearch_xmed/artifacts/live_full_warm_cache.json
```

Ce keep ne promet aucun gain sur un miss froid et son impact réel dépend du taux de
répétition byte-identique du trafic. Il n'est pas branché à la production.
Un smoke live `q01` avec `--require-warm` a confirmé le chemin réel : un hit, aucun
miss, zéro token query-builder et une phase servie en moins d'une milliseconde ; le
jugement et la traduction aval ont continué normalement.
