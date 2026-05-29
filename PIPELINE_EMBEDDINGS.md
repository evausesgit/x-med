# X-Med — Pipeline sémantique : pgvector & embeddings

## Pourquoi un matching sémantique

Le pré-filtre MeSH (intersection d'arrays SQL) compare des mots exacts. Il rate les articles pertinents dont le vocabulaire diffère légèrement du profil médecin.

Exemple : un médecin dont le profil contient *"anticoagulation, prévention AVC, FA"* ne matchera pas sur un article titré *"Novel oral factor Xa inhibitor reduces thromboembolic events in non-valvular atrial fibrillation"* si ces termes exacts ne sont pas dans son profil.

Un embedding résout ce problème en représentant le **sens** plutôt que les mots.

---

## Concept : qu'est-ce qu'un embedding

Un embedding transforme un texte en vecteur de nombres :

```
"fibrillation atriale et anticoagulants chez le sujet âgé"
→ [0.23, -0.87, 0.41, 0.12, -0.33, ..., 0.67]  ← 1536 nombres
```

Le modèle place les textes au sens proche **géométriquement proches** dans cet espace :

```
"FA et AVK en prévention AVC"          → vecteur A
"fibrillation atriale anticoagulants"  → vecteur B  ← très proche de A
"chirurgie du genou ligamentaire"      → vecteur C  ← loin de A et B
```

La distance cosinus entre deux vecteurs mesure leur similarité sémantique.

---

## Architecture Option B — pgvector

### Vue d'ensemble du pipeline

```
AVANT (filtre MeSH seul)
────────────────────────
4 000 articles/jour
    ↓ filtre MeSH SQL (&&)
  ~200 articles candidats  ← risque de rater des articles pertinents
    ↓ Claude scoring
  coûteux + rappel ~70%


APRÈS (pgvector)
────────────────
4 000 articles/jour
    ↓ génération embedding (title + abstract)
    ↓ ANN search pgvector — 50ms
   50 articles  ← sémantiquement les plus proches du profil médecin
    ↓ Claude scoring fin
  précis + exhaustif + rappel ~90%+
```

### Schéma de base de données — ajouts

```sql
-- Extension pgvector (à activer une fois)
CREATE EXTENSION IF NOT EXISTS vector;

-- Colonne embedding dans articles
ALTER TABLE articles ADD COLUMN embedding vector(1536);

-- Index HNSW pour recherche approximative rapide
-- (à créer après le chargement de la baseline)
CREATE INDEX ON articles
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Index GIN sur mesh_terms (critique pour 37M rows)
CREATE INDEX ON articles USING gin (mesh_terms);

-- Embedding du profil médecin (recalculé si profil modifié)
ALTER TABLE doctor_profiles ADD COLUMN profile_embedding vector(1536);
```

---

## Pipeline détaillé

### Étape 1 — Ingestion : embedding de chaque article

À l'ingestion (après parsing XML), chaque article est converti en vecteur :

```python
# tasks/parse_articles.py

def embed_article(article: Article) -> list[float]:
    text = f"{article.title}. {article.abstract or ''}"
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

# Upsert avec embedding
db.execute("""
    INSERT INTO articles (pmid, title, abstract, ..., embedding)
    VALUES (:pmid, :title, :abstract, ..., :embedding)
    ON CONFLICT (pmid) DO NOTHING
""", {..., "embedding": embed_article(article)})
```

### Étape 2 — Profil médecin : embedding du profil

Calculé une fois à la création, recalculé uniquement si le profil change :

```python
# services/doctor_profile.py

def embed_doctor_profile(profile: DoctorProfile) -> list[float]:
    text = f"""
Spécialité : {profile.specialty_main}
Sous-spécialités : {', '.join(profile.subspecialties)}
Pathologies : {', '.join(profile.pathologies)}
Traitements : {', '.join(profile.treatments)}
Types d'études : {', '.join(profile.study_types)}
Mots-clés additionnels : {', '.join(profile.keywords_extra)}
"""
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text.strip()
    )
    return response.data[0].embedding
```

### Étape 3 — Matching sémantique (requête pgvector)

```sql
-- Pré-filtre sémantique : top 50 articles les plus proches du profil
SELECT
    a.pmid,
    a.title,
    a.abstract,
    a.mesh_terms,
    a.evidence_level,
    a.journal,
    a.pub_date,
    1 - (a.embedding <=> dp.profile_embedding) AS similarity
FROM articles a
JOIN doctor_profiles dp ON dp.doctor_id = $1
WHERE a.ingested_at > now() - interval '24h'
  AND a.pmid NOT IN (
      SELECT pmid FROM digest_sent WHERE doctor_id = $1
  )
  AND (
      dp.min_evidence_level IS NULL
      OR a.evidence_level <= dp.min_evidence_level
  )
ORDER BY a.embedding <=> dp.profile_embedding   -- distance cosinus
LIMIT 50;
```

L'opérateur `<=>` est la distance cosinus fournie par pgvector.
Avec l'index HNSW : **~50ms sur 37M articles**.

### Étape 4 — Scoring fin via Claude

Claude ne voit que les 50 articles pré-filtrés, déjà triés par pertinence sémantique :

```python
# tasks/ai_enrichment.py

for article in top_50_articles:
    prompt = f"""
Profil médecin : {doctor_profile_text}      ← mis en cache (prompt caching)

Article :
Titre : {article.title}
Abstract : {article.abstract}
Type d'étude : {article.publication_types}
Niveau de preuve : {article.evidence_level}

Sur une échelle de 0 à 1, évalue la pertinence de cet article
pour ce profil médecin. Réponds en JSON :
{{"score": float, "priority": bool, "summary": "150 mots max en français"}}
"""
```

### Étape 5 — Notification urgente (ajout par rapport au flow actuel)

```python
# Après scoring, avant le digest 8h
if score.relevance_score > 0.90 and score.is_priority:
    # Notification immédiate sans attendre le digest
    send_urgent_notification(doctor, article, score)
```

---

## Traitement de la baseline (37M articles)

Les 37M articles existants nécessitent une génération d'embeddings en batch unique.

```
Estimation :
- text-embedding-3-small : ~500K tokens/min via API
- 37M articles × 300 tokens moy. = 11 milliards de tokens
- Séquentiel : ~22 000 min ≈ 15 jours
- Avec 10 workers parallèles : ~1.5 jours
- Coût total : ~$11 (one-shot)
```

**Stratégie pratique** : commencer par les articles des 2 dernières années (les plus pertinents pour les médecins), puis remplir le reste en arrière-plan. Le pipeline quotidien fonctionne dès J+1.

```python
# scripts/embed_baseline.py

# Traiter par batch de 1000, les plus récents en premier
SELECT pmid, title, abstract FROM articles
WHERE embedding IS NULL
ORDER BY pub_date DESC
LIMIT 1000;
```

---

## Évaluation des modèles d'embedding

### OpenAI

| Modèle | Dimensions | Coût / 1M tokens | Notes |
|---|---|---|---|
| `text-embedding-3-small` | 1536 | $0.020 | Bon rapport qualité/prix |
| `text-embedding-3-large` | 3072 | $0.130 | Meilleure précision, 6× plus cher |
| `text-embedding-ada-002` | 1536 | $0.100 | Ancienne génération, à éviter |

### Anthropic / Claude

Claude n'expose pas de modèle d'embedding via API publique à ce jour. Anthropic recommande un modèle tiers pour les embeddings, Claude pour le scoring et les résumés — c'est exactement l'architecture retenue ici.

### Cohere

| Modèle | Dimensions | Coût / 1M tokens | Notes |
|---|---|---|---|
| `embed-v4.0` | 1024 | $0.016 | Multilingue natif, très bon en médical |
| `embed-multilingual-v3.0` | 1024 | $0.100 | Ancienne version, à éviter |

`embed-v4.0` est particulièrement adapté à X-Med : multilingue de naissance, utile quand les profils médecins sont en français et les articles en anglais.

### Google / Vertex AI

| Modèle | Dimensions | Coût / 1M tokens | Notes |
|---|---|---|---|
| `text-embedding-005` | 768 | $0.000025 | Prix quasi-nul |
| `text-multilingual-embedding-002` | 768 | $0.000025 | Multilingue, même prix |

Option sérieuse si les coûts API sont une contrainte forte.

### Modèles open-source (auto-hébergés, coût API = zéro)

| Modèle | Dimensions | Notes |
|---|---|---|
| `ncbi/MedCPT-Article-Encoder` | 768 | Développé par la NLM (mêmes auteurs que PubMed), entraîné spécifiquement pour la recherche d'articles médicaux |
| `microsoft/BiomedNLP-BiomedBERT-base` | 768 | Entraîné sur littérature biomédicale |
| `pritamdeka/S-PubMedBert-MS-MARCO` | 768 | Fine-tuné sur PubMed + recherche |
| `BAAI/bge-m3` | 1024 | Multilingue, excellent benchmark général |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | Léger, CPU suffisant, anglais uniquement |

**MedCPT** est le plus intéressant pour X-Med : développé par la NLM (National Library of Medicine), entraîné sur des millions de requêtes PubMed réelles, optimisé pour retrouver des articles biomédicaux pertinents à partir d'une description clinique.

```python
# Utilisation MedCPT (auto-hébergé)
from transformers import AutoTokenizer, AutoModel
import torch

tokenizer = AutoTokenizer.from_pretrained("ncbi/MedCPT-Article-Encoder")
model = AutoModel.from_pretrained("ncbi/MedCPT-Article-Encoder")

inputs = tokenizer(
    [["titre de l'article", "abstract complet"]],
    return_tensors="pt",
    truncation=True,
    max_length=512
)
with torch.no_grad():
    embedding = model(**inputs).last_hidden_state[:, 0, :]
```

Prérequis : serveur avec ~4 Go RAM. CPU suffit pour l'inférence batch ; GPU accélère d'un facteur ~10.

---

## Comparaison finale des modèles pour X-Med

| Critère | `text-embedding-3-small` | `embed-v4.0` (Cohere) | `MedCPT` (open-source) |
|---|---|---|---|
| Qualité médicale | Bonne | Très bonne | Excellente |
| Multilingue (FR/EN) | Oui | Oui (natif) | Non (anglais PubMed) |
| Coût baseline 37M articles | ~$11 | ~$9 | $0 |
| Coût quotidien (4K articles) | ~$0.008 | ~$0.006 | $0 |
| Infra requise | Aucune (API) | Aucune (API) | Serveur CPU/GPU |
| Dépendance externe | OpenAI | Cohere | Aucune |
| Intégration | 30 min | 30 min | 1–2 jours |

---

## Recommandation par phase

**Phase pilote (< 500 médecins)**
→ `text-embedding-3-small` (OpenAI)
Zéro infrastructure, intégration en 30 minutes, coût négligeable ($11 baseline + $0.008/jour). Permet de valider l'approche rapidement.

**À l'échelle (500+ médecins)**
→ Migrer vers `MedCPT` auto-hébergé
Coût API zéro, meilleure précision sur le corpus PubMed, aucune dépendance à un fournisseur externe. Un serveur partagé avec les workers Celery existants suffit.

**Note** : pgvector est agnostique au modèle d'embedding. Changer de modèle = re-générer les vecteurs en batch, sans modifier le reste du code. La migration est non-destructive.

---

## Coûts consolidés avec Option B

### Par jour (100 médecins, 4 000 articles)

| Poste | Coût |
|---|---|
| Embeddings articles (4 000 × 300 tokens) | $0.008 |
| Claude scoring (100 médecins × 50 articles) | $1.80 |
| Claude résumés prioritaires | inclus |
| Envoi emails (Resend) | ~$0.10 |
| **Total / jour** | **~$1.91** |

### Baseline (one-shot)

| Poste | Coût |
|---|---|
| Embeddings 37M articles | ~$11 |
| Durée (10 workers parallèles) | ~1.5 jours |

---

## Ce que pgvector change dans la qualité du service

Le matching sémantique résout les cas que le filtre MeSH rate systématiquement :

- Synonymes cliniques : "infarctus du myocarde" ↔ "STEMI" ↔ "myocardial infarction"
- Nouvelles molécules sans MeSH term établi
- Articles dont l'abstract décrit la pathologie sans la nommer explicitement
- Profil médecin rédigé en français, articles indexés en anglais

Le résultat attendu : passage d'un rappel ~70% (MeSH seul) à ~90%+ (pgvector), mesuré sur le ratio d'articles jugés pertinents par les médecins dans leurs retours.
