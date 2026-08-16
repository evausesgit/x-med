# Algorithmes de recherche X-Med

Ce document décrit **toutes les méthodes de recherche** de X-Med, avec le pseudo-code
détaillé de la principale (PubMed + IA). Fidèle au code : `app/api/search.py`,
`app/services/{query_builder,codex_judge,pubmed_eutils}.py`. Garder ce
document synchronisé avec le code.

> Termes techniques glosés au fil du texte (FTS, MeSH, ts_rank, RRF…).

## Les méthodes disponibles (barre « MÉTHODE » de l'UI)

| Méthode | Libellé UI | Endpoint | Principe en une phrase |
|---|---|---|---|
| **PubMed + IA** | « PubMed + IA » | `/search/pubmed/deep/stream` | requête experte (codex) → vivier PubMed + base locale → **Codex lit et juge** chaque abstract |

C'est désormais la **seule** méthode de recherche. Les modes « Par sens » (sémantique),
« Mots-clés / MeSH », plein-texte et hybride ont été retirés du produit : le pré-tri par
vecteurs s'est révélé peu cohérent, et les autres n'étaient plus appelés par le front.
Elle se règle en **deux variantes**, v1 et v2, décrites plus bas.

---

# 1. PubMed + IA (méthode principale)

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
(mots-clés), puis l'IA lit en profondeur un **petit lot** (50).

## Les DEUX sources d'une recherche (A et B) — rôles, tailles, limites

Une recherche interroge **deux fonds en parallèle**, puis les fusionne. Ils sont
complémentaires : A apporte la **fraîcheur** (le monde entier, y compris ce qu'on n'a pas
encore en base), B apporte la **rapidité et le plein-texte** (résumés déjà chez nous, pas
d'aller-retour réseau). ~39 % des articles finalement jugés pertinents viennent du **local
seul** → les deux comptent.

| | **A — PubMed en direct** | **B — Base locale** |
|---|---|---|
| **Ce que c'est** | API NCBI E-utilities (`esearch`) | Notre miroir Postgres de PubMed |
| **Couverture** | Le monde entier, temps réel | ~**25 M articles / 75 Go** (miroir ~complet) |
| **Comment on cherche** | Requête experte Codex, tri « Best Match » PubMed | Plein-texte (FTS, index GIN) trié par `ts_rank` |
| **Combien on prend** | `k_pubmed` = **20** (fenêtre étroite) | `max_local` = **≤ 200** |
| **Vitesse typique** | ~0,5–1 s (réseau NCBI) | ~**0,4–0,5 s** (index préchargé) |
| **Limite de temps** | dépendant de NCBI ; échec `esearch` → **502**, stoppe tout | **8 s** (`statement_timeout`) → si dépassé, B = ∅, on continue sur A |
| **Texte des résumés** | à récupérer (`esummary`/`efetch`, best-effort) | déjà en base (instantané) |
| **Filtre date** | `pdat` dans `[date_from, date_to]` | `pub_year` dans les mêmes bornes |

**Pourquoi B peut être lente (et le garde-fou 8 s).** À 25 M lignes, le coût du FTS
dépend de la **fréquence des mots**, pas du nombre de résultats : des mots courants
(« bleeding », « heart »…) ont des listes d'index énormes à parcourir et à trier. La
plupart des requêtes cliniques (termes précis) reviennent en ~0,5 s ; les sujets très
larges sont coupés à 8 s et basculent sur PubMed seul.

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

  # ---- 1a. L'IA décrit le SENS, le programme rédige la requête ----
  # Pourquoi une IA : envoyer la phrase française brute à PubMed donne de
  # mauvais résultats (les mots banals « et », « par » dominent). L'IA traduit
  # les CONCEPTS en anglais et trouve les synonymes et noms de molécules.
  # Pourquoi PAS l'IA pour la requête elle-même : une chaîne PubMed est un objet
  # à syntaxe libre (quel concept en [MeSH] ou [tiab], quelles parenthèses, quel
  # ordre) — des centaines de formes sont valides et le modèle en tirait une au
  # sort à chaque appel. Mesuré en août 2026 sur 3 appels IDENTIQUES : 12,4
  # articles communs sur 20 seulement, et jusqu'à 5,6x d'écart sur le nombre de
  # résultats. Un contre-témoin a écarté la piste du modèle (l'écart entre deux
  # modèles n'est pas distinguable de l'écart entre deux appels identiques,
  # p = 0,32) : la cause était la liberté laissée, pas le modèle. Le CLI codex
  # n'ayant ni température ni graine, le déterminisme ne peut venir que du
  # RÉTRÉCISSEMENT DE L'ESPACE DE SORTIE.
  ESSAYER:
      concepts = CODEX_decouper_en_concepts(PRM)
      # ex. [{mesh: ["Glaucoma, Angle-Closure"],
      #       synonyms_en: ["angle closure glaucoma", "acute angle-closure", ...]},
      #      {mesh: ["Hydroxyzine"], synonyms_en: ["hydroxyzine", "atarax", ...]}]
      #
      # Trois règles portées par le prompt :
      #   FIDÉLITÉ  — ne jamais remplacer un concept par sa version générale
      #               (« IC à FEVG préservée » ≠ « insuffisance cardiaque ») ;
      #   ENTITÉS   — pas de concept méthodologique (efficacité, résultat,
      #               tolérance…) : ces mots sont dans presque tous les articles,
      #               ne filtrent rien de fiable et faisaient varier le nombre de
      #               résultats d'un facteur 10 ; c'est le juge qui tranchera.
      #               Et pas de bloc redondant (« mélanome stade III » ET
      #               « mélanome » ne restreint rien et écarte des articles) ;
      #   LARGEUR   — dans un concept, toutes les formes courantes d'abord, puis
      #               les rares : elles sont en OU, un synonyme rare ne coûte
      #               rien et ramène parfois l'article que personne ne trouve.

      # Chaque descripteur MeSH est VALIDÉ contre la table `mesh_descriptors`
      # (~30 600 descripteurs vus à l'ingestion). Un descripteur inventé renvoie
      # 0 SILENCIEUSEMENT sur PubMed — « Photodynamic Therapy »[MeSH] = 0 contre
      # « Photochemotherapy »[MeSH] = 32 408 — et les [tiab] en OU masquaient la
      # perte. Trois réécritures automatiques (tag collé, qualificatif /therapy,
      # inversion « Adjuvant Chemotherapy » → « Chemotherapy, Adjuvant ») ;
      # ce qui reste introuvable est rétrogradé en [tiab] au lieu de rendre 0.
      # Les molécules récentes ne SONT PAS des descripteurs (aflibercept[MeSH]
      # = 0, [tiab] = 4 276) : elles passent naturellement par ce chemin.
      {pubmed_query, mesh_terms, keywords_en, concepts_en} = ASSEMBLER(concepts)
      # ex. pubmed_query = ("Glaucoma, Angle-Closure"[MeSH] OR "angle closure"[tiab])
      #                     AND ("Hydroxyzine"[MeSH] OR "atarax"[tiab])
      # Termes cités et TRIÉS dans chaque bloc : les guillemets ne changent aucun
      # compte PubMed (vérifié, troncature comprise) et le tri supprime une
      # variation gratuite. L'ordre des CONCEPTS, lui, est conservé : il pilote
      # l'échelle de relâchement du pré-filtre local.
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
  # ---- 2a. Source B = notre base locale (filtre plein-texte FTS) ----
  # "FTS" = full-text search = recherche plein-texte Postgres sur titre+résumé.
  # La base est un miroir ~complet de PubMed : ~25 M articles / 63 Go.
  # On cherche les articles dont le TEXTE matche les CONCEPTS de Codex, combinés
  # en ET — chaque concept étant le OU de ses synonymes :
  #     (endometriosis OU endometriotic) ET (endometrioma OU « chocolate cyst »)
  #
  # ⚠️ C'est LE point de performance. Avant, les mots-clés étaient aplatis en un
  # seul OU (« endometriosis OU cyst OU surgery OU pain ») : le coût d'une FTS est
  # dominé par le NOMBRE DE LIGNES QUI MATCHENT (le tri ts_rank doit détoaster le
  # tsvector de chacune), donc on payait le mot le plus BANAL de la liste. Mesuré
  # sur la fenêtre 2025-2026 : 268 137 lignes en 92,8 s pour le OU à plat, contre
  # 1 546 lignes en 21 ms pour le ET des mêmes concepts. Le défaut était pervers :
  # plus la question clinique était précise, plus Codex émettait de concepts, donc
  # plus le risque qu'un mot banal (« pain » seul = 103 611 articles sur 2025-2026)
  # fasse exploser le temps était grand.
  #
  # ⚠️ On n'ajoute PLUS de condition MeSH ici (avant : « OR mesh_article ∩ mesh_terms »).
  # À l'échelle de 25 M lignes, un descripteur MeSH courant (ex. « Heart Failure »)
  # matche des MILLIONS d'articles que le tri ts_rank doit tous parcourir → la MÊME
  # requête passait de 0,4 s (FTS seul) à ~206 s (FTS OR MeSH). Les keywords_en de Codex
  # sont déjà exhaustifs (synonymes cliniques + molécules) et Codex re-juge derrière,
  # donc le gain de rappel du MeSH était marginal. mesh_terms ne sert donc qu'à la
  # requête PubMed (1a/1b), PAS au vivier local.
  concepts = concepts_en de Codex                    # [[synonymes], [synonymes], …]
  SI pas de concepts MAIS des keywords_en → UN seul groupe (ancien OU à plat)
  SI ni l'un ni l'autre (Codex HS)         → on SAUTE le vivier local (B = ∅)
      # On n'envoie JAMAIS la question FRANÇAISE à un index anglais : elle n'en tire
      # quasi aucun lexème utile et B retombait à 0 sans le dire.

  # Garde-fou latence (LOCAL_SEARCH_TIMEOUT_MS = 15 s) : budget TOTAL de l'échelle
  # ci-dessous (statement_timeout Postgres, isolé dans sa propre transaction).
  # Depuis le passage au ET, une requête saine tient en 0,4 à 2 s : au-delà ce n'est
  # plus « le sujet est large » mais une anomalie → on ABANDONNE le vivier local
  # (B = ∅) et on continue sur PubMed seul, plutôt que de faire attendre le médecin.
  ESSAYER (dans le budget restant):
      B_pmids = SELECT pmid FROM articles      # ou article_search si la fenêtre le permet
                WHERE  texte matche (concept₁ ET concept₂ ET …)   # FTS (index GIN)
                  AND  pub_year ≥ année(date_from)                # filtres date
                  AND  pub_year ≤ année(date_to)
                ORDER BY pertinence_lexicale DESC                 # "ts_rank"
                LIMIT max_local                                   # ≤ 200
  SINON (budget dépassé):
      B_pmids = []                                           # repli : PubMed seul

  # ---- 2a-bis. Échelle de relâchement ----
  # Le ET de tous les concepts est rapide mais parfois trop sévère : un article
  # pertinent peut ne pas employer le vocabulaire d'UN des concepts. Si B < 30 ET
  # qu'il y a ≥ 3 concepts, on rejoue une variante par concept retiré (les autres
  # restant en ET) et on fusionne en tourniquet, le palier strict gardant la tête.
  # JAMAIS moins de 2 concepts en ET : en dessous on retombe sur les centaines de
  # milliers de lignes que tout ceci corrige.
  # Mesuré (« kystes d'endométriose », 2025-2026, 3 concepts) : 236 articles en
  # 1,9 s pour le ET strict ; 348 en 0,4 s et 1 488 en 1,3 s pour les variantes.

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
  empêche un proxy de couper pendant le silence du jugement (~50 s). Étapes émises :
  `codex` → `codex_done` → `esearch` → `esearch_done` → `filter_start` → (`filter` |
  `filter_timeout`) → `judge` → `judge_done` → `judge_detail` → `done` → `translate` →
  `translate_done`.
  `filter_start` est émis **avant** la requête locale (sinon l'UI resterait figée sur la
  ligne PubMed pendant la recherche en base) ; `filter_timeout` remplace `filter` quand
  le garde-fou 8 s se déclenche.
- **`judge_detail` — la trace auditable du tri.** Ce jalon porte, dans sa clé
  `judgements`, le verdict de **chaque abstract soumis** au juge : `pmid`, titre
  (tronqué à 160 caractères), `score`, `relevance_pct`, `reason`, `kept`. C'est la
  **seule** trace des articles ÉCARTÉS : ils ne sont ni dans `results` (filtrés par
  `min_score`) ni dans `remaining` (le vivier jamais soumis), et la sortie brute de
  codex n'est pas conservée (`run_codex` écrit dans un `TemporaryDirectory`). Sans lui,
  un « 50 jugés → 3 retenus » est inauditable. Un article soumis dont codex n'a rien
  renvoyé garde `score: null` — jamais confondu avec un rejet argumenté.
  Persisté avec les autres jalons dans `search_runs.logs` (et `digest_runs.logs`), donc
  relisible après coup ; le front l'affiche replié sous la ligne de log correspondante.
  Les lots « 50 de plus » l'émettent aussi, mais ne sont rattachés à aucun run : leur
  détail vit le temps de la page.
- **Récap des timeouts / limites, par étape** :
  | Étape | Limite | Au-delà |
  |---|---|---|
  | Construction requête (Codex) | **180 s** | repli « requête brute » (`builder=fallback`) |
  | `esearch` PubMed (source A) | dépend de NCBI | **502**, stoppe tout |
  | Requête base locale (source B) | **8 s** (`statement_timeout`) | B = ∅, repli PubMed (`filter_timeout`) |
  | `esummary`/`efetch` (résumés manquants) | best-effort | on dégrade (titre/résumé absents), pas de 500 |
  | Jugement (Codex) | **420 s** | repli `judge_mode=skipped` (pas de score, tri lexical) |
- **Tailles / seuils** : `k_pubmed`=20 (A) · `max_local`≤200 (B) · `judge_batch`=50
  (lus par lot) · `min_score`=2 (garde ≥ pertinent) · abstract **tronqué à 1200 car.**
  avant envoi au juge.
- **Infra Postgres (indispensable à l'échelle 25 M)** : base de 75 Go, index FTS de
  6,0 Go sur `articles` (1,4 Go sur `article_search`). Config custom
  (`docker-compose.yml`) : `shared_buffers`=14 Go, `work_mem`=64 Mo,
  `effective_cache_size`=24 Go, `random_page_cost`=1.1, `effective_io_concurrency`=4,
  `track_io_timing`=on, index FTS **préchauffé** (`pg_prewarm`, `autoprewarm` actif).

  ⚠️ **Le stockage est du disque mécanique** : 2× Seagate Exos 7200 tr/min en RAID1
  (`rotational=1`). Mesuré en O_DIRECT : lecture aléatoire de 8 Ko = 6,14 ms,
  séquentielle = 0,076 ms — un ratio de **81×**. C'est LA contrainte qui gouverne tout
  le reste : la seule variable qui compte est de savoir si les blocs sont en RAM.
  Même requête, même plan, selon l'état du cache : **88 718 ms** à froid,
  **11 141 ms** après `pg_prewarm` partiel, **222 ms** pleinement chaud.
  `article_search` pèse 7 704 Mo, d'où le passage de `shared_buffers` à 14 Go — à 8 Go
  elle « rentrait juste » et se faisait évincer en permanence.

  > L'ancienne valeur documentée ici, « ~13 s à froid », n'était pas fausse à
  > l'époque : elle datait d'une base plus petite. Le corpus ayant grossi, le cas
  > froid s'est dégradé jusqu'aux 88 s mesurés le 2026-08-03. Ce n'est pas une
  > correction d'erreur mais le constat d'une dérive.
- **Coût** : 2 appels Codex par recherche initiale (1 requête + 1 jugement de 50) ;
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

---

## Variante v2 : fusion RRF pour la sélection (le tri reste Codex)

⚠️ Nomenclature : la méthode ci-dessus s'appelle historiquement « v2 » dans le code
(vs l'ancienne « v1 lots d'abstracts » supprimée). Le **réglage** ci-dessous est un
mode *à l'intérieur* de cette méthode, exposé dans l'UI « TRI : v1 · score IA (défaut) /
v2 · fusion RRF ». Ne pas confondre.

**Principe (règle produit) : la pertinence affichée est TOUJOURS celle de Codex.**
PubMed Best Match ne sert jamais à classer ce que voit le médecin — seulement à
**choisir** les candidats à faire juger. Justification : ~**39 %** des articles jugés
pertinents viennent du **local seul** (mesuré sur les recherches sauvegardées) → il ne
faut pas laisser PubMed monopoliser le lot de jugement.

Activé par `rrf=True` + `k_pubmed` élevé (50). Change **seulement la sélection** :

- **`k_pubmed` 20 → 50** : head PubMed plus large.
- **Fusion RRF** (rang réciproque) du vivier au lieu de « PubMed d'abord » :
  ```
  K = 60
  pour chaque liste L dans (PubMed Best Match, local lexical) :
      pour rang, pmid dans L :  rrf[pmid] += 1 / (K + rang)
  vivier trié par rrf décroissant        # bien classé dans l'une OU l'autre → remonte
  ```
  N'utilise que les **rangs** (pas les scores → pas de problème d'échelles).
- **Plancher local** (`local_floor`, curseur) : on garantit au moins N articles
  locaux-seuls dans le lot jugé, sinon PubMed peut tout remplir.
- **Taille de lot** (`judge_batch`, curseur, 20–100) : combien Codex juge par lot.
- **Tri final : TOUJOURS Codex** (`score → % → evidence_level → année`), en v1 comme en v2.

Curseurs UI (mode v2) : « Analysés par lot » = `judge_batch`, « Minimum local garanti »
= `local_floor`. Récap de provenance affiché au-dessus des résultats (`counts.kept_pubmed`
/ `kept_local` / `kept_both`).

But : A/B tester si nourrir Codex avec un vivier **fusionné RRF** (PubMed + local) donne
de meilleurs résultats que le « PubMed d'abord + local en filet » du v1. `v1` inchangé
quand `rrf=False`.
