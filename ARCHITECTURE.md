# X-Med — Architecture technique

## Vue d'ensemble

Pipeline quotidien qui ingère les nouveaux articles PubMed et envoie à chaque médecin un digest personnalisé selon ses spécialités d'intérêt.

---

## Sources de données

**PubMed FTP** — `ftp.ncbi.nlm.nih.gov/pubmed/`

- Baseline annuel : `pubmed26n0001.xml.gz` → `pubmed26n1455.xml.gz` (~1455 fichiers, chargement initial unique)
- Update quotidien : 1 à 3 nouveaux fichiers publiés chaque jour ouvré (~5–20 Mo chacun)
- Format : XML compressé gzip, DTD NLM PubMed 2025

Chaque article contient : PMID, titre, abstract, auteurs, journal, MeSH terms, DOI, ID PMC (si open access).

---

## Stack technique

| Composant | Technologie |
|---|---|
| Langage principal | Python 3.12 |
| Base de données | PostgreSQL 16 |
| Cache / queue | Redis + Celery |
| ORM | SQLAlchemy |
| Parsing XML | lxml (streaming SAX pour les gros fichiers) |
| Emails | Resend (ou SendGrid) |
| Scheduler | Celery Beat (cron quotidien 6h) |
| API interne | FastAPI |
| Déploiement | Docker Compose |

---

## Schéma de base de données

```sql
-- Médecins
CREATE TABLE doctors (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Spécialités disponibles (référentiel)
CREATE TABLE specialties (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,          -- ex: "Cardiologie"
    mesh_terms  TEXT[] NOT NULL,        -- ex: ['Heart Diseases', 'Arrhythmias']
    keywords    TEXT[] DEFAULT '{}'     -- mots-clés titre/abstract optionnels
);

-- Abonnements médecin ↔ spécialités
CREATE TABLE doctor_specialties (
    doctor_id    UUID REFERENCES doctors(id),
    specialty_id INT  REFERENCES specialties(id),
    PRIMARY KEY (doctor_id, specialty_id)
);

-- Articles ingérés
CREATE TABLE articles (
    pmid         TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    abstract     TEXT,
    authors      JSONB,                 -- [{last, first, affiliation}]
    journal      TEXT,
    pub_date     DATE,
    mesh_terms   TEXT[],
    doi          TEXT,
    pmc_id       TEXT,
    ingested_at  TIMESTAMPTZ DEFAULT now()
);

-- Digest envoyés (évite les doublons)
CREATE TABLE digest_sent (
    doctor_id   UUID REFERENCES doctors(id),
    article_id  TEXT REFERENCES articles(pmid),
    sent_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (doctor_id, article_id)
);
```

---

## Pipeline quotidien

### Étape 1 — Téléchargement FTP

```
tasks/ftp_download.py

1. Se connecter au FTP NLM (anonymous login)
2. Lister les fichiers dans /pubmed/updatefiles/
3. Comparer avec la table `ftp_state` (dernier fichier téléchargé)
4. Télécharger uniquement les nouveaux fichiers .xml.gz
5. Vérifier le checksum MD5 (fichier .md5 fourni par NLM)
6. Stocker localement dans /data/incoming/
```

### Étape 2 — Parsing XML (streaming)

```
tasks/parse_articles.py

Pour chaque fichier .xml.gz :
1. Décompresser à la volée (gzip streaming)
2. Parser en SAX/iterparse pour éviter de charger 200 Mo en RAM
3. Pour chaque <PubmedArticle> :
   - Extraire PMID, titre, abstract, auteurs, journal, date
   - Extraire tous les <DescriptorName> → mesh_terms[]
   - Extraire ArticleIds (doi, pmc)
4. Upsert dans la table articles (ON CONFLICT DO NOTHING)
```

### Étape 3 — Matching spécialités

```
tasks/match_articles.py

Pour chaque article nouvellement ingéré :
1. Comparer article.mesh_terms avec specialty.mesh_terms (intersection)
2. Si keywords définis : chercher dans titre + abstract (ILIKE ou pg tsvector)
3. Résultat : liste de (doctor_id, article_pmid) à notifier
4. Filtrer ceux déjà dans digest_sent
5. Insérer dans une table match_queue
```

### Étape 4 — Envoi des digests

```
tasks/send_digest.py

Pour chaque médecin ayant des articles en attente :
1. Regrouper les articles par spécialité
2. Générer un email HTML avec :
   - Titre de l'article (lien vers PubMed)
   - Abstract tronqué à 300 mots
   - Auteurs + journal
   - Bouton "Lire l'article" → DOI ou lien PMC si open access
3. Envoyer via Resend API
4. Marquer dans digest_sent
```

---

## Structure du projet

```
x-med/
├── docker-compose.yml
├── .env.example
├── alembic/                  # migrations BDD
├── app/
│   ├── models/               # SQLAlchemy models
│   ├── tasks/
│   │   ├── ftp_download.py
│   │   ├── parse_articles.py
│   │   ├── match_articles.py
│   │   └── send_digest.py
│   ├── api/                  # FastAPI (gestion médecins/spécialités)
│   ├── templates/
│   │   └── digest_email.html
│   └── config.py
├── scripts/
│   └── load_baseline.py      # chargement initial one-shot
└── tests/
```

---

## Référentiel des spécialités (initialisation)

```python
SPECIALTIES = [
    {
        "name": "Cardiologie",
        "mesh_terms": ["Heart Diseases", "Myocardial Infarction", "Arrhythmias",
                       "Heart Failure", "Coronary Artery Disease", "Atrial Fibrillation"]
    },
    {
        "name": "Oncologie",
        "mesh_terms": ["Neoplasms", "Antineoplastic Agents", "Cancer",
                       "Tumor Microenvironment", "Immunotherapy"]
    },
    {
        "name": "Neurologie",
        "mesh_terms": ["Brain Diseases", "Stroke", "Parkinson Disease",
                       "Alzheimer Disease", "Multiple Sclerosis", "Epilepsy"]
    },
    {
        "name": "Pneumologie",
        "mesh_terms": ["Lung Diseases", "Asthma", "Pulmonary Fibrosis",
                       "COVID-19", "COPD", "Respiratory Distress Syndrome"]
    },
    {
        "name": "Infectiologie",
        "mesh_terms": ["Communicable Diseases", "Anti-Bacterial Agents",
                       "HIV Infections", "Tuberculosis", "Sepsis"]
    },
    {
        "name": "Endocrinologie",
        "mesh_terms": ["Diabetes Mellitus", "Thyroid Diseases", "Obesity",
                       "Metabolic Syndrome", "Endocrine System Diseases"]
    },
    {
        "name": "Rhumatologie",
        "mesh_terms": ["Arthritis, Rheumatoid", "Lupus Erythematosus",
                       "Osteoporosis", "Spondylarthritis", "Gout"]
    },
]
```

---

## Cron schedule (Celery Beat)

```python
CELERY_BEAT_SCHEDULE = {
    "daily-pipeline": {
        "task": "tasks.run_daily_pipeline",
        "schedule": crontab(hour=6, minute=0),  # 6h du matin
    }
}
```

Ordre d'exécution : `ftp_download` → `parse_articles` → `match_articles` → `send_digest`

---

## Variables d'environnement

```env
DATABASE_URL=postgresql://xmed:password@localhost:5432/xmed
REDIS_URL=redis://localhost:6379/0
RESEND_API_KEY=re_xxxxxxxxxxxx
FTP_HOST=ftp.ncbi.nlm.nih.gov
FTP_PUBMED_PATH=/pubmed/updatefiles/
DATA_DIR=/data/incoming
```

---

## Phases de développement

| Phase | Contenu | Durée estimée |
|---|---|---|
| 1 | BDD + parsing XML + chargement baseline | 1 semaine |
| 2 | Matching MeSH + logique digest | 1 semaine |
| 3 | Envoi email + templates | 3 jours |
| 4 | API FastAPI (gestion médecins) | 1 semaine |
| 5 | Docker + déploiement | 3 jours |
| 6 | Interface web médecin (préférences) | selon besoin |
