/* X-Med — données d'exemple (mêmes que la maquette).
   Utile pour démarrer sans brancher l'API. Remplacez par vos vraies données. */
import type { DigestData } from "./types";

export const sampleDigest: DigestData = {
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
};
