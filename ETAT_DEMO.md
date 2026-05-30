# X-Med — État de la démo (Partie 1)

> Mémo pour tester. Tout tourne sur le serveur ; le frontend est exposé sur le port 3003.

## Accès

- **Site** : `http://65.108.202.130:3003` (ou ton accès habituel sur 3003)
- **API** : `http://localhost:8800` (interne ; le site la joint via un proxy `/api`)
- Relancer toute la stack si besoin : `bash scripts/dev_up.sh`

## Ce qui marche

### Recherche par mots-clés / MeSH (onglet « Mots-clés / MeSH »)
- Plein-texte (anglais) : `myocardial infarction`, `diabetes`, `renal failure`
- Tags MeSH avec autocomplétion : taper `diab` → *Diabetes Mellitus*
- Bascule **ET / OU** entre tags, filtres **année** et **niveau de preuve**

### Recherche par phrase / sémantique (onglet « Par sens »)
- Phrase en **français** : `insuffisance rénale chronique dialyse`,
  `crise cardiaque chez le diabétique` → retrouve les articles anglais pertinents
- Modèle : **bge-m3** (multilingue), 3000 articles vectorisés
- Recherche **hybride** (fusion plein-texte + sémantique, RRF)

> ⚠️ Données actuellement chargées = **780 000 articles, surtout 1974-1980**
> (les 26 premiers fichiers du corpus, les plus anciens). Donc les sujets
> récents (COVID…) ne ressortent pas encore. Le corpus complet (37 M, 57 Go)
> est téléchargé mais pas encore tout ingéré (job ~15 h).

## Benchmark multi-modèles (étape D)

Leaderboard sur **NFCorpus** (BEIR, 1500 docs, 144 requêtes) —
`GET /api/bench/leaderboard` ou `uv run python -m scripts.run_benchmark` :

| modèle | nDCG@10 | Recall@100 | MRR | P@10 |
|---|---|---|---|---|
| medcpt | 0.339 | **0.385** | 0.524 | **0.270** |
| bge_m3 | **0.340** | 0.373 | **0.541** | 0.263 |

Très serré sur ce jeu **anglais**. La comparaison décisive (requêtes **FR**)
viendra du **gold set FR** à annoter ensemble.

## Reste à faire

- **Gold set FR** : 30-50 phrases de médecins + PMIDs pertinents (à annoter)
- **Embedding MedCPT** de notre corpus (pour le sémantique côté site, pas que le benchmark)
- **Ingestion complète** des 1459 fichiers (avec index désactivés pendant le bulk-load)
- Benchmark sur NFCorpus complet (3633 docs) et autres jeux (BioASQ)
- Données récentes : ingérer des fichiers haut-numérotés pour la médecine actuelle

## Commandes utiles

```bash
bash scripts/dev_up.sh                              # démarrer db+redis+api+web
uv run python -m scripts.load_baseline --limit 25   # ingérer N fichiers
uv run python -m scripts.embed_corpus --model bge_m3 --limit 5000 --index
uv run python -m scripts.run_benchmark --max-docs 1500
```
