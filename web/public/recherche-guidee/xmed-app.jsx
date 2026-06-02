/* X-Med — démo guidée : application principale + moteur de visite guidée. */
// useState/useEffect sont déjà déclarés globalement par xmed-components.jsx
// (chargé avant ce script). Les redéclarer ici en `const` provoquerait une
// SyntaxError « Identifier 'useState' has already been declared » → page blanche.
const ANNOTATE_URL = "https://x-med.ia-do-it.com/annotate";

// ---------------- Vue d'ensemble (digest + profil, en contexte) ----------------
function BigPicture() {
  const d = window.XMED.doctor;
  const digest = window.XMED.semantic.slice(0, 2);
  return (
    <section data-tour="bigpicture">
      <div className="flow-head">
        <span className="fh-no">02</span>
        <h2>La recherche n'est qu'une porte d'entrée</h2>
      </div>
      <p className="flow-sub">
        La recherche ponctuelle que vous venez de voir s'appuie sur le même moteur que la
        veille automatique. Chaque matin, X-Med relit les nouvelles publications PubMed et
        compose un <b>digest</b> adapté à votre profil — sans que vous ayez à chercher.
      </p>

      <div className="panel profile-card">
        <div>
          <div className="profile-name">{d.name}</div>
          <div className="journal">{d.specialty}</div>
          <div className="chips" style={{ marginTop: 10, marginBottom: 0 }}>
            {d.interests.map((i) => (
              <span className="chip" key={i}>{i}</span>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
          <span className="soon">Votre profil</span>
        </div>
      </div>

      <p className="meta">Digest du 31 mai 2026 · 2 nouveaux articles pour ce profil <span className="soon">Aperçu</span></p>
      {digest.map((a) => (
        <article className="result" key={a.pmid}>
          <h3 style={{ gridTemplateColumns: "auto minmax(0,1fr)" }}>
            <span className="match-label ml-high">Prioritaire</span>
            <a href={pubmedUrl(a)} target="_blank" rel="noreferrer">{a.title}</a>
          </h3>
          <div className="journal">
            <Badge level={a.evidence_level} />
            {a.journal} · {a.pub_year}
          </div>
          <p className="abstract">{a.abstract}</p>
          <div className="actions">
            <span className="action">🌐 Traduire en français <span className="soon">Bientôt</span></span>
            <span className="action">✨ Résumé IA <span className="soon">Bientôt</span></span>
          </div>
        </article>
      ))}
    </section>
  );
}

// ---------------- Le rôle des médecins : annoter le gold set ----------------
function AnnotationCTA() {
  const [graded, setGraded] = useState(null);
  const example = window.XMED.semantic[0];
  const feedback = {
    2: "✓ « Très pertinent » : l'article répond directement à la question. C'est typiquement celui qu'on veut voir en tête.",
    1: "✓ « Pertinent » : en rapport et utile, mais partiel ou indirect.",
    0: "✓ « Non pertinent » : hors sujet, ou lien trop ténu pour être utile en pratique.",
  };
  return (
    <section data-tour="annotate">
      <div className="flow-head">
        <span className="fh-no">03</span>
        <h2>Votre rôle : créer la source de référence</h2>
      </div>
      <p className="flow-sub">
        Pour que la recherche soit fiable, il faut un « corrigé » : un ensemble de jugements de
        médecins disant, pour une question donnée, quels articles sont vraiment pertinents. C'est
        le <b>gold set</b> — et seul votre jugement clinique peut le construire.
      </p>

      <div className="cta-block">
        <h2>Annoter, c'est noter la pertinence</h2>
        <p className="lead">
          On vous présente une requête et une liste d'articles candidats. Pour chacun, vous donnez
          une note simple, à partir du titre et du résumé. Comptez 10 à 15 secondes par article.
        </p>

        <div className="cta-steps">
          <div className="cta-step">
            <div className="n">2</div>
            <h5>Très pertinent</h5>
            <p>Répond directement et précisément à la question.</p>
          </div>
          <div className="cta-step">
            <div className="n">1</div>
            <h5>Pertinent</h5>
            <p>En rapport et utile, mais partiel ou indirect.</p>
          </div>
          <div className="cta-step">
            <div className="n">0</div>
            <h5>Non pertinent</h5>
            <p>Hors sujet, ou lien trop ténu pour être utile.</p>
          </div>
        </div>

        <div className="annot-demo">
          <p className="demo-q">
            Requête : <b>{window.XMED.query}</b>
          </p>
          <article className="result" style={{ marginBottom: 0 }}>
            <div className="grade-row">
              <button className={`grade-btn g2 ${graded === 2 ? "on" : ""}`} onClick={() => setGraded(2)}>2 · Très pertinent</button>
              <button className={`grade-btn g1 ${graded === 1 ? "on" : ""}`} onClick={() => setGraded(1)}>1 · Pertinent</button>
              <button className={`grade-btn g0 ${graded === 0 ? "on" : ""}`} onClick={() => setGraded(0)}>0 · Non pertinent</button>
            </div>
            <h3 style={{ gridTemplateColumns: "1fr" }}>
              <a href={pubmedUrl(example)} target="_blank" rel="noreferrer">{example.title}</a>
            </h3>
            <div className="journal">
              <Badge level={example.evidence_level} />
              {example.journal} · {example.pub_year}
            </div>
            <p className="abstract">{example.abstract}</p>
            <div className="annot-feedback">
              {graded != null ? feedback[graded] : "Essayez : quelle note donneriez-vous à cet article pour la requête ci-dessus ?"}
            </div>
          </article>
        </div>

        <hr className="divider" style={{ margin: "24px 0 20px" }} />

        <div className="cta-cta">
          <a className="btn-link" href={ANNOTATE_URL} target="_blank" rel="noreferrer">
            Commencer à annoter →
          </a>
          <span className="cta-hint">
            Ouvre la page d'annotation X-Med · vos notes sont enregistrées automatiquement
          </span>
        </div>
      </div>
    </section>
  );
}

// ---------------- Carte de visite guidée ----------------
function TourCard({ step, idx, total, onNext, onPrev, onEnd }) {
  const centered = step.center;
  return (
    <div className={`tour-card ${centered ? "centered" : "docked"}`}>
      <span className="tour-step-no">{step.no}</span>
      <h4>{step.title}</h4>
      {step.body}
      {step.note && <div className="tour-note">{step.note}</div>}
      <div className="tour-foot">
        <div className="tour-dots">
          {Array.from({ length: total }).map((_, i) => (
            <span key={i} className={`tour-dot ${i === idx ? "on" : ""}`} />
          ))}
        </div>
        <div className="tour-btns">
          {idx > 0 && <button onClick={onPrev}>Précédent</button>}
          {idx < total - 1
            ? <button className="primary" onClick={onNext}>Suivant</button>
            : <button className="primary" onClick={onEnd}>Terminer</button>}
        </div>
      </div>
    </div>
  );
}

// ---------------- Application ----------------
function App() {
  const X = window.XMED;
  const [mode, setMode] = useState("semantic");
  const [q, setQ] = useState("");
  const [mesh, setMesh] = useState([]);
  const [yearFrom, setYearFrom] = useState("");
  const [evidenceMax, setEvidenceMax] = useState("");

  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(false);

  // ---- tour state ----
  const [tourActive, setTourActive] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [hole, setHole] = useState(null);

  function applySemantic() {
    setMode("semantic");
    setQ(X.query);
    setResults(X.semantic);
    setTotal(X.semantic.length);
    setOffset(0);
    setHasSearched(true);
  }
  function applyKeyword() {
    setMode("keyword");
    setMesh(X.keyword.mesh);
    setEvidenceMax("2");
    setYearFrom("2018");
    setResults(X.keyword.results);
    setTotal(X.keyword.total);
    setOffset(0);
    setHasSearched(true);
  }

  function onSearch() {
    setLoading(true);
    setTimeout(() => {
      if (mode === "semantic") {
        if (!q.trim()) { setLoading(false); return; }
        setResults(X.semantic);
        setTotal(X.semantic.length);
      } else {
        setResults(X.keyword.results);
        setTotal(X.keyword.total);
      }
      setOffset(0);
      setHasSearched(true);
      setLoading(false);
    }, 280);
  }

  // ---- tour steps ----
  const steps = [
    {
      no: "Visite guidée",
      center: true,
      title: "Bienvenue dans X-Med",
      body: (
        <React.Fragment>
          <p>
            X-Med vous aide à <b>explorer la littérature médicale</b> sans vous noyer : posez une
            question, lisez des résultats clairs, ouvrez l'article d'un clic.
          </p>
          <p>Cette courte visite vous montre comment chercher — en moins d'une minute.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 1",
      target: '[data-tour="modes"]',
      title: "Deux façons de chercher",
      onEnter: () => setMode("semantic"),
      body: (
        <React.Fragment>
          <p><b>Par sens</b> — décrivez votre question en français, le moteur comprend l'intention.</p>
          <p><b>Mots-clés / MeSH</b> — pour une recherche précise par tags et filtres.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 2",
      target: '[data-tour="search-input"]',
      title: "Décrivez votre question, en français",
      onEnter: () => { setMode("semantic"); setQ(X.query); },
      body: (
        <React.Fragment>
          <p>Écrivez une phrase entière, comme vous la diriez à un confrère :</p>
          <p style={{ color: "var(--accent)", fontStyle: "italic" }}>« {X.query} »</p>
          <p>Le moteur fait le pont vers les articles anglais pertinents — pas besoin de traduire.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 3",
      target: "#first-result",
      title: "Des résultats lisibles d'un coup d'œil",
      onEnter: applySemantic,
      body: (
        <React.Fragment>
          <p>Chaque article tient dans une carte épurée : titre, revue, niveau de preuve, pertinence et résumé.</p>
          <p>Plus de murs de texte : vous décidez en quelques secondes si l'article mérite une lecture.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 4",
      target: '[data-tour="result-title"]',
      title: "Un clic mène à l'article",
      onEnter: applySemantic,
      body: <p>Le titre est un lien : il ouvre la fiche complète sur <b>PubMed</b> (et l'accès libre PMC quand il existe), dans un nouvel onglet.</p>,
      note: "Essayez : cliquez le titre pour ouvrir l'article sur PubMed.",
    },
    {
      no: "Étape 5",
      target: '[data-tour="result-badge"]',
      title: "Le niveau de preuve, d'emblée",
      onEnter: applySemantic,
      body: (
        <React.Fragment>
          <p>La pastille indique la <b>solidité de l'étude</b>, déduite du type de publication :</p>
          <p><b>Niv. 1</b> méta-analyse / essai randomisé · <b>Niv. 2</b> cohorte · <b>Niv. 3</b> cas / série · <b>Niv. 4</b> avis, éditorial.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 6",
      target: '[data-tour="result-score"]',
      title: "La barre de pertinence",
      onEnter: applySemantic,
      body: (
        <React.Fragment>
          <p>Elle situe l'article <b>par rapport au meilleur résultat de la page</b> — « Très pertinent », « Pertinent » ou « Lié ».</p>
          <p>C'est une aide au tri, pas un pourcentage de certitude.</p>
        </React.Fragment>
      ),
    },
    {
      no: "Étape 7",
      target: '[data-tour="result-tags"]',
      title: "Les tags MeSH",
      onEnter: applySemantic,
      body: <p>Les termes MeSH standardisés résument le contenu de l'article. Ils servent aussi de point de départ pour affiner une recherche par mots-clés.</p>,
    },
    {
      no: "Étape 8",
      target: '[data-tour="keyword-panel"]',
      title: "Mode précis : tags + filtres",
      onEnter: applyKeyword,
      body: (
        <React.Fragment>
          <p>Besoin de précision ? Combinez des <b>tags MeSH</b> (ET / OU) et filtrez par <b>année</b> et <b>niveau de preuve</b>.</p>
          <p>L'autocomplétion vous propose les bons termes pendant que vous tapez.</p>
        </React.Fragment>
      ),
    },
    {
      no: "La suite",
      target: '[data-tour="bigpicture"]',
      title: "Au-delà de la recherche",
      body: <p>Le même moteur alimente un <b>digest quotidien</b> personnalisé : chaque matin, les nouveaux articles qui comptent pour votre profil, sans rien chercher.</p>,
    },
    {
      no: "Votre rôle",
      target: '[data-tour="annotate"]',
      title: "Aidez-nous à créer la référence",
      body: (
        <React.Fragment>
          <p>X-Med doit être <b>validé</b>. Pour cela, nous avons besoin de votre jugement clinique : noter la pertinence des articles pour construire un « corrigé » (gold set).</p>
          <p>C'est rapide, et c'est ce qui rendra l'outil fiable.</p>
        </React.Fragment>
      ),
      note: "Faites défiler : un exemple interactif vous attend juste en dessous.",
    },
    {
      no: "C'est parti",
      center: true,
      title: "À vous de jouer",
      body: (
        <React.Fragment>
          <p>Cherchez librement, ouvrez des articles, puis aidez-nous à bâtir la source de référence.</p>
          <p>
            <a href={ANNOTATE_URL} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", fontWeight: 600 }}>
              Ouvrir la page d'annotation →
            </a>
          </p>
        </React.Fragment>
      ),
    },
  ];

  // position spotlight relative to current target
  function positionFor(step) {
    if (!step || step.center) { setHole(null); return; }
    const el = document.querySelector(step.target);
    if (!el) { setHole(null); return; }
    const rect = el.getBoundingClientRect();
    const p = 8;
    setHole({
      top: rect.top - p,
      left: rect.left - p,
      width: rect.width + 2 * p,
      height: rect.height + 2 * p,
    });
  }

  // entering a step: run side effects, then poll for the target (it may render
  // after a state update), scroll to it once, and keep measuring as it settles.
  useEffect(() => {
    if (!tourActive) return;
    const step = steps[stepIdx];
    if (step.onEnter) step.onEnter();
    if (step.center) { setHole(null); return; }
    let cancelled = false;
    let scrolled = false;
    let tries = 0;
    let timer = null;
    const tick = () => {
      if (cancelled) return;
      const el = document.querySelector(step.target);
      if (el) {
        if (!scrolled) {
          scrolled = true;
          const rect = el.getBoundingClientRect();
          // bring the target into the upper area, clear of the docked card
          const targetY = window.scrollY + rect.top - window.innerHeight * 0.2;
          window.scrollTo(0, Math.max(0, targetY));
        }
        positionFor(step);
      }
      tries += 1;
      if (tries < 11) timer = setTimeout(tick, 95);
    };
    timer = setTimeout(tick, 80);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [tourActive, stepIdx]);

  // keep spotlight synced while scrolling / resizing
  useEffect(() => {
    if (!tourActive) return;
    const step = steps[stepIdx];
    if (step.center) return;
    const handler = () => positionFor(step);
    window.addEventListener("scroll", handler, { passive: true });
    window.addEventListener("resize", handler);
    return () => {
      window.removeEventListener("scroll", handler);
      window.removeEventListener("resize", handler);
    };
  }, [tourActive, stepIdx]);

  // auto-start on first visit
  useEffect(() => {
    let seen = false;
    try { seen = localStorage.getItem("xmed_tour_seen") === "1"; } catch (e) {}
    if (!seen) {
      const t = setTimeout(() => { setTourActive(true); setStepIdx(0); }, 650);
      return () => clearTimeout(t);
    }
  }, []);

  function startTour() { window.scrollTo({ top: 0, behavior: "smooth" }); setStepIdx(0); setTourActive(true); }
  function endTour() {
    setTourActive(false);
    try { localStorage.setItem("xmed_tour_seen", "1"); } catch (e) {}
  }
  function nextStep() { setStepIdx((i) => Math.min(steps.length - 1, i + 1)); }
  function prevStep() { setStepIdx((i) => Math.max(0, i - 1)); }

  useEffect(() => {
    if (!tourActive) return;
    const onKey = (e) => { if (e.key === "Escape") endTour(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tourActive]);

  const navLinks = [
    { label: "Recherche", href: "/" },
    { label: "Digest", href: "/digest" },
    { label: "Profils", href: "/profil" },
    { label: "Annoter", href: "/annotate" },
    { label: "Évaluation", href: "/evaluation" },
    { label: "Comment ça marche", href: "/architecture" },
  ];

  return (
    <React.Fragment>
      <nav className="topnav">
        <div className="topnav-inner">
          <a className="brand" href="/">X-Med</a>
          <div className="topnav-links">
            {navLinks.map((l, i) => (
              <a key={l.label} className={i === 0 ? "active" : ""} href={l.href}>{l.label}</a>
            ))}
          </div>
        </div>
      </nav>

      <main className="container">
        <h1>X-Med</h1>
        <p className="tagline">Explorez la recherche médicale</p>
        <p className="subtitle">
          Décrivez votre question en français — ou cherchez par mots-clés et tags MeSH.
          Des résultats clairs, notés et reliés directement à PubMed.
        </p>

        <div className="flow-head" style={{ marginTop: 8 }}>
          <span className="fh-no">01</span>
          <h2>Chercher un article</h2>
        </div>
        <p className="flow-sub">
          Deux modes de recherche, une même promesse : retrouver vite les bons articles, et les
          lire sans effort.
        </p>

        <SearchPanel
          mode={mode} setMode={setMode}
          q={q} setQ={setQ}
          onSearch={onSearch} loading={loading}
          mesh={mesh} setMesh={setMesh}
          yearFrom={yearFrom} setYearFrom={setYearFrom}
          evidenceMax={evidenceMax} setEvidenceMax={setEvidenceMax}
        />

        {hasSearched
          ? <Results results={results} mode={mode} total={total} offset={offset} />
          : (
            <div className="panel" style={{ textAlign: "center", color: "var(--muted)" }}>
              <p style={{ margin: 0 }}>
                Lancez une recherche — ou suivez la <b>visite guidée</b> pour voir un exemple complet.
              </p>
            </div>
          )}

        <BigPicture />
        <AnnotationCTA />
      </main>

      {/* Floating replay-tour button */}
      {!tourActive && (
        <button className="tour-fab" onClick={startTour}>
          <span aria-hidden>↻</span> Visite guidée
        </button>
      )}

      {/* Tour overlay */}
      {tourActive && (
        <React.Fragment>
          <div className="tour-backdrop" />
          <button className="tour-skip" onClick={endTour}>Passer la visite ✕</button>
          {hole && <div className="tour-hole" style={{ top: hole.top, left: hole.left, width: hole.width, height: hole.height }} />}
          <TourCard
            step={steps[stepIdx]}
            idx={stepIdx}
            total={steps.length}
            onNext={nextStep}
            onPrev={prevStep}
            onEnd={endTour}
          />
        </React.Fragment>
      )}
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
