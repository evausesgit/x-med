/* X-Med — données d'exemple (mêmes que la maquette).
   Utile pour démarrer sans brancher l'API. Remplacez par vos vraies données.
   Les abstracts ci-dessous sont ILLUSTRATIFS (démo) ; en production ils viennent
   de PubMed (en) et de la traduction (fr). */
import type { DigestData } from "./types";

export const sampleDigest: DigestData = {
  date: "Jeudi 31 mai 2026",
  generated: "06:00",
  method: "aperçu de démonstration",
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
      abstract:
        "Contexte : l’aspirine à faible dose est recommandée chez les femmes à haut risque de pré-éclampsie, mais le moment optimal d’initiation et l’ampleur du bénéfice restent débattus.\nMéthodes : méta-analyse de 27 essais randomisés (n = 41 892 grossesses à haut risque) comparant l’aspirine à faible dose (75–162 mg/j) à un placebo ou à l’absence de traitement, stratifiée selon l’âge gestationnel à l’initiation.\nRésultats : l’aspirine réduit l’incidence de la pré-éclampsie (RR 0,67 ; IC 95 % 0,59–0,76). L’effet est maximal lorsque le traitement débute avant 16 semaines d’aménorrhée (RR 0,53) et s’atténue ensuite. Aucune augmentation des hémorragies maternelles, fœtales ou néonatales n’a été observée.\nConclusions : chez les femmes à haut risque, l’aspirine débutée avant 16 SA réduit la pré-éclampsie d’environ un tiers sans excès hémorragique, ce qui plaide pour un repérage du risque dès la première consultation prénatale.",
    },
    en: {
      title: "Aspirin for the prevention of pre-eclampsia in high-risk pregnancies: an updated meta-analysis",
      stand: "Low-dose aspirin started before 16 weeks reduces pre-eclampsia by roughly one third in high-risk women, with no excess bleeding.",
      abstract:
        "Background: Low-dose aspirin is recommended for women at high risk of pre-eclampsia, but the optimal timing of initiation and the magnitude of benefit remain debated.\nMethods: We pooled 27 randomized trials (n = 41,892 high-risk pregnancies) comparing low-dose aspirin (75–162 mg/day) with placebo or no treatment, stratified by gestational age at initiation.\nResults: Aspirin reduced the incidence of pre-eclampsia (RR 0.67, 95% CI 0.59–0.76). The effect was largest when treatment began before 16 weeks of gestation (RR 0.53) and attenuated thereafter. There was no increase in maternal, fetal, or neonatal bleeding.\nConclusions: In high-risk pregnancies, low-dose aspirin started before 16 weeks reduces pre-eclampsia by roughly one third without excess bleeding, supporting early risk stratification at the first antenatal visit.",
    },
    why: [
      "Méta-analyse actualisée portant sur plus de 40 000 grossesses à haut risque.",
      "Réduction relative du risque d’environ 33 % lorsque le traitement débute avant 16 SA.",
      "Aucun excès d’hémorragie maternelle ni néonatale rapporté.",
      "Plaide pour un repérage du risque dès la première consultation prénatale.",
    ],
    spoken:
      "Article du jour. L’aspirine confirme sa place dans la prévention de la pré-éclampsie. Une méta-analyse actualisée portant sur plus de quarante mille grossesses à haut risque montre qu’une aspirine à faible dose, débutée avant seize semaines, réduit le risque d’environ un tiers, sans excès hémorragique. Pour la pratique, ces résultats plaident pour un repérage du risque dès la première consultation prénatale.",
    mesh: ["Pre-Eclampsia", "Aspirin", "Pregnancy, High-Risk", "Primary Prevention", "Platelet Aggregation Inhibitors"],
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
        abstract:
          "Contexte : le choix entre prise en charge médicale et chirurgicale de l’endométriose profonde infiltrante reste discuté, faute de données comparatives à long terme.\nMéthodes : cohorte prospective de 614 femmes atteintes d’endométriose profonde, traitées médicalement (hormonothérapie) ou chirurgicalement (exérèse cœlioscopique), suivies cinq ans. Critères principaux : douleur pelvienne (EVA) et grossesse spontanée ou assistée.\nRésultats : à cinq ans, les scores de douleur et les taux cumulés de grossesse sont comparables entre les groupes ; la chirurgie apporte un soulagement initial plus rapide mais un taux de réintervention plus élevé.\nConclusions : les stratégies médicale et chirurgicale donnent des résultats comparables à cinq ans ; la décision doit être individualisée selon les symptômes, le projet de grossesse et la préférence de la patiente.",
      },
      en: {
        title: "Long-term outcomes of conservative versus surgical management of deep endometriosis",
        stand: "At five years, pain and fertility outcomes differ little between medical and surgical management — the choice stays individual.",
        abstract:
          "Background: The choice between medical and surgical management of deep infiltrating endometriosis is contentious, with limited long-term comparative data.\nMethods: Prospective cohort of 614 women with deep endometriosis managed medically (hormonal therapy) or surgically (laparoscopic excision), followed for five years. Primary endpoints were pelvic pain (VAS) and spontaneous or assisted pregnancy.\nResults: At five years, pain scores and cumulative pregnancy rates were similar between groups; surgery offered faster initial pain relief but a higher rate of reintervention.\nConclusions: Medical and surgical strategies yield comparable five-year outcomes for deep endometriosis; the decision should be individualized to symptoms, fertility goals, and patient preference.",
      },
      why: [
        "Cohorte prospective comparant prise en charge médicale et chirurgicale.",
        "Critères de jugement : douleur et fertilité à 5 ans.",
        "Différences modestes entre les deux stratégies.",
      ],
      spoken:
        "Endométriose profonde : faut-il opérer ? Une cohorte prospective à cinq ans montre que la douleur et la fertilité diffèrent peu entre la prise en charge médicale et la chirurgie. La décision reste donc individuelle, à discuter avec la patiente.",
      mesh: ["Endometriosis", "Pelvic Pain", "Fertility", "Laparoscopy", "Cohort Studies"],
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
        abstract:
          "Contexte : la couverture du dépistage du cancer du col reste insuffisante chez les femmes peu ou pas dépistées. L’auto-prélèvement HPV pourrait lever certains freins à la participation.\nMéthodes : essai randomisé pragmatique incluant 9 210 femmes en retard de dépistage, réparties entre un kit d’auto-prélèvement HPV envoyé par courrier et une invitation standard à un dépistage en cabinet.\nRésultats : la participation est nettement supérieure dans le bras auto-prélèvement (38,6 % contre 17,1 % ; RR 2,26). La détection des lésions de haut grade est au moins équivalente.\nConclusions : proposer l’auto-prélèvement HPV augmente fortement la participation des femmes sous-dépistées et constitue une option concrète pour étendre la couverture.",
      },
      en: {
        title: "HPV self-sampling to improve cervical cancer screening coverage: a randomized trial",
        stand: "Offering HPV self-sampling markedly increases participation among under-screened women.",
        abstract:
          "Background: Cervical cancer screening coverage remains suboptimal among under-screened women. HPV self-sampling may lower barriers to participation.\nMethods: Pragmatic randomized trial enrolling 9,210 women overdue for screening, allocated to a mailed HPV self-sampling kit or a standard invitation to clinic-based screening.\nResults: Participation was markedly higher in the self-sampling arm (38.6% vs 17.1%, RR 2.26). Detection of high-grade lesions was at least equivalent.\nConclusions: Offering HPV self-sampling substantially increases screening participation among under-screened women and is a practical option to extend coverage.",
      },
      why: [
        "Essai randomisé sur la couverture du dépistage.",
        "Hausse de la participation chez les femmes sous-dépistées.",
        "Option concrète pour atteindre les populations difficiles à toucher.",
      ],
      spoken:
        "Dépistage du col de l’utérus : un essai randomisé montre que proposer l’auto-prélèvement HPV augmente nettement la participation des femmes peu ou pas dépistées. C’est une option concrète pour améliorer la couverture du dépistage.",
      mesh: ["Uterine Cervical Neoplasms", "Mass Screening", "Papillomavirus Infections", "Early Detection of Cancer", "Self-Examination"],
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
        abstract:
          "Contexte : l’obésité s’accompagne d’une inflammation systémique chronique de bas grade. On ignore si les agonistes du récepteur GLP-1 réduisent l’inflammation au-delà de la perte de poids.\nMéthodes : dans l’essai randomisé en double aveugle STEP-INFLAM, 612 adultes obèses ont reçu du sémaglutide 2,4 mg une fois par semaine ou un placebo pendant 52 semaines. Critère principal : variation de la protéine C réactive ultrasensible (hs-CRP).\nRésultats : le sémaglutide abaisse la hs-CRP de 38 % versus placebo, un effet seulement en partie médié par la perte de poids à l’analyse de médiation. L’IL-6 et le fibrinogène sont également réduits.\nConclusions : le sémaglutide hebdomadaire réduit les marqueurs inflammatoires systémiques dans l’obésité, en partie indépendamment de la perte de poids.",
      },
      en: {
        title: "Semaglutide and reduction of systemic inflammatory markers in obesity (STEP-INFLAM)",
        stand: "CRP fell by 38% at one year, an effect only partly explained by weight loss.",
        abstract:
          "Background: Obesity is associated with chronic low-grade systemic inflammation. Whether GLP-1 receptor agonists reduce inflammation beyond weight loss is unclear.\nMethods: In the STEP-INFLAM randomized, double-blind trial, 612 adults with obesity received once-weekly semaglutide 2.4 mg or placebo for 52 weeks. The primary endpoint was change in high-sensitivity C-reactive protein (hs-CRP).\nResults: Semaglutide lowered hs-CRP by 38% versus placebo, an effect only partly mediated by weight loss in mediation analysis. IL-6 and fibrinogen were also reduced.\nConclusions: Once-weekly semaglutide reduces systemic inflammatory markers in obesity, in part independently of weight loss.",
      },
      why: [
        "Essai randomisé contre placebo, 52 semaines.",
        "Baisse de la CRP de 38 %, IL-6 et fibrinogène également réduits.",
        "Effet en partie indépendant de la perte de poids.",
      ],
      spoken:
        "Sémaglutide et inflammation. Dans l’essai randomisé STEP-INFLAM, le sémaglutide a réduit la protéine C réactive de trente-huit pour cent à un an, un effet seulement en partie expliqué par la perte de poids. L’interleukine 6 et le fibrinogène diminuent également.",
      mesh: ["Semaglutide", "Inflammation", "C-Reactive Protein", "Obesity", "Randomized Controlled Trial"],
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
        abstract:
          "Contexte : l’inflammation entretient la progression des lésions d’endométriose. Les agonistes du récepteur GLP-1 ont des effets anti-inflammatoires dans d’autres tissus.\nMéthodes : des cellules stromales endométriosiques issues de pièces opératoires ont été traitées par des agonistes du récepteur GLP-1 à différentes doses ; la sécrétion de cytokines et l’activation de NF-κB ont été quantifiées.\nRésultats : le traitement réduit significativement la sécrétion d’IL-6, d’IL-8 et de TNF-α de façon dose-dépendante, avec inhibition de l’activation de NF-κB.\nConclusions : les agonistes du récepteur GLP-1 exercent une action anti-inflammatoire directe sur les cellules stromales endométriosiques, au-delà de leurs effets métaboliques, ce qui justifie de poursuivre l’étude dans l’endométriose.",
      },
      en: {
        title: "GLP-1 receptor agonists attenuate pro-inflammatory cytokine secretion in endometriotic stromal cells",
        stand: "A direct anti-inflammatory action on stromal cells, beyond the metabolic effect.",
        abstract:
          "Background: Inflammation drives the progression of endometriotic lesions. GLP-1 receptor agonists have anti-inflammatory effects in other tissues.\nMethods: Endometriotic stromal cells isolated from surgical specimens were treated with GLP-1 receptor agonists across a range of doses; cytokine secretion and NF-κB activation were quantified.\nResults: Treatment significantly reduced IL-6, IL-8 and TNF-α secretion in a dose-dependent manner, with suppression of NF-κB activation.\nConclusions: GLP-1 receptor agonists exert a direct anti-inflammatory action on endometriotic stromal cells, beyond their metabolic effects, supporting further study in endometriosis.",
      },
      why: [
        "Modèle cellulaire : cellules stromales endométriosiques.",
        "Baisse d’IL-6, IL-8 et TNF-α, inhibition de NF-κB.",
        "Rationnel pour explorer le GLP-1 dans l’endométriose.",
      ],
      spoken:
        "Les agonistes du GLP-1 freinent l’inflammation des lésions d’endométriose. Sur cellules stromales, le traitement réduit la sécrétion d’interleukine 6, d’interleukine 8 et de TNF alpha, avec une inhibition de la voie NF kappa B. Cela suggère une action anti-inflammatoire directe, au-delà de l’effet métabolique.",
      mesh: ["Endometriosis", "Glucagon-Like Peptide-1 Receptor", "Inflammation", "Cytokines", "NF-kappa B", "Stromal Cells"],
    },
  ],
};
