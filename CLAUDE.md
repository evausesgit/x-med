# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## État actuel du dépôt

Le produit est **implémenté et déployé** : API FastAPI, front Next, base Postgres miroir de PubMed, cron d'ingestion quotidien. Tests : `uv run --group dev pytest -q`. Lint : `uv run --group dev ruff check`.

- `ARCHITECTURE.md` — architecture technique de référence (stack, schéma SQL, pipeline, endpoints, coûts, phases)
- `ALGO_RECHERCHE.md` et `PLAN_RECHERCHE_PUBMED_CODEX.md` — l'algorithme de recherche réellement en service
- `PRESENTATION_MEDECINS.md` — présentation produit destinée aux médecins (non technique)
- `PLAN_NETTOYAGE.md` / `PLAN_BASES_SEPAREES.md` — chantiers de rangement en cours

Quand on implémente une fonctionnalité, **`ARCHITECTURE.md` fait foi** sur les choix de design (schéma de tables, noms de fichiers, ordre du pipeline). Garder ce document synchronisé avec le code.

> **Chantiers retirés (juillet 2026).** Les embeddings (bge-m3, MedCPT), le pré-tri
> sémantique pgvector, le banc d'essai multi-modèles et le gold set d'annotation ont été
> supprimés du projet : le pré-tri par vecteurs s'est révélé peu cohérent face au filtre
> lexical suivi du jugement par l'IA. Ne pas les réintroduire sans décision explicite.

## De quoi il s'agit

X-Med est un service de veille médicale : il ingère quotidiennement les nouveaux articles PubMed, les filtre selon le profil d'un médecin, puis génère un digest email personnalisé (résumé + traduction). La langue de travail du projet (docs, copie produit, résumés générés) est le **français**.

## Architecture — le flux de bout en bout

Le système est un **pipeline de batch quotidien** orchestré par Celery Beat, en 4 étapes séquentielles (voir `ARCHITECTURE.md` § Pipeline quotidien) :

1. **`tasks/ftp_download.py`** — télécharge les `.xml.gz` de `ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/`, suit l'état dans la table `ftp_state` pour ne traiter que les nouveaux fichiers.
2. **`tasks/parse_articles.py`** — parse le XML NLM en **streaming (lxml iterparse)**, dérive `evidence_level` (1–4) à partir des `PublicationType`, upsert dans `articles`, et alimente le miroir plein-texte `article_search`.
3. **`tasks/ai_enrichment.py`** — pour chaque médecin, score les articles candidats via **Claude API** (scoring de pertinence 0–1 + résumé traduit + flag prioritaire), stocke dans `article_scores`.
4. **`tasks/send_digest.py`** — génère l'email HTML (template Jinja2) et l'envoie via **Resend**, journalise dans `digest_sent`.

Deux idées structurantes :

- **Matching en deux temps** (clé pour la maîtrise des coûts) : un **pré-filtre rapide** réduit le corpus à quelques dizaines de candidats *avant* tout appel au LLM. Ce pré-filtre est une **recherche plein-texte** (index GIN + tri `ts_rank`), sur la table étroite `article_search` quand la fenêtre de dates le permet (~0,4 s) et sur `articles` sinon. L'intersection d'arrays MeSH a été retirée du vivier local : un descripteur courant matchait des millions de lignes et faisait passer la requête de 0,4 s à ~200 s. Seuls les candidats pré-filtrés passent au jugement par l'IA.
- **Deux sources PubMed distinctes** : le **FTP NLM** (flux bulk quotidien, source principale du pipeline) et l'**API E-utilities** (`esearch`/`efetch`, pour la recherche ponctuelle à la demande depuis l'API FastAPI). Ne pas confondre les deux usages.

## Démarrer / redémarrer le backend proprement

Le moyen canonique de (re)lancer toute la stack dev est **`bash scripts/dev_up.sh`** : il
remonte Postgres+Redis, applique les migrations, relance l'**API FastAPI sur `:8800`**
(`0.0.0.0`, en daemon `setsid` détaché) et rebuild+relance le **front Next sur `:3003`**.
Il tue l'ancien process **par le port** (jamais `pkill -f`) et fait des health-checks.
Logs : `/tmp/xmed-api.log`, `/tmp/xmed-web.log`, `/tmp/xmed-web-build.log`.

⚠️ **Piège PATH (cause de « 502 codex introuvable » sur la recherche PubMed).** La
recherche PubMed + IA appelle le binaire **`codex`** (CLI GPT-5.6),
installé via **npm global dans `~/.npm-global/bin`**. Ce dossier est dans le PATH d'un
terminal interactif, mais **PAS** dans celui d'un process lancé par un **agent** (arbre
`systemd --user` → hermes gateway), dont le PATH est minimal. Si l'API a été démarrée par
un agent sans ce dossier, `codex` est introuvable et `/search/pubmed/deep` renvoie 502.
`scripts/dev_up.sh` force désormais `~/.npm-global/bin` dans le PATH ; **toujours
redémarrer le backend via ce script** (et pas un `uvicorn` lancé à la main) pour garantir
que `codex` est résolvable. Vérifier avec `command -v codex` avant de soupçonner le code.

## Stack cible (à respecter lors de l'implémentation)

Python 3.12 · PostgreSQL 16 · Redis + Celery / Celery Beat · SQLAlchemy + Alembic · lxml · FastAPI · Jinja2 · Docker Compose.

Services externes : **Claude API** (`claude-sonnet-4-6`) pour scoring/résumé/traduction ; **Resend** pour l'email ; **PubMed E-utilities** (clé API NIH gratuite).

Structure projet cible et variables d'environnement : voir `ARCHITECTURE.md` (§ Structure du projet, § Variables d'environnement).

## Conventions de coûts (contraintes de design)

L'architecture est explicitement optimisée pour le coût des appels LLM. Toute modification du pipeline IA doit préserver ces leviers :
- **pré-filtre avant tout appel Claude** (jamais scorer 4 000 articles bruts) ;
- **prompt caching** sur la partie profil médecin (invariante d'un article à l'autre).
