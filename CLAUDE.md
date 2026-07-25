# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## État actuel du dépôt

Ce dépôt est en **phase de conception** : il ne contient pour l'instant que trois documents Markdown (en français). **Aucun code n'a encore été écrit.** Les commandes de build/test/lint n'existent donc pas encore — elles seront à créer en suivant la stack ci-dessous.

- `ARCHITECTURE.md` — architecture technique de référence (stack, schéma SQL, pipeline, endpoints, structure projet cible, coûts, phases)
- `PIPELINE_EMBEDDINGS.md` — extension du matching : recherche sémantique via pgvector + embeddings (remplace/complète le pré-filtre MeSH)
- `PRESENTATION_MEDECINS.md` — présentation produit destinée aux médecins (non technique)

Quand on implémente une fonctionnalité, **`ARCHITECTURE.md` et `PIPELINE_EMBEDDINGS.md` font foi** sur les choix de design (schéma de tables, noms de fichiers, ordre du pipeline). Garder ces documents synchronisés avec le code.

## De quoi il s'agit

X-Med est un service de veille médicale : il ingère quotidiennement les nouveaux articles PubMed, les filtre selon le profil d'un médecin, puis génère un digest email personnalisé (résumé + traduction).

**Langues.** La langue de travail interne (docs, commentaires de code, échanges) reste le **français**. Le **produit**, lui, est bilingue : l'**anglais est la langue principale** de l'interface, le français est au choix. Voir § Interface bilingue.

## Architecture — le flux de bout en bout

Le système est un **pipeline de batch quotidien** orchestré par Celery Beat, en 4 étapes séquentielles (voir `ARCHITECTURE.md` § Pipeline quotidien) :

1. **`tasks/ftp_download.py`** — télécharge les `.xml.gz` de `ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/`, suit l'état dans la table `ftp_state` pour ne traiter que les nouveaux fichiers.
2. **`tasks/parse_articles.py`** — parse le XML NLM en **streaming (lxml iterparse)**, dérive `evidence_level` (1–4) à partir des `PublicationType`, upsert dans `articles`. C'est aussi ici que l'**embedding** de chaque article est généré (voir pipeline sémantique).
3. **`tasks/ai_enrichment.py`** — pour chaque médecin, score les articles candidats via **Claude API** (scoring de pertinence 0–1 + résumé traduit + flag prioritaire), stocke dans `article_scores`.
4. **`tasks/send_digest.py`** — génère l'email HTML (template Jinja2) et l'envoie via **Resend**, journalise dans `digest_sent`.

Deux idées structurantes :

- **Matching en deux temps** (clé pour la maîtrise des coûts) : un **pré-filtre rapide** réduit ~4 000 articles/jour à quelques dizaines de candidats, *avant* tout appel à Claude. Le pré-filtre historique est une intersection d'arrays MeSH en SQL (`&&`) ; `PIPELINE_EMBEDDINGS.md` le remplace par une **recherche sémantique pgvector** (distance cosinus `<=>` + index HNSW) qui rattrape les synonymes cliniques et le franco-anglais. Seuls les candidats pré-filtrés passent au scoring Claude.
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

## Interface bilingue (anglais principal, français au choix)

Le front est traduit via un catalogue maison, sans dépendance ni routage par
locale (tout le site est derrière le login : l'argument SEO ne s'applique pas).

- `web/lib/messages/en.ts` — catalogue de **référence** : il définit le type
  `Messages`, donc une clé oubliée dans `fr.ts` est une **erreur TypeScript**.
- `web/lib/locale.ts` — noyau sans React : types, résolution des clés (`t`/`tp`,
  variables `{nom}`, pluriels), langue active de module pour le code non-React
  (messages d'erreur de `lib/api.ts`), cookie `xmed.locale`.
- `web/lib/i18n.tsx` — `I18nProvider`, hook `useT()`, sélecteur `LocaleSwitcher`.
- `web/lib/server-locale.ts` — lecture du cookie côté serveur.

**Autorité de la langue** : profil du médecin (`doctors.language`) > cookie
`xmed.locale` > anglais. Le cookie est lu dans le layout serveur, ce qui évite
un « flash » d'anglais et donne le bon `<html lang>` ; le provider corrige au
montage si le compte dit autre chose. Changer de langue écrit le cookie **et**
`PUT /me/language`, pour que la préférence suive le médecin d'un appareil à
l'autre.

**Défaut** : `doctors.language` vaut `'en'` pour les nouveaux comptes
(migration `0011`) ; les comptes existants gardent `'fr'` — seul le DÉFAUT de
la colonne change, aucune ligne n'est réécrite.

**Périmètre traduit** : pages médecin (recherche, digest, profil, recherches
sauvegardées, connexion, « Comment ça marche ») + navigation. Les outils
internes (`/annotate`, `/evaluation`, `/embeddings`) restent en français.

**Contenu des articles** : les abstracts PubMed sont en anglais — les afficher
ne coûte donc **aucun appel de traduction**. Le français passe par `codex` avec
cache en base (`article_fr`) ; par défaut la traduction suit la langue du
compte, et la bascule de chaque carte permet une dérogation à la demande.
⚠️ Le cache ne stocke QUE le français : ajouter une 3e langue demandera
d'étendre `article_fr` (→ `article_translation(pmid, lang)`) et les endpoints
`/translate` + `/translate/batch`.

## Stack cible (à respecter lors de l'implémentation)

Python 3.12 · PostgreSQL 16 (+ extension **pgvector**) · Redis + Celery / Celery Beat · SQLAlchemy + Alembic · lxml · FastAPI · Jinja2 · Docker Compose.

Services externes : **Claude API** (`claude-sonnet-4-6`) pour scoring/résumé/traduction ; un modèle d'**embedding** tiers pour les vecteurs (Claude n'expose pas d'embeddings — voir `PIPELINE_EMBEDDINGS.md` pour le comparatif ; `text-embedding-3-small` en pilote, `MedCPT` auto-hébergé à l'échelle) ; **Resend** pour l'email ; **PubMed E-utilities** (clé API NIH gratuite).

Structure projet cible et variables d'environnement : voir `ARCHITECTURE.md` (§ Structure du projet, § Variables d'environnement).

## Conventions de coûts (contraintes de design)

L'architecture est explicitement optimisée pour le coût des appels LLM. Toute modification du pipeline IA doit préserver ces leviers :
- **pré-filtre avant tout appel Claude** (jamais scorer 4 000 articles bruts) ;
- **prompt caching** sur la partie profil médecin (invariante d'un article à l'autre) ;
- l'embedding du profil médecin est **calculé une fois** et recalculé seulement si le profil change.
