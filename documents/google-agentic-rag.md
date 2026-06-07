# Google Research — Agentic RAG (Cross-Corpus Retrieval)

- **Source** : Google Research blog, 5 juin 2026
- **Lien** : https://research.google/blog/unlocking-dependable-responses-with-gemini-enterprise-agent-platforms-agentic-rag/?utm_source=twitter&utm_medium=social&utm_campaign=social_post&utm_content=gr-acct
- **Copie locale** : `documents/google-agentic-rag.html` (page sauvegardée)
- **Auteurs** : Cyrus Rashtchian, Da-Cheng Juan (Google Research) — produit Gemini Enterprise Agent Platform (Google Cloud)

## Résumé

Le RAG classique fait **une seule recherche en un pas** et échoue sur les requêtes
**multi-sources / multi-hop** où l'info est éclatée entre plusieurs « îlots » de données.
Leur réponse : un workflow **multi-agents** qui planifie, réécrit, route et **itère** :

- **Orchestrator / Root Agent** — découpe la requête complexe
- **Planner Agent** — décide quelles sources interroger et dans quel ordre
- **Query Rewriter** — transforme une question floue en plusieurs requêtes ciblées
- **Search Fanout Agent** — lance les requêtes en parallèle sur plusieurs corpus
- **Sufficient Context Agent** (vraie nouveauté) — contrôle qualité qui vérifie *avant
  de répondre* si le contexte récupéré suffit ; sinon il dit **précisément ce qui
  manque** (log « Reason / Feedback / Gap ») et relance une recherche ciblée
- **Synthesis Agent** — rédige la réponse finale, *grounded*

**Résultats** : +34 % de factualité vs RAG standard ; 90,1 % de bonnes réponses même en
cross-corpus (4 sources concurrentes), à latence quasi identique. Benchmark = FramesQA
(824 questions multi-hop, 2 676 PDF), LLM-as-a-judge.

## Pertinence pour X-Med

**À connaître, pas à copier tel quel.**

- **Exemple-phare médical** : ils illustrent avec un médecin demandant médicaments de
  sortie + restrictions alimentaires + réactions allergiques d'un patient — typiquement
  une requête clinique composite.
- **Réutilisable à court terme** : la notion de **vérification de suffisance du contexte**
  comme garde-fou anti-hallucination dans nos résumés générés (Claude vérifie que les
  abstracts couvrent vraiment la facette de la requête). À rapprocher de notre approche
  LLM-as-a-judge dans le plan d'éval.
- **Query Rewriter + fanout** rejoint notre réflexion franco-anglais / synonymes cliniques.

**Divergences / limites :**

- Produit Gemini/Google Cloud propriétaire — notre stack est Claude + pgvector + bge-m3.
- C'est de l'agentic RAG **génératif Q&A multi-hop**, pas du **matching/veille** comme
  notre pipeline (filtrer 4 000 articles/jour → digest).
- L'itération multi-agents **coûte cher en appels LLM** → contraire à notre design
  optimisé coût (pré-filtre avant tout scoring Claude). Inadapté au pipeline batch quotidien.
- Le « cross-corpus » résout un problème (bases d'équipes séparées) qu'on n'a pas : notre
  corpus PubMed est unifié.

**Piste future** : pertinent surtout pour une éventuelle **recherche conversationnelle /
Q&A à la demande** (côté API E-utilities), où « cherche jusqu'à avoir assez de contexte »
aurait du sens.
