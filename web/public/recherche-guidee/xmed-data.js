/* X-Med — données de démonstration (réalistes, à but pédagogique).
   Requête vedette du médecin :
   « impact des anti GLP-1 sur la diminution de l'inflammation
     dans la prise en charge de l'endométriose »
   Les articles sont en anglais (corpus PubMed/MEDLINE), la requête en français :
   c'est tout l'intérêt de la recherche « par sens » (pont FR -> EN). */

window.XMED = {
  query: "impact des anti GLP-1 sur la diminution de l'inflammation dans la prise en charge de l'endométriose",

  // Résultats du mode « Par sens (sémantique) », triés par score de fusion (RRF).
  // score = score brut renvoyé par l'API (plafonne vers ~0,03, NON un %).
  semantic: [
    {
      pmid: 39812044,
      title: "Glucagon-like peptide-1 receptor agonists attenuate pro-inflammatory cytokine secretion in endometriotic stromal cells",
      journal: "Human Reproduction",
      pub_year: 2025,
      evidence_level: 2,
      score: 0.0312,
      abstract: "Treatment with GLP-1 receptor agonists significantly reduced IL-6, IL-8 and TNF-α secretion in cultured endometriotic stromal cells, with a dose-dependent suppression of NF-κB activation. The findings suggest a direct anti-inflammatory action of GLP-1 signalling within ectopic endometrial lesions, beyond its metabolic effects.",
      mesh_terms: ["Endometriosis", "Glucagon-Like Peptide-1 Receptor", "Inflammation", "Cytokines", "NF-kappa B", "Stromal Cells"],
      term: "GLP-1 receptor agonist endometriosis inflammation cytokine",
    },
    {
      pmid: 38744120,
      title: "Anti-inflammatory mechanisms of GLP-1 analogues: from metabolic disease to immune modulation",
      journal: "Frontiers in Endocrinology",
      pub_year: 2024,
      evidence_level: 4,
      score: 0.0241,
      abstract: "This narrative review summarizes converging evidence that GLP-1 receptor agonists attenuate macrophage activation, dampen NF-κB and inflammasome signalling, and lower circulating inflammatory markers across cardiometabolic and reproductive tissues, supporting repurposing hypotheses in chronic inflammatory disease.",
      mesh_terms: ["Glucagon-Like Peptide 1", "Inflammation", "Macrophages", "Anti-Inflammatory Agents", "Immunomodulation"],
      term: "GLP-1 analogue anti-inflammatory mechanism immune",
    },
    {
      pmid: 39056781,
      title: "Semaglutide and reduction of systemic inflammatory markers in obesity: the STEP-INFLAM randomized controlled trial",
      journal: "Lancet Diabetes & Endocrinology",
      pub_year: 2025,
      evidence_level: 1,
      score: 0.0207,
      abstract: "In 612 adults with obesity, once-weekly semaglutide lowered high-sensitivity C-reactive protein by 38% versus placebo over 52 weeks, an effect only partly explained by weight loss. Secondary endpoints showed reductions in IL-6 and fibrinogen.",
      mesh_terms: ["Semaglutide", "Inflammation", "C-Reactive Protein", "Obesity", "Randomized Controlled Trial"],
      term: "semaglutide systemic inflammation C-reactive protein randomized",
    },
    {
      pmid: 37690233,
      title: "Peritoneal macrophage polarization drives the inflammatory progression of endometriosis",
      journal: "Reproductive Sciences",
      pub_year: 2023,
      evidence_level: 2,
      score: 0.0169,
      abstract: "M1-polarized peritoneal macrophage infiltration correlated with lesion severity and peritoneal IL-1β concentration in women with deep infiltrating endometriosis, identifying the macrophage compartment as a candidate target for anti-inflammatory therapy.",
      mesh_terms: ["Endometriosis", "Macrophages", "Inflammation", "Peritoneum", "Interleukin-1beta"],
      term: "peritoneal macrophage endometriosis inflammation",
    },
    {
      pmid: 38211907,
      title: "Expression of the GLP-1 receptor in human peritoneal tissue and resident immune cells",
      journal: "Molecular Human Reproduction",
      pub_year: 2024,
      evidence_level: 3,
      score: 0.0142,
      abstract: "Immunohistochemistry and single-cell RNA sequencing demonstrated GLP-1 receptor expression in peritoneal mesothelial cells and a subset of resident macrophages, providing a biological rationale for local effects of GLP-1 receptor agonists in the pelvic cavity.",
      mesh_terms: ["Glucagon-Like Peptide-1 Receptor", "Peritoneum", "Macrophages", "Gene Expression"],
      term: "GLP-1 receptor expression peritoneal immune cells",
    },
    {
      pmid: 36558410,
      title: "Metabolic profile and low-grade inflammation in women with endometriosis: a case-control study",
      journal: "Fertility and Sterility",
      pub_year: 2022,
      evidence_level: 2,
      score: 0.0118,
      abstract: "Women with endometriosis showed higher hs-CRP and altered adipokine profiles than matched controls, supporting a systemic low-grade inflammatory component to the disease that may be amenable to metabolic intervention.",
      mesh_terms: ["Endometriosis", "Inflammation", "C-Reactive Protein", "Metabolic Syndrome", "Case-Control Studies"],
      term: "metabolic inflammation endometriosis case-control",
    },
  ],

  // Résultats du mode « Mots-clés / MeSH » : tags Endometriosis + Inflammation,
  // niveau de preuve <= 2, triés par date. (total simulé pour la pagination)
  keyword: {
    total: 47,
    mesh: ["Endometriosis", "Inflammation"],
    results: [
      {
        pmid: 39812044,
        title: "Glucagon-like peptide-1 receptor agonists attenuate pro-inflammatory cytokine secretion in endometriotic stromal cells",
        journal: "Human Reproduction",
        pub_year: 2025,
        evidence_level: 2,
        score: null,
        abstract: "Treatment with GLP-1 receptor agonists significantly reduced IL-6, IL-8 and TNF-α secretion in cultured endometriotic stromal cells, with a dose-dependent suppression of NF-κB activation.",
        mesh_terms: ["Endometriosis", "Glucagon-Like Peptide-1 Receptor", "Inflammation", "Cytokines"],
        term: "GLP-1 endometriosis inflammation",
      },
      {
        pmid: 37690233,
        title: "Peritoneal macrophage polarization drives the inflammatory progression of endometriosis",
        journal: "Reproductive Sciences",
        pub_year: 2023,
        evidence_level: 2,
        score: null,
        abstract: "M1-polarized peritoneal macrophage infiltration correlated with lesion severity and peritoneal IL-1β concentration in women with deep infiltrating endometriosis.",
        mesh_terms: ["Endometriosis", "Macrophages", "Inflammation", "Peritoneum"],
        term: "peritoneal macrophage endometriosis inflammation",
      },
      {
        pmid: 36558410,
        title: "Metabolic profile and low-grade inflammation in women with endometriosis: a case-control study",
        journal: "Fertility and Sterility",
        pub_year: 2022,
        evidence_level: 2,
        score: null,
        abstract: "Women with endometriosis showed higher hs-CRP and altered adipokine profiles than matched controls, supporting a systemic low-grade inflammatory component to the disease.",
        mesh_terms: ["Endometriosis", "Inflammation", "C-Reactive Protein", "Metabolic Syndrome"],
        term: "metabolic inflammation endometriosis",
      },
      {
        pmid: 35221764,
        title: "NF-κB signalling pathway in the pathophysiology of endometriosis-associated pain",
        journal: "Human Reproduction Update",
        pub_year: 2022,
        evidence_level: 1,
        score: null,
        abstract: "A systematic review of inflammatory signalling in endometriosis lesions, focusing on NF-κB-driven cytokine cascades and their relationship to chronic pelvic pain.",
        mesh_terms: ["Endometriosis", "NF-kappa B", "Inflammation", "Pelvic Pain", "Signal Transduction"],
        term: "NF-kB endometriosis inflammation pain",
      },
    ],
  },

  // Tags MeSH proposés par l'autocomplétion (mode mots-clés).
  meshSuggest: {
    "endo": ["Endometriosis", "Endometrium", "Endothelium, Vascular", "Endocarditis"],
    "infla": ["Inflammation", "Inflammatory Bowel Diseases", "Inflammation Mediators", "Anti-Inflammatory Agents"],
    "glp": ["Glucagon-Like Peptide 1", "Glucagon-Like Peptide-1 Receptor", "Glucagon-Like Peptides"],
    "diab": ["Diabetes Mellitus", "Diabetes Mellitus, Type 2", "Diabetes, Gestational", "Diabetic Retinopathy"],
    "cyto": ["Cytokines", "Cytotoxicity, Immunologic", "Cytochrome P-450"],
  },

  // Profil médecin (contexte « bigger picture »).
  doctor: {
    name: "Dr Lefèvre",
    specialty: "Gynécologie médicale",
    interests: ["Endométriose", "Douleur pelvienne chronique", "Médecine de la reproduction", "Inflammation", "GLP-1"],
  },

  // Aperçu du digest quotidien (rendu « magazine », même modèle que la page /digest).
  // Format DigestData (voir web/app/digest/types.ts) : lead + articles, FR/EN, why[], spoken.
  digest: {
    date: "Jeudi 31 mai 2026",
    generated: "06:00",
    model: "bge-m3",
    doctor: { name: "Dr Lefèvre", specialty: "Gynécologie médicale" },
    themes: ["Endométriose", "Douleur pelvienne", "Reproduction", "Inflammation", "Dépistage"],

    lead: {
      id: "aspirin",
      journal: "Am. J. Obstet. Gynecol.",
      year: 2026,
      level: 1,
      match: 94,
      read: "4 min",
      fr: {
        title: "L’aspirine confirme sa place dans la prévention de la pré-éclampsie",
        stand: "Débutée avant 16 semaines, l’aspirine à faible dose réduit d’environ un tiers le risque de pré-éclampsie chez les femmes à haut risque — sans excès hémorragique.",
      },
      en: {
        title: "Aspirin for the prevention of pre-eclampsia in high-risk pregnancies: an updated meta-analysis",
        stand: "Low-dose aspirin started before 16 weeks reduces pre-eclampsia by roughly one third in high-risk women, with no excess bleeding.",
      },
      why: [
        "Méta-analyse actualisée portant sur plus de 40 000 grossesses à haut risque.",
        "Réduction relative du risque d’environ 33 % lorsque le traitement débute avant 16 SA.",
        "Aucun excès d’hémorragie maternelle ni néonatale rapporté.",
        "Plaide pour un repérage du risque dès la première consultation prénatale.",
      ],
      spoken:
        "Article du jour. L’aspirine confirme sa place dans la prévention de la pré-éclampsie. Une méta-analyse actualisée portant sur plus de quarante mille grossesses à haut risque montre qu’une aspirine à faible dose, débutée avant seize semaines, réduit le risque d’environ un tiers, sans excès hémorragique. Pour la pratique, ces résultats plaident pour un repérage du risque dès la première consultation prénatale.",
    },

    articles: [
      {
        id: "endo",
        journal: "Human Reproduction",
        year: 2026,
        level: 2,
        match: 88,
        read: "6 min",
        fr: {
          title: "Endométriose profonde : faut-il opérer ? Une cohorte à 5 ans relance le débat",
          stand: "À cinq ans, douleur et fertilité diffèrent peu entre prise en charge médicale et chirurgicale — la décision reste individuelle.",
        },
        en: {
          title: "Long-term outcomes of conservative versus surgical management of deep endometriosis",
          stand: "At five years, pain and fertility outcomes differ little between medical and surgical management — the choice stays individual.",
        },
        why: [
          "Cohorte prospective comparant prise en charge médicale et chirurgicale.",
          "Critères de jugement : douleur et fertilité à 5 ans.",
          "Différences modestes entre les deux stratégies.",
        ],
        spoken:
          "Endométriose profonde : faut-il opérer ? Une cohorte prospective à cinq ans montre que la douleur et la fertilité diffèrent peu entre la prise en charge médicale et la chirurgie. La décision reste donc individuelle, à discuter avec la patiente.",
      },
      {
        id: "hpv",
        journal: "The Lancet",
        year: 2026,
        level: 1,
        match: 81,
        read: "3 min",
        fr: {
          title: "Dépistage du col : l’auto-prélèvement HPV élargit la couverture",
          stand: "Proposer l’auto-prélèvement augmente nettement la participation des femmes peu ou pas dépistées.",
        },
        en: {
          title: "HPV self-sampling to improve cervical cancer screening coverage: a randomized trial",
          stand: "Offering HPV self-sampling markedly increases participation among under-screened women.",
        },
        why: [
          "Essai randomisé sur la couverture du dépistage.",
          "Hausse de la participation chez les femmes sous-dépistées.",
          "Option concrète pour atteindre les populations difficiles à toucher.",
        ],
        spoken:
          "Dépistage du col de l’utérus : un essai randomisé montre que proposer l’auto-prélèvement HPV augmente nettement la participation des femmes peu ou pas dépistées. C’est une option concrète pour améliorer la couverture du dépistage.",
      },
      {
        id: "sema",
        journal: "Lancet Diabetes Endocrinol.",
        year: 2025,
        level: 1,
        match: 76,
        read: "5 min",
        fr: {
          title: "Sémaglutide : une baisse de l’inflammation au-delà de la perte de poids",
          stand: "La CRP chute de 38 % à un an, un effet en partie indépendant du poids perdu.",
        },
        en: {
          title: "Semaglutide and reduction of systemic inflammatory markers in obesity (STEP-INFLAM)",
          stand: "CRP fell by 38% at one year, an effect only partly explained by weight loss.",
        },
        why: [
          "Essai randomisé contre placebo, 52 semaines.",
          "Baisse de la CRP de 38 %, IL-6 et fibrinogène également réduits.",
          "Effet en partie indépendant de la perte de poids.",
        ],
        spoken:
          "Sémaglutide et inflammation. Dans l’essai randomisé STEP-INFLAM, le sémaglutide a réduit la protéine C réactive de trente-huit pour cent à un an, un effet seulement en partie expliqué par la perte de poids. L’interleukine 6 et le fibrinogène diminuent également.",
      },
      {
        id: "glp1",
        journal: "Human Reproduction",
        year: 2025,
        level: 2,
        match: 72,
        read: "4 min",
        fr: {
          title: "Les agonistes GLP-1 freinent l’inflammation des lésions d’endométriose",
          stand: "Une action anti-inflammatoire directe sur les cellules stromales, au-delà de l’effet métabolique.",
        },
        en: {
          title: "GLP-1 receptor agonists attenuate pro-inflammatory cytokine secretion in endometriotic stromal cells",
          stand: "A direct anti-inflammatory action on stromal cells, beyond the metabolic effect.",
        },
        why: [
          "Modèle cellulaire : cellules stromales endométriosiques.",
          "Baisse d’IL-6, IL-8 et TNF-α, inhibition de NF-κB.",
          "Rationnel pour explorer le GLP-1 dans l’endométriose.",
        ],
        spoken:
          "Les agonistes du GLP-1 freinent l’inflammation des lésions d’endométriose. Sur cellules stromales, le traitement réduit la sécrétion d’interleukine 6, d’interleukine 8 et de TNF alpha, avec une inhibition de la voie NF kappa B. Cela suggère une action anti-inflammatoire directe, au-delà de l’effet métabolique.",
      },
    ],
  },
};
