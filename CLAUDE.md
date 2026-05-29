# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## État actuel du dépôt

Ce dépôt est en **phase de conception** : il ne contient pour l'instant que trois documents Markdown (en français). **Aucun code n'a encore été écrit.** Les commandes de build/test/lint n'existent donc pas encore — elles seront à créer en suivant la stack ci-dessous.

- `ARCHITECTURE.md` — architecture technique de référence (stack, schéma SQL, pipeline, endpoints, structure projet cible, coûts, phases)
- `PIPELINE_EMBEDDINGS.md` — extension du matching : recherche sémantique via pgvector + embeddings (remplace/complète le pré-filtre MeSH)
- `PRESENTATION_MEDECINS.md` — présentation produit destinée aux médecins (non technique)

Quand on implémente une fonctionnalité, **`ARCHITECTURE.md` et `PIPELINE_EMBEDDINGS.md` font foi** sur les choix de design (schéma de tables, noms de fichiers, ordre du pipeline). Garder ces documents synchronisés avec le code.

## De quoi il s'agit

X-Med est un service de veille médicale : il ingère quotidiennement les nouveaux articles PubMed, les filtre selon le profil d'un médecin, puis génère un digest email personnalisé (résumé + traduction). La langue de travail du projet (docs, copie produit, résumés générés) est le **français**.

## Architecture — le flux de bout en bout

Le système est un **pipeline de batch quotidien** orchestré par Celery Beat, en 4 étapes séquentielles (voir `ARCHITECTURE.md` § Pipeline quotidien) :

1. **`tasks/ftp_download.py`** — télécharge les `.xml.gz` de `ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/`, suit l'état dans la table `ftp_state` pour ne traiter que les nouveaux fichiers.
2. **`tasks/parse_articles.py`** — parse le XML NLM en **streaming (lxml iterparse)**, dérive `evidence_level` (1–4) à partir des `PublicationType`, upsert dans `articles`. C'est aussi ici que l'**embedding** de chaque article est généré (voir pipeline sémantique).
3. **`tasks/ai_enrichment.py`** — pour chaque médecin, score les articles candidats via **Claude API** (scoring de pertinence 0–1 + résumé traduit + flag prioritaire), stocke dans `article_scores`.
4. **`tasks/send_digest.py`** — génère l'email HTML (template Jinja2) et l'envoie via **Resend**, journalise dans `digest_sent`.

Deux idées structurantes :

- **Matching en deux temps** (clé pour la maîtrise des coûts) : un **pré-filtre rapide** réduit ~4 000 articles/jour à quelques dizaines de candidats, *avant* tout appel à Claude. Le pré-filtre historique est une intersection d'arrays MeSH en SQL (`&&`) ; `PIPELINE_EMBEDDINGS.md` le remplace par une **recherche sémantique pgvector** (distance cosinus `<=>` + index HNSW) qui rattrape les synonymes cliniques et le franco-anglais. Seuls les candidats pré-filtrés passent au scoring Claude.
- **Deux sources PubMed distinctes** : le **FTP NLM** (flux bulk quotidien, source principale du pipeline) et l'**API E-utilities** (`esearch`/`efetch`, pour la recherche ponctuelle à la demande depuis l'API FastAPI). Ne pas confondre les deux usages.

## Stack cible (à respecter lors de l'implémentation)

Python 3.12 · PostgreSQL 16 (+ extension **pgvector**) · Redis + Celery / Celery Beat · SQLAlchemy + Alembic · lxml · FastAPI · Jinja2 · Docker Compose.

Services externes : **Claude API** (`claude-sonnet-4-6`) pour scoring/résumé/traduction ; un modèle d'**embedding** tiers pour les vecteurs (Claude n'expose pas d'embeddings — voir `PIPELINE_EMBEDDINGS.md` pour le comparatif ; `text-embedding-3-small` en pilote, `MedCPT` auto-hébergé à l'échelle) ; **Resend** pour l'email ; **PubMed E-utilities** (clé API NIH gratuite).

Structure projet cible et variables d'environnement : voir `ARCHITECTURE.md` (§ Structure du projet, § Variables d'environnement).

## Conventions de coûts (contraintes de design)

L'architecture est explicitement optimisée pour le coût des appels LLM. Toute modification du pipeline IA doit préserver ces leviers :
- **pré-filtre avant tout appel Claude** (jamais scorer 4 000 articles bruts) ;
- **prompt caching** sur la partie profil médecin (invariante d'un article à l'autre) ;
- l'embedding du profil médecin est **calculé une fois** et recalculé seulement si le profil change.
