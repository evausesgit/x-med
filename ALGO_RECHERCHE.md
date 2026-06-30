# Algorithme de recherche — PubMed + IA (méthode « v2 »)

Pseudo-code de référence de la **seule** méthode de recherche en service (« PubMed +
codex »). Fidèle au code : `app/api/search.py` (`_run_deep_search`, `_run_deep_more`),
`app/services/query_builder.py`, `app/services/codex_judge.py`,
`app/services/pubmed_eutils.py`. Garder ce document synchronisé avec le code.

> Les termes techniques sont glosés au fil du texte (FTS, MeSH, ts_rank…).

---

## Vue d'ensemble — la recherche se fait en 3 temps

```
PRM (phrase du médecin, en français)
        │
   ┌────┴─────────────────────────────────────────────┐
   │ TEMPS 1 — fabriquer une bonne requête + 2 viviers │
   └────┬─────────────────────────────────────────────┘
        │   A = PubMed (le monde entier, frais)
        │   B = notre base locale (rapide, déjà chez nous)
        │
   ┌────┴───────────────────────────────────────┐
   │ TEMPS 2 — fusionner A∪B, récupérer le texte │
   └────┬───────────────────────────────────────┘
        │
   ┌────┴───────────────────────────────────────────────┐
   │ TEMPS 3 — l'IA LIT les résumés, note, on trie, on FR│
   └─────────────────────────────────────────────────────┘
```

Idée-clé : **l'IA ne note jamais 4 000 articles**. On pré-filtre vite et grossièrement
(mots-clés), puis l'IA lit en profondeur un **petit lot** (50). Les embeddings/pgvector
**ne sont pas** sur ce chemin (jugés peu cohérents).

---

## Paramètres (valeurs par défaut réelles)

```
PRM           = la question clinique, en français   (ex. « glaucome par fermeture de l'angle et atarax »)
date_from     = borne basse de publication          (défaut 2025-01-01 côté UI)
date_to       = borne haute                         (défaut = aujourd'hui)
k_pubmed      = 20      → taille de A (combien d'articles on demande à PubMed)
max_local     = 200     → taille max de B (vivier local pré-filtré)
judge_batch   = 50      → combien d'abstracts l'IA lit PAR lot
min_score     = 2       → seuil pour garder un article (note IA de 0 à 3)
```

---

## PSEUDO-CODE DÉTAILLÉ

### TEMPS 1 — Construire la requête, puis interroger les 2 sources

```
FONCTION recherche(PRM, date_from, date_to):

  # ---- 1a. L'IA traduit la question FR en requête PubMed experte ----
  # Pourquoi : envoyer la phrase française brute à PubMed donne de mauvais
  # résultats (les mots banals « et », « par » dominent). GPT-5.4 traduit
  # les CONCEPTS en anglais, ajoute synonymes/molécules, pose les tags.
  ESSAYER:
      {pubmed_query, mesh_terms, keywords_en} = CODEX_construire_requete(PRM)
      # ex. pubmed_query = ("Glaucoma, Angle-Closure"[MeSH] OR "angle closure"[tiab])
      #                     AND (hydroxyzine[tiab] OR atarax[tiab])
      #     mesh_terms   = ["Glaucoma, Angle-Closure", "Hydroxyzine"]
      #     keywords_en  = ["angle closure glaucoma", "hydroxyzine", "atarax", ...]
      builder = "codex"
      term    = pubmed_query
  SINON (codex KO ou quota dépassé):
      builder = "fallback"
      term    = PRM                      # repli : on envoie la question brute
      mesh_terms = [] ; keywords_en = []

  # ---- 1b. Source A = PubMed (E-utilities esearch) ----
  # On demande au plus k_pubmed (20) PMID, triés par pertinence PubMed,
  # filtrés sur la DATE DE PUBLICATION (pdat) dans [date_from, date_to].
  (total_pubmed, A_pmids) = PUBMED_esearch(term,
                                           retmax   = k_pubmed,
                                           sort     = "relevance",
                                           datetype = "publication",
                                           mindate  = date_from,
                                           maxdate  = date_to)
  SI esearch échoue → ERREUR 502 (PubMed indisponible)    # seul cas qui stoppe tout
```

### TEMPS 2 — Vivier local + fusion + récupération du texte

```
  # ---- 2a. Source B = notre base locale (filtre lexical + MeSH) ----
  # "FTS" = full-text search = recherche plein-texte Postgres sur titre+résumé.
  # On cherche les articles dont le texte matche les mots-clés anglais (en OU),
  # OU qui portent au moins un des tags MeSH demandés ("overlap" = intersection
  # non vide entre les MeSH de l'article et mesh_terms).
  texte_recherché = keywords_en joints par " OR "   (sinon PRM brut)

  B_pmids = SELECT pmid FROM articles
            WHERE  ( texte matche texte_recherché          # FTS
                     OR  mesh_de_l_article ∩ mesh_terms ≠ ∅ )  # MeSH
              AND  pub_year ≥ année(date_from)              # filtres date
              AND  pub_year ≤ année(date_to)
            ORDER BY pertinence_lexicale DESC               # "ts_rank"
            LIMIT max_local                                 # ≤ 200

  # ---- 2b. Fusion A ∪ B ----
  # On concatène A PUIS B et on déduplique en gardant le 1er vu.
  # ⇒ l'ORDRE est : PubMed d'abord, puis local. (Important pour le lot de 50.)
  candidats = dédup([ ...A_pmids, ...B_pmids ])

  # ---- 2c. Récupérer titre + résumé de chaque candidat ----
  db = articles_en_base(candidats)                  # ce qu'on a déjà localement
  manquants = A_pmids absents de db                 # surtout des articles PubMed récents
  SI manquants:
      # best-effort : un hoquet NCBI ne doit PAS faire échouer la recherche
      meta          = PUBMED_esummary(manquants)    # journal, année, doi, titre
      abstracts_ext = PUBMED_efetch(manquants)      # résumés
      # en cas d'échec réseau → on dégrade (titre/résumé manquants), pas de 500

  titre(p)    = db[p].titre    sinon meta[p].titre    sinon str(p)
  abstract(p) = db[p].résumé   sinon abstracts_ext[p] sinon None
```

### TEMPS 3 — L'IA lit et juge UN lot, puis on trie

```
  # ---- 3a. Qui est "jugeable" ? Ceux qui ont un résumé à lire ----
  jugeables   = [ p dans candidats SI abstract(p) non vide ]   # garde l'ordre fusionné
  premier_lot = jugeables[ 0 : judge_batch ]      # les 50 premiers
  reste       = jugeables[ judge_batch : ]        # gardés pour « Analyser 50 de plus »

  # ---- 3b. L'IA LIT les 50 résumés et note chacun ----
  # GPT-5.4 reçoit le PRM + (titre, résumé tronqué à 1200 caractères) de chaque
  # article, et renvoie pour chacun :
  #   score         = 0..3   0 hors-sujet · 1 marginal · 2 pertinent · 3 très pertinent
  #   relevance_pct = 0..100 (finesse cohérente avec score : 3≈80-100, 2≈55-79, …)
  #   reason        = 1 phrase « ce que l'article APPORTE » (pas une justif de note)
  ESSAYER:
      scores = CODEX_juger(PRM, [(titre(p), abstract(p)) pour p dans premier_lot])
      judge_mode = "codex"
  SINON (codex KO/quota):
      scores = {}
      judge_mode = "skipped"            # repli : aucun score
      reste = []                        # pas de pagination « 50 de plus »

  # ---- 3c. Assembler les résultats gardés ----
  résultats = []
  POUR chaque p dans candidats:
      j     = scores[p] (ou rien)
      score = j.score (ou None)

      SI judge_mode == "codex" ET (score est None OU score < min_score):
          IGNORER p          # l'IA a tourné → on ne garde QUE ses ≥ 2.
                             # (donc : les non-jugés et les hors-sujet disparaissent)
      # NB : si judge_mode == "skipped", on ne filtre rien (tout passe, sans score)

      source = "both"   si p ∈ A et p ∈ B
               "pubmed" si p ∈ A seulement
               "local"  si p ∈ B seulement

      résultats.ajouter( DeepHit{
          pmid, titre(p), journal, année, doi, url_pubmed,
          in_db          = (p est en base locale),
          source,
          evidence_level = niveau de preuve 1..4 (si connu localement, sinon None),
          score, relevance_pct, reason,
          abstract       = abstract(p)            # résumé EN original
      })

  # ---- 3d. LE TRI (par ordre de priorité des critères) ----
  trier résultats par:
      1) score          DÉCROISSANT   (3 avant 2 ; non-noté = -1, donc en dernier)
      2) relevance_pct  DÉCROISSANT   (départage 2 articles de même score)
      3) evidence_level CROISSANT     (1 = preuve la plus forte d'abord ; inconnu = 99, à la fin)
      4) pub_year       DÉCROISSANT   (le plus récent d'abord)

  # ---- 3e. Traduction FR ----
  POUR chaque résultat: si une traduction FR est DÉJÀ en cache → l'attacher (instantané)
  # le reste est traduit en streaming après coup (enrichit le cache au fil de l'eau)

  RETOURNER {
      query=PRM, pubmed_query, mesh_terms, keywords_en, builder, judge_mode,
      counts = { pubmed: |A|, local: |B|, merged: |candidats|,
                 judgeable: |jugeables|, judged: |scores|, kept: |résultats| },
      results   = résultats,          # = C, trié
      remaining = reste               # PMID jugeables non encore notés (pagination)
  }
```

### Pagination « 🔬 Analyser 50 de plus »

```
FONCTION analyser_plus(PRM, pmids = remaining[0:50]):
  # même 3b→3d, mais sur le lot fourni ; on garde ≥ min_score, on trie,
  # et le front FUSIONNE ces nouveaux hits avec les précédents (dédup PMID).
```

---

## Détails d'implémentation à connaître

- **Streaming SSE** : `/search/pubmed/deep/stream` émet le déroulé en direct (chaque
  étape avec son chrono) puis un événement `result`. Un **keep-alive toutes les 10 s**
  empêche un proxy de couper pendant le silence du jugement (~50 s).
- **Timeouts codex** : construction de requête 180 s ; jugement 420 s.
- **Abstract tronqué** à 1200 caractères avant d'être envoyé au juge (tient dans un
  seul appel).
- **Coût** : 2 appels codex par recherche initiale (1 requête + 1 jugement de 50) ;
  chaque « 50 de plus » = 1 appel jugement supplémentaire.

---

## Points de design à challenger (vrais choix, pas des bugs)

1. **Ordre de fusion A puis B** → comme on ne juge que les **50 premiers**, les articles
   **PubMed passent avant le local**. Sur une base locale fournie, de bons articles
   locaux peuvent attendre le « 50 de plus ». À discuter : entrelacer A/B ? trier le
   vivier fusionné par pertinence avant de couper à 50 ?
2. **On ne juge que 50 sur potentiellement ~220** → le reste est invisible tant qu'on
   ne clique pas « 50 de plus ». Volontaire (coût), mais décision produit.
3. **Seuil `min_score = 2`** → on jette les « marginaux » (1). Strict ou pas ?
4. **Tri : score IA avant niveau de preuve** → un score IA 3 sur un « case report »
   (preuve faible) passe devant un score 2 sur une méta-analyse. Voulu ?
5. **Repli sans IA (`skipped`)** → on **ne filtre pas** et il n'y a **pas de score** :
   les résultats sortent en ordre lexical brut. Cohérent ?
6. **`k_pubmed = 20`** seulement → fenêtre PubMed étroite. L'élargir augmente le vivier
   mais pas le nombre jugé (toujours 50).
