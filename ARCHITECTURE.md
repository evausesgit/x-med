# X-Med — Architecture technique

## Vue d'ensemble

Pipeline hybride qui combine :
- **Ingestion bulk FTP** : flux quotidien NLM pour les nouveaux articles
- **API PubMed E-utilities** : recherche ponctuelle à la demande
- **Claude API** : enrichissement IA (scoring de pertinence, résumé, traduction)
- **Digest personnalisé** : email généré par profil médecin

### Explicabilité des résultats

L'API de recherche joint à chaque article une explication factuelle calculée
après le classement, sans modifier son score :

- concepts principaux issus des descripteurs MeSH PubMed ;
- population issue des descripteurs démographiques ou d'une mention détectée
  dans l'abstract ;
- intervention issue d'une mention détectée dans l'abstract ;
- type d'étude issu des `PublicationType` PubMed.

Ces éléments sont des indices de lecture, pas une validation clinique ni
l'explication mathématique du score d'embedding. L'interface les présente dans
un panneau repliable « Pourquoi ce résultat ? ». Une future version pourra
expliquer le score du reranker lorsqu'un tel modèle aura été évalué.

---

## Sources de données

### 1. FTP NLM (pipeline principal — quotidien)
`ftp.ncbi.nlm.nih.gov/pubmed/`

- Baseline annuel : `pubmed26n0001.xml.gz` → `pubmed26n1455.xml.gz` (chargement initial unique)
- Update quotidien : 1 à 3 fichiers `.xml.gz` publiés chaque jour ouvré (~5–20 Mo)
- Format : XML compressé gzip, DTD NLM PubMed 2025
- Contenu : PMID, titre, abstract, auteurs, journal, MeSH terms, DOI, PMC ID

### 2. PubMed E-utilities API (recherche ponctuelle)
`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

- `esearch.fcgi` : recherche par mots-clés, MeSH, filtres (date, type d'étude, journal)
- `efetch.fcgi` : récupération d'articles spécifiques par PMID
- Rate limit : 10 req/s avec API key (gratuite, inscription NIH)
- Usage : recherche manuelle depuis l'interface médecin

---

## Stack technique

| Composant | Technologie |
|---|---|
| Langage principal | Python 3.12 |
| Base de données | PostgreSQL 16 |
| Cache / queue | Redis + Celery |
| ORM | SQLAlchemy + Alembic |
| Parsing XML | lxml (iterparse streaming) |
| IA / LLM | Claude API (Anthropic) — claude-sonnet-4-6 |
| Emails | Resend |
| Scheduler | Celery Beat |
| API interne | FastAPI |
| Déploiement | Docker Compose |

---

## Schéma de base de données

```sql
-- Médecins
CREATE TABLE doctors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'fr',     -- langue de réception
    digest_frequency TEXT NOT NULL DEFAULT 'daily', -- 'daily' | 'weekly'
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Profil détaillé du médecin
CREATE TABLE doctor_profiles (
    doctor_id           UUID PRIMARY KEY REFERENCES doctors(id),
    specialty_main      TEXT NOT NULL,              -- ex: "Cardiologie"
    subspecialties      TEXT[] DEFAULT '{}',        -- ex: ['Rythmologie', 'IC']
    pathologies         TEXT[] DEFAULT '{}',        -- ex: ['FA', 'STEMI']
    treatments          TEXT[] DEFAULT '{}',        -- ex: ['Anticoagulants', 'ICD']
    study_types         TEXT[] DEFAULT '{}',        -- ex: ['RCT', 'meta-analysis']
    min_evidence_level  INT DEFAULT NULL,           -- 1=le plus haut, 4=le plus bas
    preferred_journals  TEXT[] DEFAULT '{}',        -- ex: ['NEJM', 'Lancet']
    mesh_terms_extra    TEXT[] DEFAULT '{}',        -- termes MeSH additionnels personnalisés
    keywords_extra      TEXT[] DEFAULT '{}',        -- mots-clés libres additionnels
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Spécialités (référentiel système)
CREATE TABLE specialties (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    mesh_terms  TEXT[] NOT NULL,
    keywords    TEXT[] DEFAULT '{}'
);

-- Articles ingérés
CREATE TABLE articles (
    pmid            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    abstract        TEXT,
    authors         JSONB,
    journal         TEXT,
    issn            TEXT,
    pub_date        DATE,
    mesh_terms      TEXT[],
    doi             TEXT,
    pmc_id          TEXT,
    publication_types TEXT[],   -- ex: ['Randomized Controlled Trial', 'Meta-Analysis']
    evidence_level  INT,        -- 1-4, dérivé de publication_types
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

-- Scoring IA par article × médecin (généré par Claude)
CREATE TABLE article_scores (
    doctor_id       UUID REFERENCES doctors(id),
    pmid            TEXT REFERENCES articles(pmid),
    relevance_score FLOAT NOT NULL,         -- 0.0 à 1.0
    summary_fr      TEXT,                   -- résumé généré en langue du médecin
    summary_lang    TEXT,                   -- langue du résumé
    is_priority     BOOLEAN DEFAULT false,  -- top 3 du digest
    scored_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (doctor_id, pmid)
);

-- Digest envoyés
CREATE TABLE digest_sent (
    doctor_id   UUID REFERENCES doctors(id),
    pmid        TEXT REFERENCES articles(pmid),
    sent_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (doctor_id, pmid)
);

-- État du FTP (suivi des fichiers téléchargés)
CREATE TABLE ftp_state (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT,
    downloaded_at TIMESTAMPTZ DEFAULT now()
);
```

---

## Pipeline quotidien

```
06:00  FTP Download    → télécharge nouveaux fichiers .xml.gz
06:15  Parse Articles  → extrait et insère en base
06:30  AI Enrichment   → scoring + résumé + traduction (Claude API)
08:00  Send Digests    → email HTML personnalisé par médecin
```

### Étape 1 — Téléchargement FTP

```
tasks/ftp_download.py

1. Connexion FTP anonyme à ftp.ncbi.nlm.nih.gov
2. Lister /pubmed/updatefiles/ → comparer avec ftp_state
3. Télécharger uniquement les fichiers non traités (.xml.gz)
4. Vérifier checksum MD5 (fichier .md5 joint par NLM)
5. Stocker dans /data/incoming/
6. Insérer dans ftp_state
```

### Étape 2 — Parsing XML (streaming)

```
tasks/parse_articles.py

Pour chaque .xml.gz non encore parsé :
1. Décompresser + parser en iterparse (streaming SAX)
2. Pour chaque <PubmedArticle> :
   a. Extraire : PMID, titre, abstract, auteurs, journal, ISSN, date
   b. Extraire MeSH terms (<DescriptorName>)
   c. Extraire publication types (<PublicationType>) → dériver evidence_level :
        - RCT / Meta-Analysis / Systematic Review   → niveau 1
        - Cohort / Case-Control                     → niveau 2
        - Case Series / Case Report                 → niveau 3
        - Expert Opinion / Editorial                → niveau 4
   d. Extraire ArticleIds : doi, pmc
3. Upsert dans articles (ON CONFLICT (pmid) DO NOTHING)
```

### Étape 3 — Enrichissement IA (Claude API)

```
tasks/ai_enrichment.py

Pour chaque médecin, pour chaque article candidat (MeSH match initial) :

1. Construire un prompt avec :
   - Profil du médecin (spécialité, pathologies, traitements, types d'études)
   - Titre + abstract de l'article
   - Type d'étude + niveau de preuve

2. Appeler claude-sonnet-4-6 avec le prompt :
   "Sur une échelle de 0 à 1, évalue la pertinence de cet article
    pour ce profil médecin. Réponds en JSON :
    { score: float, priority: bool, summary: string (150 mots max, en [langue]) }"

3. Stocker dans article_scores :
   - relevance_score
   - is_priority (score > 0.8)
   - summary traduit dans la langue du médecin

4. Filtrer : ne conserver que les articles avec score > 0.4

Optimisation coûts API :
- Prompt caching sur la partie profil médecin (invariante)
- Batch processing : grouper les articles par médecin
- Ne scorer que les articles avec au moins 1 MeSH term commun (filtre préalable)
```

### Étape 4 — Envoi des digests

```
tasks/send_digest.py

Pour chaque médecin ayant des articles scorés non envoyés :
1. Récupérer les articles triés par relevance_score DESC
2. Séparer : is_priority=true (section "Prioritaire") + le reste
3. Générer email HTML depuis template Jinja2 :
   - Articles prioritaires en tête avec résumé complet
   - Autres articles : titre + journal + lien
   - Chaque article : lien PubMed + lien PMC si pmc_id présent
4. Envoyer via Resend API
5. Insérer dans digest_sent
```

---

## Profil médecin → stratégie de matching

Le matching se fait en deux temps :

**Pré-filtre (rapide, SQL)** — élimine les articles sans rapport :
```sql
-- Articles dont les MeSH terms intersectent avec le profil
SELECT a.pmid FROM articles a
WHERE a.mesh_terms && (
    SELECT mesh_terms FROM specialties WHERE name = doctor_specialty
    UNION ALL
    SELECT dp.mesh_terms_extra FROM doctor_profiles dp WHERE dp.doctor_id = $1
)
AND a.pmid NOT IN (SELECT pmid FROM digest_sent WHERE doctor_id = $1)
AND (dp.min_evidence_level IS NULL OR a.evidence_level <= dp.min_evidence_level)
```

**Scoring fin (Claude API)** — sur les candidats restants uniquement.

---

## API FastAPI — endpoints principaux

```
POST   /doctors                    création compte médecin
PUT    /doctors/{id}/profile       mise à jour profil
GET    /doctors/{id}/digest        digest courant (JSON)
GET    /doctors/{id}/history       articles déjà reçus
POST   /search                     recherche PubMed E-utilities
GET    /specialties                liste des spécialités disponibles
```

---

## Structure du projet

```
x-med/
├── docker-compose.yml
├── .env.example
├── alembic/
│   └── versions/
├── app/
│   ├── models/
│   │   ├── doctor.py
│   │   ├── article.py
│   │   └── score.py
│   ├── tasks/
│   │   ├── ftp_download.py
│   │   ├── parse_articles.py
│   │   ├── ai_enrichment.py      ← nouveau
│   │   └── send_digest.py
│   ├── api/
│   │   ├── doctors.py
│   │   ├── search.py             ← nouveau (E-utilities)
│   │   └── specialties.py
│   ├── services/
│   │   ├── claude_client.py      ← nouveau
│   │   ├── pubmed_ftp.py
│   │   └── pubmed_search.py      ← nouveau
│   ├── templates/
│   │   └── digest_email.html
│   └── config.py
├── scripts/
│   └── load_baseline.py
└── tests/
```

---

## Variables d'environnement

```env
DATABASE_URL=postgresql://xmed:password@localhost:5432/xmed
REDIS_URL=redis://localhost:6379/0
RESEND_API_KEY=re_xxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
PUBMED_API_KEY=xxxxxxxxxxxx          # NIH, gratuit
FTP_HOST=ftp.ncbi.nlm.nih.gov
FTP_PUBMED_PATH=/pubmed/updatefiles/
DATA_DIR=/data/incoming
```

---

## Estimation des coûts Claude API

Par médecin et par jour (hypothèse : 20 articles candidats après pré-filtre) :

| Opération | Tokens | Coût estimé |
|---|---|---|
| Prompt profil médecin (caché) | ~300 tokens | ~0 (cache hit) |
| Abstract × 20 articles | ~4 000 tokens input | ~$0.003 |
| Résumés × 20 articles | ~3 000 tokens output | ~$0.015 |
| **Total par médecin/jour** | | **~$0.018** |

Pour 100 médecins : ~$1.80/jour soit ~$55/mois.

---

## Phases de développement

| Phase | Contenu | Durée estimée |
|---|---|---|
| 1 | BDD + parsing XML + chargement baseline | 1 semaine |
| 2 | Pré-filtre MeSH + pipeline FTP quotidien | 1 semaine |
| 3 | Intégration Claude API (scoring + résumé + traduction) | 1 semaine |
| 4 | Templates email + envoi Resend | 3 jours |
| 5 | API FastAPI (CRUD médecins + profils) | 1 semaine |
| 6 | Recherche PubMed E-utilities | 3 jours |
| 7 | Docker + déploiement | 3 jours |
| 8 | Interface web médecin (gestion profil) | selon besoin |

---

## Ce que l'architecture précédente gardait

- Pipeline FTP NLM : inchangé, toujours la source principale
- Parsing XML iterparse : inchangé
- Pré-filtre MeSH en SQL : conservé comme première étape
- PostgreSQL + Celery + FastAPI : inchangé

## Ce qui a changé

- **Profil médecin** : beaucoup plus riche (sous-spécialités, pathologies, traitements, types d'études, niveau de preuve, revues)
- **Étape IA ajoutée** : scoring de pertinence + résumé + traduction via Claude API
- **Evidence level** : dérivé automatiquement des publication types PubMed
- **Recherche à la demande** : ajout PubMed E-utilities API
- **Coût maîtrisé** : prompt caching + pré-filtre SQL avant tout appel IA
