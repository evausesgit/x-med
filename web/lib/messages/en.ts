// Catalogue de messages ANGLAIS — langue principale du produit et référence du
// catalogue : c'est ce fichier qui définit la FORME (`Messages`) que toutes les
// autres langues doivent respecter. Ajouter une clé ici et oublier de la
// traduire ailleurs devient une erreur TypeScript (voir messages/fr.ts).
//
// Les valeurs peuvent contenir des variables `{nom}` (voir `t()` dans lib/i18n)
// et, pour les libellés qui varient au pluriel, prendre la forme
// `{ one: "…", other: "…" }` (voir `tp()`).

export const en = {
  nav: {
    home: "X-Med — home",
    search: "Search",
    digest: "My Digest",
    more: "More pages",
    saved: "Saved",
    profiles: "Profiles",
    annotate: "Annotate",
    evaluation: "Evaluation",
    vectorization: "Vectorization",
    howItWorks: "How it works",
    guidedTour: "Guided tour",
    internalTag: "internal",
    signOut: "Sign out",
    language: "Interface language",
    switchToFrench: "Passer en français",
    switchToEnglish: "Switch to English",
  },

  common: {
    loading: "Loading…",
    error: "Error",
    apiError: "API error ({status})",
    usageLimit: "GPT-5.6 usage limit reached — please try again later.",
    working: "…",
  },

  lang: {
    groupLabel: "Display language",
    french: "French",
    english: "English",
    translating: "Translating…",
    translationFailed: "Translation failed.",
    translatedLabel: "Summary (translated into {language})",
    languageName: { en: "English", fr: "French" },
  },

  search: {
    hero: "What are you looking for today, Doctor?",
    placeholder: "Describe your clinical question…",
    explore: "Explore →",
    stop: "⏹ Stop",
    stopping: "⏹ Stopping…",
    stopped: "⏹ Stopped",
    stopTitle: "Stop the running search (to fix or change your question)",
    sortLabel: "SORT",
    sortTitle:
      "v1 = sorted by AI score · v2 = sorted by PubMed relevance (Best Match) + wider PubMed pool",
    sortV1: "v1 · AI score",
    sortV2: "v2 · RRF fusion",
    judgeBatch: "Judged per batch:",
    localFloor: "Guaranteed local minimum:",
    slidersHint:
      "RRF picks the candidates · sorting still follows the Codex score · applied to the next search",
    method:
      "The AI builds an expert query, we pre-filter our database locally (keywords + MeSH), then GPT-5.6 reads and judges only those candidates — fast, and unaffected by how wide the date range is.",
    recent: "RECENT",
    recentTitle: "{query} · {date} · {count} article(s) kept",
    copyLink: "Copy link",
    linkCopied: "Link copied",
    liveTitle: "Search progress",
    liveLive: " — live · {elapsed}",
    livePubmed: "Local pre-filter, then judged by codex",
    liveOther: "Search running",
    stopLocal: "⏹ Stop the local search (continue with PubMed only)",
    stoppingLocal: "Stopping the local search…",
    waitShort:
      "⏳ A search usually takes {typical}. It keeps running in the background — you can leave the page or lock your phone, the result will be waiting here.",
    waitMedium:
      "⏳ Taking a little longer than usual (broad topic) — the AI is reading and judging the articles, hang tight.",
    waitLong:
      "⏳ Long search: a bit more patience — it will stop by itself if it runs past a few minutes.",
    typicalDuration: "30 to 90 seconds",
    stoppedNotice:
      "⏹️ Search stopped — fix your question and start again whenever you like.",
    trackFailed:
      "Cannot track the running search — reload the page to find it again.",
    runFailed: "The search failed. Please try again later.",
    reopenFailed: "Cannot reopen this search — please reload the page.",
    moreFailed: "Analysing the next batch failed.",
    codexLimitTitle: "GPT-5.6 usage limit reached.",
    codexLimitBefore:
      "“PubMed + codex” searches rely on GPT-5.6 (query building, ranking and translation): the quota is exhausted for now. Results are shown in",
    codexLimitDegraded: "degraded mode",
    codexLimitAfter:
      "(no smart ranking, no translation). Please try again a little later.",
    countsSummary:
      "{kept} kept · {judged} judged by codex · {merged} merged",
    countsPubmed: "{count} PubMed",
    countsLocal: "{count} local",
    countsBoth: "{count} both",
    alreadySaved:
      "💾 Result already saved on {date} — shown without calling codex again.",
    rerunAnyway: "Run it again anyway",
    saveProfile: "Profile",
    saveNoProfile: "— No profile —",
    saveButton: "💾 Save this search",
    saveDone: "✓ Saved —",
    saveSeeAll: "see my searches",
    saveFailed: "Could not save",
    generatedQuery: "Generated PubMed query + keywords",
    judgeSkipped:
      "⚠ codex unavailable: lexical fallback ranking (no relevance judgement).",
    noResults: "No article judged relevant for this search.",
    analyseMore: "Analyse {count} more",
    analysing: "Analysing…",
    remaining: "{count} pre-filtered abstract(s) left to judge.",
    disclaimer:
      "Relevance judged by AI from PubMed abstracts — a reading aid, not a clinical validation.",
    sourceBoth: "A · PubMed + B · local",
    sourcePubmed: "A · PubMed",
    sourceLocal: "B · local",
    revealLabel: "Structured summary",
  },

  result: {
    evidence1: "Lv. 1 · high evidence",
    evidence2: "Lv. 2 · moderate",
    evidence3: "Lv. 3 · case",
    evidence4: "Lv. 4 · opinion",
    tierHigh: "Highly relevant",
    tierMid: "Relevant",
    tierLow: "Partial",
    tierRelated: "Related",
    relevanceTitle: "Relevance {pct} % · codex score {score}/3.",
    relevanceTitleShort: "Codex score: {score} / 3 (0–3 scale).",
    ringCaption: "Relevance to your question",
    ringCaptionProfile: "Relevance to your profile",
    relevanceProfileTitle: "Relevance to your profile: {pct}%",
    ringUnit: "% match",
    featured: "★ Most relevant",
    unknownJournal: "Unknown journal",
    contributionLabel: "Takeaway",
    hideSummary: "Hide summary",
    defaultRevealLabel: "Summary & abstract",
    readOnPubmed: "Read on PubMed",
    listen: "Listen",
    stopListening: "Stop",
    readTime: "{time} read",
    source: "Source: {title}",
    aiSummary: "AI summary",
    toVerify: "to be checked",
  },

  critique: {
    selectLimit: "Limit of {max} articles reached",
    selectRemove: "Remove from selection",
    selectAdd: "Add to the critical analysis",
    selected: "Selected",
    compare: "Compare",
    selectedCount: {
      one: "{count} / {max} selected for analysis",
      other: "{count} / {max} selected for analysis",
    },
    runTitleTooFew: "Select at least 2 articles",
    runTitle: "Run the comparative critical analysis",
    run: "🔬 Analyse the selection",
    clear: "Clear",
    liveTitle: "Critical analysis — live",
    liveEmpty: "Analysis running…",
    liveReading: "codex is reading the abstracts…",
    failed: "The critical analysis failed.",
    demoUnavailable:
      "The critical analysis compares real PubMed articles. It becomes available once your digest is generated — the demo preview contains no real articles.",
    title: "Comparative critical analysis",
    subtitle:
      "Critical reading generated by AI from PubMed abstracts — a reading aid, not a clinical validation. “Not specified in the abstract” flags information missing from the abstract.",
    axisHeader: "Criterion",
    columnNo: "Article {n}",
    axisStudyType: "Study type / level of evidence",
    axisPopulation: "Population (n + profile)",
    axisPrimaryOutcome: "Primary outcome",
    axisEffectSize: "Effect size",
    axisLimits: "Limitations",
    concordance: "Agreement between the articles",
    synthesis: "Practical takeaway",
  },

  login: {
    tagline: "Explore medical research",
    checking: "Checking your session…",
    intro:
      "Sign in to access search, your profiles and your personalised digest.",
    button: "Continue with Google",
    busy: "Signing in…",
    deniedIntro:
      "The account {email} does not have access to X-Med. Contact the team to be added, or sign in with another account.",
    switchAccount: "Switch account",
    footer: "Protected access — your searches and your profile stay private.",
    errNetwork: "Cannot connect: check your network access and try again.",
    errUnauthorizedDomain:
      "This domain is not allowed in the project's Firebase configuration.",
    errOperationNotAllowed:
      "Google sign-in is not enabled on the Firebase project.",
    errGeneric: "Sign-in failed. Try again, or contact the X-Med team.",
  },

  profile: {
    title: "My profile",
    tagline: "What you get in your digest, and why",
    subtitle:
      "Your profile is linked to your Google account. It describes your practice (specialty, conditions, MeSH tags…) and drives the selection of articles in your digest.",
    loadFailed: "Could not load the profile: {error}",
    specialty: "Main specialty",
    subspecialties: "Subspecialties",
    pathologies: "Conditions",
    treatments: "Treatments",
    meshTerms: "MeSH tags (English)",
    keywords: "Keywords",
    journals: "Preferred journals",
    minEvidence: "Min. evidence level",
    evidenceAll: "All",
    evidence1: "1 — high",
    evidence2: "≤ 2",
    evidence3: "≤ 3",
    evidence4: "≤ 4",
    commaSeparated: "comma separated",
    save: "Save",
    saved: "Profile updated ✓",
    languageSection: "Language",
    languageHelp:
      "Language of the interface and of the automatic translations of articles. You can still translate a single article on demand from any result card.",
  },

  saved: {
    title: "Saved searches",
    tagline: "Your results, to read again and reuse",
    subtitle:
      "Each search is stored exactly as it was (query + articles kept). Reopening it does not call the AI again. For now every search is visible to everyone — the “🔗 Share” button copies a direct link to the results.",
    empty:
      "No saved search yet. Run a “PubMed + lexical filter + Codex” search, then click “💾 Save this search”.",
    count: { one: "{count} saved search", other: "{count} saved searches" },
    noProfile: "No profile",
    articles: { one: "{count} article", other: "{count} articles" },
    hide: "Hide",
    reopen: "Reopen / read again",
    delete: "Delete",
    confirmDelete: "Delete this saved search?",
    loadingResults: "Loading results…",
    share: "🔗 Share",
    shared: "✅ Link copied",
    sharePrompt: "Copy this link to share it:",
    backToAll: "← All saved searches",
    notFound:
      "This saved search cannot be found. The link may be wrong, or the search was deleted.",
    emptyPayload: "No article in this saved search.",
  },

  digest: {
    periodLabel: "PERIOD",
    lastDays: "Last {count} days",
    generate: "✨ Generate my digest",
    generateTitle: "Run the article selection for your profile",
    generateNoProfile: "Create your profile first",
    stop: "⏹ Stop",
    historyLabel: "HISTORY",
    historyTitle: "{date} · {count} articles · last {days} days",
    runningTitle:
      "Generating your digest — in the background (you can leave the page, it will keep going)",
    runningFirstLine: "Building the search from your profile…",
    meError:
      "Could not load your profile — sign in again, then reload the page.",
    noProfile: "Your digest is personalised from your profile.",
    createProfile: "Create my profile →",
    loadRunFailed: "Could not load this digest — please reload the page.",
    genFailed: "Generating the digest failed. Please try again later.",
    emptyResult:
      "No article kept over the last {days} days for your profile.",
    widen: "Widen to 90 days",
    inProgress: "in progress",
    demoTitle: "🧪 This is a demo preview",
    demoBody:
      "Everything below is a made-up example — a fictional “Dr Lefèvre” profile and invented articles. Click “✨ Generate my digest” to get a real PubMed selection matched to your profile.",
    kicker: "My Digest · {date}",
    headTitle: "Your watch of the day",
    headSub: "{count} articles picked for your profile — {name}, {specialty}.",
    generatedAt: "Generated {time} CET",
    method: "PubMed + GPT-5.6 · last {days} days",
    themesLabel: "YOUR TOPICS",
    adjustThemes: "adjust my topics →",
    disclaimer:
      "Selection built for your profile — a watch aid, not a clinical validation.",
    unknownJournal: "Journal not provided",
    unknownSpecialty: "Specialty not provided",
  },

  meta: {
    title: "X-Med — Explore medical research",
    description: "Search medical articles by MeSH tags or free-text question",
    howItWorksTitle: "X-Med — How it works",
    howItWorksDescription:
      "The PubMed + AI search explained technically: pipeline, v1 vs v2, batch sizes, timeouts and constraints.",
  },
};

// Pas de `as const` : on veut que les valeurs restent des `string` (sinon une
// traduction devrait répéter mot pour mot le texte anglais pour typer juste).
// Seule la STRUCTURE des clés fait contrat.
/** Forme du catalogue : toute autre langue doit la respecter exactement. */
export type Messages = typeof en;
