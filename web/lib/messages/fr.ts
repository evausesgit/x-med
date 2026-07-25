// Catalogue de messages FRANÇAIS. Le typage `Messages` (défini par en.ts) rend
// toute clé manquante ou en trop une erreur de compilation : les deux langues
// ne peuvent pas diverger silencieusement.
//
// Les textes reprennent mot pour mot la copie française d'origine du produit —
// c'est la traduction anglaise qui est nouvelle, pas l'inverse.

import type { Messages } from "./en";

export const fr: Messages = {
  nav: {
    home: "X-Med — accueil",
    search: "Recherche",
    digest: "Mon Digest",
    more: "Plus de pages",
    saved: "Sauvegardées",
    profiles: "Profils",
    annotate: "Annoter",
    evaluation: "Évaluation",
    vectorization: "Vectorisation",
    howItWorks: "Comment ça marche",
    guidedTour: "Visite guidée",
    internalTag: "interne",
    signOut: "Se déconnecter",
    language: "Langue de l’interface",
    switchToFrench: "Passer en français",
    switchToEnglish: "Switch to English",
  },

  common: {
    loading: "Chargement…",
    error: "Erreur",
    apiError: "Erreur API ({status})",
    usageLimit: "Limite d'usage GPT-5.6 atteinte — réessayez plus tard.",
    working: "…",
  },

  lang: {
    groupLabel: "Langue d'affichage",
    french: "Français",
    english: "English",
    translating: "Traduction…",
    translationFailed: "Échec de la traduction.",
    translatedLabel: "Résumé (traduit en {language})",
    languageName: { en: "anglais", fr: "français" },
  },

  search: {
    hero: "Que recherchez-vous aujourd’hui, Docteur ?",
    placeholder: "Décrivez votre question clinique en français…",
    explore: "Explorer →",
    stop: "⏹ Arrêter",
    stopping: "⏹ Arrêt…",
    stopped: "⏹ Arrêté",
    stopTitle:
      "Arrêter la recherche en cours (pour corriger ou changer votre question)",
    sortLabel: "TRI",
    sortTitle:
      "v1 = tri par score IA · v2 = tri par pertinence PubMed (Best Match) + vivier PubMed élargi",
    sortV1: "v1 · score IA",
    sortV2: "v2 · fusion RRF",
    judgeBatch: "Analysés par lot :",
    localFloor: "Minimum local garanti :",
    slidersHint:
      "RRF choisit les candidats · le tri reste par score Codex · appliqué à la prochaine recherche",
    method:
      "L’IA construit une requête experte, on pré-filtre la base en local (mots-clés + MeSH), puis GPT-5.6 lit et juge uniquement ces candidats — rapide, insensible à la largeur de la période.",
    recent: "RÉCENTES",
    recentTitle: "{query} · {date} · {count} article(s) retenu(s)",
    copyLink: "Copier le lien",
    linkCopied: "Lien copié",
    liveTitle: "Déroulé de la recherche",
    liveLive: " — en direct · {elapsed}",
    livePubmed: "Pré-filtre local puis jugement par codex",
    liveOther: "Recherche en cours",
    stopLocal: "⏹ Arrêter la recherche locale (continuer avec PubMed seul)",
    stoppingLocal: "Arrêt de la recherche locale…",
    waitShort:
      "⏳ Une recherche prend en général {typical}. Elle continue en arrière-plan — vous pouvez quitter la page ou verrouiller votre téléphone, le résultat vous attendra ici.",
    waitMedium:
      "⏳ Un peu plus long que d'habitude (sujet large) — l'IA lit et juge les articles, on continue.",
    waitLong:
      "⏳ Recherche longue : on patiente encore un peu, elle s'arrêtera d'elle-même si elle dépasse quelques minutes.",
    typicalDuration: "30 à 90 secondes",
    stoppedNotice:
      "⏹️ Recherche arrêtée — corrigez votre question et relancez quand vous voulez.",
    trackFailed:
      "Impossible de suivre la recherche en cours — rechargez la page pour la retrouver.",
    runFailed: "La recherche a échoué. Réessayez plus tard.",
    reopenFailed: "Impossible de rouvrir cette recherche — rechargez la page.",
    moreFailed: "L'analyse du lot suivant a échoué.",
    codexLimitTitle: "Limite d’usage GPT-5.6 atteinte.",
    codexLimitBefore:
      "Les recherches « PubMed + codex » reposent sur GPT-5.6 (construction de la requête, tri et traduction) : le quota est épuisé pour le moment. Les résultats sont en",
    codexLimitDegraded: "mode dégradé",
    codexLimitAfter:
      "(sans tri intelligent ni traduction). Réessayez un peu plus tard.",
    countsSummary: "{kept} retenu(s) · {judged} jugés codex · {merged} fusionnés",
    countsPubmed: "{count} PubMed",
    countsLocal: "{count} local",
    countsBoth: "{count} les deux",
    alreadySaved:
      "💾 Résultat déjà sauvegardé le {date} — affiché sans relancer codex.",
    rerunAnyway: "Relancer quand même",
    saveProfile: "Profil",
    saveNoProfile: "— Aucun profil —",
    saveButton: "💾 Sauvegarder cette recherche",
    saveDone: "✓ Sauvegardée —",
    saveSeeAll: "voir mes recherches",
    saveFailed: "Échec de la sauvegarde",
    generatedQuery: "Requête PubMed générée + mots-clés",
    judgeSkipped:
      "⚠ codex indisponible : tri lexical de repli (pas de jugement de pertinence).",
    noResults: "Aucun article jugé pertinent pour cette recherche.",
    analyseMore: "Analyser {count} de plus",
    analysing: "Analyse en cours…",
    remaining: "{count} abstract(s) pré-filtré(s) restant(s) à juger.",
    disclaimer:
      "Pertinence jugée par l’IA à partir des abstracts PubMed — un appui à la lecture, pas une validation clinique.",
    sourceBoth: "A · PubMed + B · local",
    sourcePubmed: "A · PubMed",
    sourceLocal: "B · local",
    revealLabel: "Résumé structuré",
  },

  result: {
    evidence1: "Niv. 1 · preuve élevée",
    evidence2: "Niv. 2 · modérée",
    evidence3: "Niv. 3 · cas",
    evidence4: "Niv. 4 · avis",
    tierHigh: "Très pertinent",
    tierMid: "Pertinent",
    tierLow: "Partiel",
    tierRelated: "Lié",
    relevanceTitle: "Pertinence {pct} % · score codex {score}/3.",
    relevanceTitleShort: "Score codex : {score} / 3 (grille 0–3).",
    ringCaption: "Pertinence pour votre question",
    ringCaptionProfile: "Pertinence pour votre profil",
    relevanceProfileTitle: "Pertinence pour votre profil : {pct} %",
    ringUnit: "% match",
    featured: "★ Le plus pertinent",
    unknownJournal: "Journal inconnu",
    contributionLabel: "Apport",
    hideSummary: "Masquer le résumé",
    defaultRevealLabel: "Résumé & abstract",
    readOnPubmed: "Lire sur PubMed",
    listen: "Écouter",
    stopListening: "Arrêter",
    readTime: "{time} de lecture",
    source: "Source : {title}",
    aiSummary: "Résumé IA",
    toVerify: "à vérifier",
  },

  critique: {
    selectLimit: "Limite de {max} articles atteinte",
    selectRemove: "Retirer de la sélection",
    selectAdd: "Ajouter à l'analyse critique",
    selected: "Sélectionné",
    compare: "Comparer",
    selectedCount: {
      one: "{count} / {max} sélectionné pour l’analyse",
      other: "{count} / {max} sélectionnés pour l’analyse",
    },
    runTitleTooFew: "Sélectionnez au moins 2 articles",
    runTitle: "Lancer l'analyse critique comparative",
    run: "🔬 Analyser la sélection",
    clear: "Effacer",
    liveTitle: "Analyse critique — en direct",
    liveEmpty: "Analyse en cours…",
    liveReading: "Lecture des abstracts par codex…",
    failed: "L'analyse critique a échoué.",
    demoUnavailable:
      "L'analyse critique compare de vrais articles PubMed. Disponible dès que votre digest sera généré — l'aperçu de démonstration ne contient pas d'articles réels.",
    title: "Analyse critique comparative",
    subtitle:
      "Lecture critique générée par l’IA à partir des résumés PubMed — un appui à la lecture, pas une validation clinique. Les mentions « Non précisé dans le résumé » signalent une information absente de l’abstract.",
    axisHeader: "Critère",
    columnNo: "Article {n}",
    axisStudyType: "Type d'étude / niveau de preuve",
    axisPopulation: "Population (n + profil)",
    axisPrimaryOutcome: "Critère de jugement principal",
    axisEffectSize: "Taille d'effet",
    axisLimits: "Limites",
    concordance: "Concordance entre les articles",
    synthesis: "À retenir en pratique",
  },

  login: {
    tagline: "Explorez la recherche médicale",
    checking: "Vérification de la session…",
    intro:
      "Connectez-vous pour accéder à la recherche, à vos profils et à votre digest personnalisé.",
    button: "Continuer avec Google",
    busy: "Connexion…",
    deniedIntro:
      "Le compte {email} n’a pas accès à X-Med. Contactez l’équipe pour être ajouté, ou connectez-vous avec un autre compte.",
    switchAccount: "Changer de compte",
    footer: "Accès protégé — vos recherches et votre profil restent privés.",
    errNetwork:
      "Connexion impossible : vérifiez votre accès réseau puis réessayez.",
    errUnauthorizedDomain:
      "Ce domaine n'est pas autorisé dans la configuration Firebase du projet.",
    errOperationNotAllowed:
      "La connexion Google n'est pas activée sur le projet Firebase.",
    errGeneric: "La connexion a échoué. Réessayez, ou contactez l'équipe X-Med.",
  },

  profile: {
    title: "Mon profil",
    tagline: "Ce que vous recevez dans le digest, et pourquoi",
    subtitle:
      "Votre profil est lié à votre compte Google. Il décrit votre pratique (spécialité, pathologies, tags MeSH…) et pilote la sélection des articles de votre digest.",
    loadFailed: "Impossible de charger le profil : {error}",
    specialty: "Spécialité principale",
    subspecialties: "Sous-spécialités",
    pathologies: "Pathologies",
    treatments: "Traitements",
    meshTerms: "Tags MeSH (anglais)",
    keywords: "Mots-clés",
    journals: "Revues préférées",
    minEvidence: "Niveau de preuve min.",
    evidenceAll: "Tous",
    evidence1: "1 — élevé",
    evidence2: "≤ 2",
    evidence3: "≤ 3",
    evidence4: "≤ 4",
    commaSeparated: "séparés par des virgules",
    save: "Enregistrer",
    saved: "Profil mis à jour ✓",
    languageSection: "Langue",
    languageHelp:
      "Langue de l'interface et des traductions automatiques des articles. Vous pouvez toujours traduire un article à la demande depuis n'importe quelle carte de résultat.",
  },

  saved: {
    title: "Recherches sauvegardées",
    tagline: "Vos résultats, à relire et réutiliser",
    subtitle:
      "Chaque recherche est enregistrée telle quelle (requête + articles retenus). La rouvrir n’appelle pas l’IA à nouveau. Pour l’instant, toutes les recherches sont visibles de tous — le bouton « 🔗 Partager » copie un lien direct vers les résultats.",
    empty:
      "Aucune recherche sauvegardée pour l’instant. Lancez une recherche « PubMed + Filtre lexical + Codex » puis cliquez sur « 💾 Sauvegarder cette recherche ».",
    count: {
      one: "{count} recherche sauvegardée",
      other: "{count} recherches sauvegardées",
    },
    noProfile: "Sans profil",
    articles: { one: "{count} article", other: "{count} articles" },
    hide: "Masquer",
    reopen: "Rouvrir / relire",
    delete: "Supprimer",
    confirmDelete: "Supprimer cette recherche sauvegardée ?",
    loadingResults: "Chargement des résultats…",
    share: "🔗 Partager",
    shared: "✅ Lien copié",
    sharePrompt: "Copiez ce lien pour le partager :",
    backToAll: "← Toutes les recherches sauvegardées",
    notFound:
      "Cette recherche sauvegardée est introuvable. Le lien est peut-être erroné ou la recherche a été supprimée.",
    emptyPayload: "Aucun article dans cette recherche sauvegardée.",
  },

  digest: {
    periodLabel: "PÉRIODE",
    lastDays: "{count} derniers jours",
    generate: "✨ Générer mon digest",
    generateTitle: "Lancer la sélection d'articles pour votre profil",
    generateNoProfile: "Créez d'abord votre profil",
    stop: "⏹ Arrêter",
    historyLabel: "HISTORIQUE",
    historyTitle: "{date} · {count} articles · {days} derniers jours",
    runningTitle:
      "Génération du digest — en arrière-plan (vous pouvez quitter la page, elle continuera)",
    runningFirstLine: "Composition de la recherche à partir de votre profil…",
    meError:
      "Impossible de charger votre profil — reconnectez-vous puis rechargez la page.",
    noProfile: "Votre digest se personnalise à partir de votre profil.",
    createProfile: "Créer mon profil →",
    loadRunFailed: "Impossible de charger ce digest — rechargez la page.",
    genFailed: "La génération du digest a échoué. Réessayez plus tard.",
    emptyResult:
      "Aucun article retenu sur les {days} derniers jours pour votre profil.",
    widen: "Élargir à 90 jours",
    inProgress: "en cours",
    demoTitle: "🧪 Ceci est un aperçu de démonstration",
    demoBody:
      "Tout ce qui s’affiche ci-dessous est un exemple fictif — profil « Dr Lefèvre » et articles inventés. Cliquez sur « ✨ Générer mon digest » pour obtenir une vraie sélection PubMed adaptée à votre profil.",
    kicker: "Mon Digest · {date}",
    headTitle: "Votre veille du jour",
    headSub: "{count} articles choisis pour votre profil — {name}, {specialty}.",
    generatedAt: "Généré {time} CET",
    method: "PubMed + GPT-5.6 · {days} derniers jours",
    themesLabel: "VOS THÈMES",
    adjustThemes: "ajuster mes thèmes →",
    disclaimer:
      "Sélection établie pour votre profil — un appui à la veille, pas une validation clinique.",
    unknownJournal: "Journal non renseigné",
    unknownSpecialty: "Spécialité non renseignée",
  },

  meta: {
    title: "X-Med — Explorez la recherche médicale",
    description:
      "Recherche d'articles médicaux par tags MeSH ou par phrase libre",
    howItWorksTitle: "X-Med — Comment ça marche",
    howItWorksDescription:
      "La recherche PubMed + IA expliquée en technique : pipeline, v1 vs v2, tailles de lots, timeouts et contraintes.",
  },
};
