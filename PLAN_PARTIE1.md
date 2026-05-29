# X-Med — Plan d'implémentation, Partie 1

> **Objectif de cette partie** : construire la base PostgreSQL à partir du corpus
> PubMed local, un site web où un médecin recherche des articles **par tags
> MeSH** *ou* **par phrase libre** (recherche sémantique), et un **banc d'essai
> (benchmark) multi-modèles** pour départager objectivement les modèles
> d'embedding.
>
> Document de réflexion — **aucun code n'est encore écrit**. À valider avant
> implémentation. Les choix de design font référence à `ARCHITECTURE.md` et
> `PIPELINE_EMBEDDINGS.md`.

---

## 1. Périmètre

**Dans cette partie :**
- Téléchargement du corpus PubMed (FTP NLM, édition annuelle 2026).
- Schéma PostgreSQL + extension pgvector, **multi-modèles d'embedding**.
- Pipeline d'ingestion (parsing XML streaming → upsert en base).
- Génération d'embeddings des articles (modèles auto-hébergés, voir §2).
- **Benchmark des modèles d'embedding** (vérité-terrain standard + interne, métriques IR).
- API de recherche (FastAPI, JSON) : MeSH + plein-texte + sémantique.
- Frontend de recherche (React / Next SPA).

**Hors périmètre (parties suivantes) :**
- Profils médecins, scoring de pertinence Claude, digest email Resend.
- **Benchmark des LLM de scoring** (même mécanique, mais étage 2 — plus tard).
- Orchestration Celery / Celery Beat du pipeline quotidien.
- Recherche à la demande via PubMed E-utilities.

> Les tables `doctors`, `doctor_profiles`, `article_scores`, `digest_sent` du
> schéma de référence ne sont pas remplies dans cette partie.

---

## 2. Décisions actées

| Sujet | Choix | Note |
|---|---|---|
| Corpus | **Baseline 2026** (`pubmed26n0001`–`1334`) + `updatefiles` (`1335`–`1459`) | ~37 M articles, ~27 Go compressés |
| Édition 2025 | **Non téléchargée** | Le baseline 2026 est cumulatif (contient déjà 2025) |
| Recherche | **MeSH + sémantique** | Les deux dès cette partie |
| Étage benchmarké | **Embeddings seuls** | Les LLM de scoring viendront en Partie 3 |
| Modèles (run initial) | **MedCPT** (768) + **bge-m3** (1024) | Deux modèles **gratuits / auto-hébergés** |
| Modèle payant | `text-embedding-3-large` (3072) | **Candidat à comparer plus tard**, hors run initial |
| Vérité-terrain | **Benchmark standard + gold set interne** | Les deux |
| Frontend | **React / Next (SPA)** | API FastAPI en JSON |
| Métrique de décision | **Recall@100 + nDCG@10** | Les deux suivies en parallèle dans le leaderboard |
| Texte embarqué | **Titre + abstract ; titre seul si pas d'abstract** | Couvre 100 % du corpus |
| Filtre multi-MeSH | **Bascule ET/OU réglable dans l'UI** (défaut OU) | — |
| Accès site | **Public, sans login** | Déploiement + protections anti-abus à prévoir (plus tard) |
| Infra calcul | **CPU (12 cœurs, 62 Go), pas de GPU** | OK pour le benchmark ; corpus complet = lent sur CPU |

### Pourquoi ces deux modèles
- **MedCPT** (`ncats/MedCPT-Article-Encoder`) — développé par la NLM (mêmes
  auteurs que PubMed), entraîné sur des millions de requêtes PubMed réelles,
  spécialisé recherche d'articles médicaux. **Anglais uniquement.**
- **bge-m3** (`BAAI/bge-m3`) — **multilingue natif (FR/EN)**, généraliste très
  performant. Pertinent quand les requêtes médecins sont en français et les
  articles en anglais.

Contraste volontaire : **spécialiste-EN vs multilingue-généraliste**. Le
benchmark tranchera, au lieu de parier.

---

## 3. Écarts assumés par rapport aux docs de référence

1. **Embeddings — multi-modèles au lieu d'une colonne unique.**
   Doc actuelle : une colonne `embedding vector(1536)`. Or chaque modèle a une
   dimension différente (MedCPT 768, bge-m3 1024, 3-large 3072) et pgvector
   exige une dimension fixe par colonne indexée. → **une table d'embeddings par
   modèle** (voir §7), pilotées par un **registre de modèles**. Ajouter un
   modèle = une table + un adaptateur, sans toucher au reste.

2. **Modèles auto-hébergés en premier (au lieu d'OpenAI).**
   On démarre avec deux modèles gratuits ; OpenAI `text-embedding-3-large`
   devient un candidat de comparaison ultérieur. → la question de la clé API et
   du coût d'embedding est repoussée.

3. **Frontend.** Doc : interface Jinja de gestion de profil. Ici : **SPA
   React/Next orientée recherche** ; l'API FastAPI renvoie du **JSON**.

4. **Endpoint `/search`.** Doc : interroge PubMed E-utilities. Ici : recherche
   sur **la base locale ingérée**. E-utilities conservé pour plus tard — deux
   surfaces distinctes.

→ `PIPELINE_EMBEDDINGS.md` à mettre à jour (multi-modèles, halfvec, benchmark).

---

## 4. Coût

- **Run de benchmark** : modèles auto-hébergés → **coût API = 0**. On
  benchmarke sur un **petit corpus de test** (pas les 37 M), donc temps CPU
  raisonnable.
- **Déploiement du gagnant** : embedder le corpus complet (37 M) une seule
  fois. Sur CPU, c'est lent (plusieurs jours) ; stratégie « 2 dernières années
  d'abord » puis le reste en arrière-plan.
- **OpenAI 3-large** (si comparé plus tard) : ~$700–1 400 one-shot sur 37 M.
  Le chiffre « ~$11 » de la doc est sous-évalué (~20×) et vise le modèle *small*.

---

## 5. Données — état des lieux

- Source : `https://ftp.ncbi.nlm.nih.gov/pubmed/`
  - `baseline/pubmed26n0001.xml.gz` → `…1334.xml.gz`
  - `updatefiles/pubmed26n1335.xml.gz` → `…1459.xml.gz`
- ~30 000 articles par fichier ; ~51 % ont un abstract.
- Champs utiles par `<PubmedArticle>` : `PMID`, `ArticleTitle`,
  `Abstract/AbstractText`, `AuthorList`, `Journal` (titre, ISSN), `PubDate`,
  `MeshHeadingList` (`DescriptorName UI`), `PublicationTypeList`,
  `ArticleIdList` (doi, pmc).
- Téléchargement : `data/pubmed/download_corpus.sh` (vérif MD5, reprise/skip),
  stockage sous `/home/geekette/data/pubmed/`.

> Accès : `/home/jack/data/pubmed` inaccessible (parent `/home/jack` en
> `drwx------`) → données retéléchargées sous `/home/geekette/data/pubmed/`.

---

## 6. Dérivation `evidence_level` (1–4)

À partir de `PublicationType` :

| Niveau | Types PubMed |
|---|---|
| 1 | Meta-Analysis, Systematic Review, Randomized Controlled Trial |
| 2 | Controlled Clinical Trial, Clinical Trial, Comparative Study |
| 3 | Case Reports, Case Series |
| 4 | Review, Editorial, Letter, Comment, autres |

Un article cumule plusieurs types → on retient le **niveau le plus haut**.

---

## 7. Schéma — articles + embeddings multi-modèles + benchmark

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Articles (métadonnées) — schéma ARCHITECTURE.md + ajouts
CREATE TABLE articles (
    pmid              BIGINT PRIMARY KEY,
    title             TEXT NOT NULL,
    abstract          TEXT,
    authors           JSONB,
    journal           TEXT,
    issn              TEXT,
    pub_date          DATE,
    pub_year          INT,                 -- pour filtre/tri rapide
    mesh_terms        TEXT[],
    doi               TEXT,
    pmc_id            TEXT,
    publication_types TEXT[],
    evidence_level    INT,
    fts               tsvector,            -- généré (title + abstract)
    ingested_at       TIMESTAMPTZ DEFAULT now()
);
-- Index : GIN(fts), GIN(mesh_terms), btree(pub_year)

-- UNE table d'embeddings PAR modèle (dimension fixe par table)
CREATE TABLE emb_medcpt (pmid BIGINT PRIMARY KEY REFERENCES articles(pmid), v vector(768));
CREATE TABLE emb_bge_m3 (pmid BIGINT PRIMARY KEY REFERENCES articles(pmid), v vector(1024));
-- (plus tard) emb_e3large (pmid …, v halfvec(3072))
-- Index HNSW (cosine) sur chaque .v, créé APRÈS chargement

-- Autocomplétion MeSH (peuplée à l'ingestion)
CREATE TABLE mesh_descriptors (ui TEXT PRIMARY KEY, name TEXT);

-- Suivi des fichiers ingérés
CREATE TABLE ftp_state (filename TEXT PRIMARY KEY, checksum TEXT, downloaded_at TIMESTAMPTZ DEFAULT now());

-- ===== Benchmark =====
CREATE TABLE bench_queries (
    id        SERIAL PRIMARY KEY,
    dataset   TEXT NOT NULL,        -- 'nfcorpus' | 'gold_interne' | …
    text      TEXT NOT NULL,
    lang      TEXT                  -- 'en' | 'fr'
);
CREATE TABLE bench_qrels (          -- vérité-terrain
    query_id  INT REFERENCES bench_queries(id),
    pmid      BIGINT,
    relevance INT NOT NULL,         -- 0 = non pertinent, ≥1 = pertinent
    PRIMARY KEY (query_id, pmid)
);
CREATE TABLE bench_runs (
    id         SERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    dataset    TEXT NOT NULL,
    params     JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE bench_results (
    run_id INT REFERENCES bench_runs(id),
    metric TEXT NOT NULL,           -- 'ndcg@10' | 'recall@100' | 'mrr' | 'p@10'
    value  FLOAT NOT NULL,
    PRIMARY KEY (run_id, metric)
);
```

---

## 8. Le benchmark, en détail

### Registre de modèles
Un objet par modèle : `{ name, table, dim, lang, loader }` où `loader` charge
le modèle (transformers/sentence-transformers) et expose `embed(texts) -> vecteurs`.
Tout le code de benchmark/ingestion itère ce registre — aucun code spécifique
par modèle ailleurs.

### Vérités-terrain (les deux)
1. **Standard — NFCorpus** (via BEIR) : ~3,6 K documents médicaux dérivés de
   PubMed, ~320 requêtes de test en langage naturel + qrels. Petit, rapide,
   résultats comparables à la littérature. (Montée en charge possible :
   BioASQ — questions + PMIDs réels, directement mappables à `articles`.)
2. **Interne — gold set FR** : 30–50 phrases types de médecins (en français),
   avec les PMIDs pertinents validés manuellement. Teste précisément le cas
   réel **requête FR → article EN**, que les benchmarks anglais ne couvrent pas.

### Runner
Pour chaque modèle du registre :
1. embed le corpus de test → table `emb_*` ;
2. embed chaque requête → KNN pgvector (`<=>`) top-k ;
3. compare au qrels → calcule **nDCG@10, Recall@100, MRR, P@10** (lib `pytrec_eval` ou `ranx`) ;
4. écrit `bench_runs` + `bench_results`.

### Sortie
Un **leaderboard** (table + endpoint `GET /bench/leaderboard`) :

| modèle | dataset | nDCG@10 | Recall@100 | MRR |
|---|---|---|---|---|
| MedCPT | nfcorpus | … | … | … |
| bge-m3 | nfcorpus | … | … | … |
| MedCPT | gold_interne (FR) | … | … | … |
| bge-m3 | gold_interne (FR) | … | … | … |

→ décision **mesurée** du modèle déployé sur le corpus complet.

---

## 9. Étapes d'implémentation

- **A — Infra + schéma** : `docker-compose.yml` (`pgvector/pgvector:pg16`,
  redis, api, web), migration Alembic (§7), `app/config.py`, `app/models/`.
- **B — Ingestion** : `app/services/pubmed_ftp.py`, `app/tasks/parse_articles.py`,
  `scripts/load_baseline.py` — `lxml.iterparse` streaming, dérivation
  `evidence_level`, upsert batch, `DeleteCitation`, `ftp_state`,
  `mesh_descriptors`.
- **C — Embeddings multi-modèles** : `app/services/embeddings.py` (registre +
  adaptateurs MedCPT, bge-m3), `scripts/embed_corpus.py` (remplit les tables
  `emb_*`).
- **D — Benchmark** : `bench/` — chargement NFCorpus + gold set FR dans
  `bench_queries`/`bench_qrels`, `bench/runner.py` (métriques IR), leaderboard.
- **E — API de recherche** : `app/api/search.py` — `/search/mesh`,
  `/search/semantic` (paramètre `model`), `/search` (hybride),
  `/articles/{pmid}`, `/mesh/autocomplete`, `/bench/leaderboard`. CORS.
- **F — Frontend React/Next** (`web/`) : barre de recherche langage naturel +
  chips MeSH (autocomplétion) + filtres (année, niveau de preuve) + résultats
  (titre, journal, année, badge niveau de preuve, extrait, tags MeSH, score,
  lien PubMed). Sélecteur de modèle d'embedding (utile en phase benchmark).

---

## 10. Ordre de livraison

```
A (infra+schéma)
└─ B (ingestion → charger l'échantillon, valider les comptes)
   ├─ E (recherche MeSH/plein-texte — fonctionne sans embedding)
   │   └─ F (frontend sur recherche MeSH)
   └─ C (embeddings MedCPT + bge-m3 sur corpus de test)
       └─ D (benchmark → leaderboard → choix du modèle)
           └─ recherche sémantique branchée + embedding du corpus complet
```

Le téléchargement complet tourne en arrière-plan pendant A–E.

---

## 11. Structure de projet cible (Partie 1)

```
x-med/
├── docker-compose.yml
├── .env.example
├── pyproject.toml            # lxml, sqlalchemy, alembic, fastapi, psycopg,
│                             #   pgvector, sentence-transformers, transformers,
│                             #   torch (CPU), pytrec_eval/ranx
├── alembic/versions/
├── app/
│   ├── config.py / main.py / db.py
│   ├── models/article.py
│   ├── services/{pubmed_ftp.py, embeddings.py}
│   ├── tasks/parse_articles.py
│   └── api/search.py
├── bench/
│   ├── registry.py           # registre des modèles
│   ├── datasets.py           # chargement NFCorpus + gold set FR
│   └── runner.py             # exécution + métriques IR
├── scripts/{load_baseline.py, embed_corpus.py}
└── web/                      # frontend React / Next
```

---

## 12. Variables d'environnement (ajouts pour cette partie)

```env
DATABASE_URL=postgresql://xmed:password@localhost:5432/xmed
DATA_DIR=/home/geekette/data/pubmed
EMBEDDING_MODELS=medcpt,bge_m3        # modèles actifs (registre)
# OPENAI_API_KEY=sk-...               # seulement si on compare 3-large plus tard
```

---

## 13. Défauts techniques retenus

| Sujet | Décision |
|---|---|
| Dates PubMed | `pub_year` toujours ; `pub_date` seulement si date complète parseable |
| Révisions | Toujours la dernière version (upsert) ; `DeleteCitation` honorés |
| Recherche hybride | Fusion **RRF** (Reciprocal Rank Fusion) plein-texte + sémantique |
| Troncature | Limite du modèle (MedCPT 512 tokens, bge-m3 8192) |
| Reranker | Hors 1er run (add-on possible MedCPT/bge-reranker) |
| Gestionnaire Python | **`uv`** |
| Chargement initial | Échantillon (~25 fichiers) pour valider, puis corpus complet |
| Langue UI | Français |
| Résultats / page | 20 |
| Benchmark standard | **NFCorpus** (1er run), BioASQ en montée en charge |

## 14. Point ouvert restant

- **Annotation du gold set FR** : méthode retenue = X-Med génère les phrases
  candidates + une présélection de PMIDs (via MeSH/plein-texte), validée
  manuellement par Eva ou un médecin. À faire au moment de l'étape D
  (spécialités cibles à préciser à ce moment-là).
```
