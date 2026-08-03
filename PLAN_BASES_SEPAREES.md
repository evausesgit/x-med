# Plan — séparation en deux bases de données

> **Statut : proposition, non exécutée.**
>
> **À faire après** le nettoyage décrit dans [`PLAN_NETTOYAGE.md`](PLAN_NETTOYAGE.md).
> L'ordre compte : le nettoyage supprime à lui seul toutes les jointures qui traversent
> la frontière entre les deux bases, ce qui rend cette séparation purement mécanique.

## Le problème

Tout vit aujourd'hui dans une seule base (`x-med-db-1`, base `xmed`) : les 25 millions
d'articles PubMed **et** les comptes médecins, leurs profils, leurs recherches
sauvegardées. Trois conséquences :

1. **On ne peut pas développer sans les 75 Go.** Impossible de cloner l'environnement
   sur un autre poste, ou de démarrer une base de test rapidement.
2. **Le corpus fait tomber le reste.** Charger la baseline PubMed complète fait crasher
   Postgres — et ça emporte *tout*, y compris les comptes utilisateurs.
3. **Les données produit sont noyées.** Un `pg_dump` de sauvegarde, c'est 65 Go dont
   99,99 % est re-téléchargeable gratuitement depuis le FTP de la NLM.

## Le critère de découpage

Une seule question par table : **est-ce reconstructible gratuitement depuis PubMed ?**

- **Oui** → base **corpus** : énorme, jetable, re-téléchargeable
- **Non** (saisie humaine, appels LLM payants, données médecin) → base **app** :
  minuscule, précieuse, sauvegardable en 2 secondes

---

# Instance 1 — `xmed_corpus` (~72 Go)

Le miroir PubMed et ses accélérateurs de recherche.

| Table | Taille | Rôle |
|---|---|---|
| `articles` | 65 Go | le corpus PubMed brut (~25 M articles) |
| `article_search` | 7,5 Go | miroir plein-texte à fenêtre glissante — 3 412 286 lignes, articles ≥ 2024. Rend le pré-filtre rapide en permanence (~0,4 s au lieu de ~150 s à froid) |
| `mesh_descriptors` | 4,3 Mo | vocabulaire MeSH, alimenté par l'ingestion |
| `ftp_state` | 224 ko | quels fichiers `.xml.gz` ont déjà été ingérés — indissociable du corpus qu'il décrit |
| `alembic_version` | — | historique de migrations **propre à cette base** |

**Objets SQL rattachés** (migration `0006`) : le trigger `trg_article_search_sync` sur
`articles`, et les fonctions `article_search_min_year()` et `article_search_prune()`.

**Qui écrit** : uniquement le pipeline d'ingestion — `scripts/pubmed_daily.py`,
`app/tasks/parse_articles.py`, `scripts/backfill_article_search.py`,
`scripts/prune_article_search.py`, `scripts/load_baseline.py`.

**Qui lit** : l'API, en **lecture seule**.

---

# Instance 2 — `xmed_app` (~4 Mo)

Tout ce que X-Med produit et tout ce qui vient des utilisateurs.

| Table | Taille | Lignes | Rôle |
|---|---|---|---|
| `doctors` | 64 ko | 1 | comptes (email, Firebase UID, langue) |
| `doctor_profiles` | 32 ko | 1 | profil de veille (spécialité, pathologies, MeSH extra…) |
| `saved_searches` | 728 ko | **42** | recherches sauvegardées — le `payload` jsonb contient la réponse v2 complète |
| `search_runs` | 296 ko | 6 | recherches lancées en arrière-plan (logs, statut, payload) |
| `digest_runs` | 192 ko | 2 | historique des digests envoyés |
| `usage_events` | 64 ko | 21 | télémétrie d'usage |
| `article_fr` | 2 Mo | **904** | cache des traductions FR — **payé en tokens codex**, donc irremplaçable sans recoût |
| `alembic_version` | — | — | historique de migrations **propre à cette base** |

> Les tables `emb_bge_m3`, `emb_medcpt`, `bench_*` et `eval_*` n'apparaissent nulle part
> ici : elles auront disparu avec le nettoyage préalable.

---

# Ce qui rend la coupure sûre

## Aucune clé étrangère ne traverse la frontière

Les 9 clés étrangères de la base ont été relevées une par une. Toutes tombent
**à l'intérieur** d'un seul côté :

| Enfant | → Parent | Côté |
|---|---|---|
| `article_search.pmid` | `articles` | corpus ✓ |
| `doctor_profiles.doctor_id` | `doctors` | app ✓ |
| `saved_searches.doctor_id` | `doctors` | app ✓ |
| `search_runs.doctor_id` | `doctors` | app ✓ |
| `digest_runs.doctor_id` | `doctors` | app ✓ |

*(les 4 autres — `emb_*.pmid`, `bench_qrels.query_id`, `bench_results.run_id` —
disparaissent avec le nettoyage.)*

Point important : `article_fr.pmid` **n'a déjà aujourd'hui aucune clé étrangère** vers
`articles`. La séparation ne casse donc aucune contrainte d'intégrité existante.

## Aucune jointure SQL ne traverse la frontière

Un `JOIN` ne sait recoller que des tables vivant dans la même base : c'est le seul vrai
coût de ce genre de découpage. Avant nettoyage, 4 requêtes étaient concernées. **Après
nettoyage, il n'en reste aucune** — les quatre vivaient dans le code d'évaluation et
d'annotation qui disparaît (`app/api/eval.py:94`, `scripts/build_pool.py:56`,
`scripts/load_translations.py:64`, `scripts/bench_selection.py`).

Nuance honnête : trois scripts d'outillage lisent les deux mondes
(`pubmed_coverage.py`, `compare_v1_v2.py`, `bench_v1_v2.py` lisent `saved_searches`
puis interrogent `articles`). Mais ils le font en **deux requêtes séparées**, jamais par
un `JOIN` : il suffit de leur passer deux connexions au lieu d'une. Aucune logique à
réécrire.

---

# Comment on relie les deux

**Deux connexions applicatives — pas de `postgres_fdw`.** Le FDW (qui permet à Postgres
d'interroger une autre base comme si elle était locale) recréerait exactement le
couplage qu'on cherche à supprimer, avec un coût de performance en prime.

Dans `app/db.py`, un second moteur SQLAlchemy à côté de l'existant :

```python
DATABASE_URL         # → xmed_app     (lecture/écriture)
CORPUS_DATABASE_URL  # → xmed_corpus  (lecture seule)

SessionLocal        / get_session          # app
CorpusSessionLocal  / get_corpus_session   # corpus
```

Les endpoints de recherche prennent la session corpus, tout le reste (profils,
recherches sauvegardées, digests) garde la session app. Là où les deux se croisent, on
récupère une liste de PMID d'un côté et on va chercher leur contenu de l'autre en une
seule requête `WHERE pmid = ANY(:pmids)` — sur 20 à 40 identifiants en clé primaire,
c'est quelques millisecondes.

## Deux rôles Postgres distincts

| Rôle | Droits |
|---|---|
| `xmed_app` | lecture/écriture sur `xmed_app` · **lecture seule** sur `xmed_corpus` |
| `xmed_ingest` | lecture/écriture sur `xmed_corpus` (cron quotidien, backfills) |

L'API ne peut alors plus abîmer le corpus par accident, et le cron d'ingestion ne peut
pas toucher aux données médecins.

## Deux instances, pas seulement deux bases

Recommandation : **deux conteneurs Postgres séparés** plutôt que deux bases dans le même
serveur.

- Aujourd'hui, un crash Postgres pendant un chargement massif emporte *tout*. Séparés,
  le corpus peut tomber sans que les comptes médecins ne soient concernés.
- Le réglage mémoire est opposé : le corpus veut l'essentiel du `shared_buffers` pour
  garder `article_search` chaud en RAM, l'app n'a besoin de presque rien.

---

# Migration : on ne copie jamais les 65 Go

L'astuce : **`x-med-db-1` *devient* la base corpus.** On ne déplace pas les gros
fichiers, on en extrait seulement les petites tables.

1. **Dump des tables app** (~4 Mo, quelques secondes) :

   ```bash
   docker exec x-med-db-1 pg_dump -U xmed -d xmed \
     -t doctors -t doctor_profiles -t saved_searches -t search_runs \
     -t digest_runs -t usage_events -t article_fr \
     > xmed_app.sql
   ```

2. **Création du conteneur `x-med-app-db`** et restauration du dump dedans.

3. **Vérification** : `42` recherches sauvegardées, `904` traductions, les comptes et
   profils présents. On ne passe à l'étape suivante qu'après ce contrôle.

4. **`DROP TABLE`** de ces 7 tables côté corpus, et renommage du conteneur/base en
   `xmed_corpus`.

5. **Découpage d'Alembic** en deux historiques : `alembic/app/` et `alembic/corpus/`,
   chacun avec son `alembic_version`. Répartition des migrations existantes :

   | Migration | Destination |
   |---|---|
   | `0001_initial_schema` (articles, mesh, ftp_state) | corpus *(à amputer des tables supprimées)* |
   | `0006_article_search` | corpus |
   | `0002_doctors_profiles`, `0004_article_fr`, `0005_saved_searches`, `0007_usage_events`, `0008_doctor_firebase_uid`, `0009_digest_runs`, `0010_search_runs` | app |
   | `0003_eval_annotation`, `0011_drop_ml_eval` | supprimées par le nettoyage |

6. **Configuration** : `CORPUS_DATABASE_URL` ajoutée dans `.env`, `docker-compose.yml`,
   et côté Coolify.

**Retour arrière** : tant que l'étape 4 n'est pas faite, la bascule est réversible —
il suffit de repointer `DATABASE_URL` sur l'ancienne base.

---

# Ce que ça débloque pour la prod et les pull requests

C'est le bénéfice principal, au-delà du rangement.

### Développement local sans les 75 Go

`CORPUS_DATABASE_URL` peut pointer soit vers le vrai corpus, soit vers un **corpus
échantillon** de quelques dizaines de milliers d'articles. La base app, elle, tient dans
un fichier de 4 Mo qu'on peut versionner, copier sur un autre poste, ou réinitialiser en
deux secondes.

### Previews de PR sans dupliquer le corpus

Aujourd'hui, une preview de PR devrait soit partager la base de prod (risqué : une
migration en cours de revue s'applique aux vraies données), soit disposer de 75 Go à
elle. Avec deux bases :

- **le corpus est partagé en lecture seule** entre la prod et toutes les previews —
  aucune duplication, aucun risque, puisque personne n'y écrit à part le cron ;
- **chaque preview reçoit sa propre base app jetable** (4 Mo), créée depuis le dump ou
  vide, détruite avec la PR.

Une migration qui casse quelque chose ne casse alors que la base jetable de sa PR.

### Sauvegardes réalistes

La sauvegarde qui compte devient un dump de 4 Mo, réalisable plusieurs fois par jour et
restaurable en secondes. Le corpus n'a pas besoin d'être sauvegardé du tout : il est
re-téléchargeable depuis la NLM.

### Restaurations sans interruption

Recharger ou réparer le corpus (opération de plusieurs heures) n'oblige plus à toucher
à la base qui contient les comptes utilisateurs.

---

# Récapitulatif

| | `xmed_corpus` | `xmed_app` |
|---|---|---|
| **Taille** | ~72 Go | ~4 Mo |
| **Tables** | 4 + `alembic_version` | 7 + `alembic_version` |
| **Reconstructible ?** | oui, depuis PubMed | **non** |
| **Sauvegarde** | inutile | plusieurs fois par jour |
| **Écriture** | cron d'ingestion (`xmed_ingest`) | API (`xmed_app`) |
| **Partage entre environnements** | lecture seule, mutualisé | une base par environnement |

**Prérequis : le nettoyage doit être fait et validé d'abord.**
