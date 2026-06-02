"use client";

/* X-Med — Digest Magazine : composant client Next.js.
   Issu de la maquette ; converti en composant à props.
   - Données : passées via `data` (plus de window.DIGEST).
   - Styles : digest.css, scopés sous .xmed-digest.
   - Traduire / Résumé IA / Écouter : voir notes en bas + INTEGRATION.md. */

import { useState, useEffect } from "react";
import "./digest.css";
import type { DigestData, Article } from "./types";

/* ---------- icons ---------- */
const Ic = {
  translate: (<svg viewBox="0 0 24 24"><path d="M4 5h7M8 4v1c0 4-2 7-5 8M5 9c0 3 3 5 6 6" /><path d="M13 19l4-9 4 9M14.5 16h5" /></svg>),
  ia: (<svg viewBox="0 0 24 24"><path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z" /><path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z" /></svg>),
  speaker: (<svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9z" /><path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8 8 0 0 1 0 12" /></svg>),
  play: (<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>),
  pause: (<svg viewBox="0 0 24 24"><path d="M7 5h3v14H7zM14 5h3v14h-3z" /></svg>),
  arrow: (<svg viewBox="0 0 24 24" style={{ width: 13, height: 13, fill: "none", stroke: "currentColor", strokeWidth: 2 }}><path d="M5 12h14M13 6l6 6-6 6" /></svg>),
};

function Ev({ l, dark }: { l: number; dark?: boolean }) {
  const lab: Record<number, string> = { 1: "Niv.1 · preuve élevée", 2: "Niv.2 · modérée", 3: "Niv.3 · cas", 4: "Niv.4 · avis" };
  return <span className={`badge ${dark ? "on-ink " : ""}ev${l}`}>{lab[l]}</span>;
}
const PUB = (t: string) => "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(t);

/* ---------- speech synthesis ---------- */
const TTS = {
  ok: typeof window !== "undefined" && "speechSynthesis" in window,
  pickFr(): SpeechSynthesisVoice | null {
    const vs = window.speechSynthesis.getVoices() || [];
    return vs.find((v) => /fr/i.test(v.lang)) || null;
  },
  speak(text: string, onend: () => void) {
    if (!this.ok) { setTimeout(onend, 50); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "fr-FR";
    const v = this.pickFr();
    if (v) u.voice = v;
    u.rate = 1; u.pitch = 1;
    u.onend = onend; u.onerror = onend;
    window.speechSynthesis.speak(u);
  },
  stop() { if (this.ok) window.speechSynthesis.cancel(); },
};

function fmt(s: number) {
  const m = Math.floor(s / 60), ss = Math.floor(s % 60);
  return `${m}:${String(ss).padStart(2, "0")}`;
}

/* ---------- IA summary panel ---------- */
function IASummary({ bullets, dark }: { bullets: string[]; dark?: boolean }) {
  const [gen, setGen] = useState(true);
  useEffect(() => {
    const t = setTimeout(() => setGen(false), 1050);
    return () => clearTimeout(t);
  }, []);
  return (
    <div className={`panel-ia ia-enter ${dark ? "on-ink" : ""}`}>
      <div className="hd">
        <span className="t">{Ic.ia} Résumé IA</span>
        <span className="dis">Généré automatiquement · à vérifier</span>
      </div>
      <div className="bd">
        {gen ? (
          <div>
            <div className="gen-row"><span className="spin" /> Analyse du résumé…</div>
            <div className="shimmer-line" style={{ width: "92%" }} />
            <div className="shimmer-line" style={{ width: "78%" }} />
            <div className="shimmer-line" style={{ width: "85%", marginBottom: 0 }} />
          </div>
        ) : (
          <ul>
            {bullets.map((b, i) => (
              <li key={i} className="ia-enter" style={{ animationDelay: `${i * 70}ms` }}>{b}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ---------- audio bar ---------- */
function AudioBar({ playing, onToggle, spoken, dark }: { playing: boolean; onToggle: () => void; spoken: string; dark?: boolean }) {
  const words = spoken.trim().split(/\s+/).length;
  const total = Math.max(6, Math.round(words / 2.6));
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!playing) { setElapsed(0); return; }
    setElapsed(0);
    const t0 = Date.now();
    const iv = setInterval(() => setElapsed(Math.min(total, (Date.now() - t0) / 1000)), 200);
    return () => clearInterval(iv);
  }, [playing, total]);
  return (
    <div className={`audiobar ${dark ? "on-ink " : ""}${playing ? "playing" : ""}`}>
      <button className="play" onClick={onToggle} aria-label={playing ? "Pause" : "Écouter"}>
        {playing ? Ic.pause : Ic.play}
      </button>
      <div className="wave">
        {Array.from({ length: 32 }).map((_, i) => (
          <i key={i} style={{ animationDelay: `${(i % 8) * 0.07}s` }} />
        ))}
      </div>
      <span className="lang-note">FR · voix navigateur</span>
      <span className="atime">{fmt(elapsed)} / {fmt(total)}</span>
    </div>
  );
}

/* ---------- action bar ---------- */
function Actions({ lang, setLang, iaOpen, setIaOpen, playing, onAudio, dark }: {
  lang: "fr" | "en"; setLang: (l: "fr" | "en") => void;
  iaOpen: boolean; setIaOpen: (b: boolean) => void;
  playing: boolean; onAudio: () => void; dark?: boolean;
}) {
  const k = dark ? "on-ink" : "";
  return (
    <div className="actions">
      <button className={`act ${k} ${lang === "en" ? "on" : ""}`} onClick={() => setLang(lang === "fr" ? "en" : "fr")}>
        <span className="ic">{Ic.translate}</span>
        {lang === "fr" ? "Voir l’original (EN)" : "Traduire en français"}
        <span className="tag">{lang === "fr" ? "FR" : "EN"}</span>
      </button>
      <button className={`act ${k} ${iaOpen ? "on" : ""}`} onClick={() => setIaOpen(!iaOpen)}>
        <span className="ic">{Ic.ia}</span> Résumé IA
      </button>
      <button className={`act ${k} ${playing ? "on" : ""}`} onClick={onAudio}>
        <span className="ic">{Ic.speaker}</span> {playing ? "Arrêter" : "Écouter"}
      </button>
    </div>
  );
}

/* ---------- gauge ring ---------- */
function Gauge({ pct }: { pct: number }) {
  const [p, setP] = useState(0);
  useEffect(() => { const t = setTimeout(() => setP(pct), 200); return () => clearTimeout(t); }, [pct]);
  return (
    <div className="gauge" style={{ ["--p" as string]: p } as React.CSSProperties}>
      <div className="g-val">{pct}</div>
      <div className="g-unit">% match</div>
    </div>
  );
}

/* ---------- lead (ink panel) ---------- */
function Lead({ a, playing, onAudio }: { a: Article; playing: boolean; onAudio: () => void }) {
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const [iaOpen, setIaOpen] = useState(false);
  const t = a[lang];
  return (
    <section className="lead">
      <div className="lead-grid">
        <div>
          <div className="lk">
            <span className="kicker">Article du jour</span>
            <span className="relchip"><span className="d" /> Très pertinent</span>
          </div>
          <h1>{t.title}</h1>
          <p className="stand">{t.stand}</p>
          <div className="src">{lang === "fr" ? "Source : " : "Original — "}{a.en.title}</div>
          <div className="meta-row">
            <Ev l={a.level} dark />
            <span className="m">{a.journal} · {a.year}</span>
            <span className="m">Lecture {a.read}</span>
          </div>
          <Actions lang={lang} setLang={setLang} iaOpen={iaOpen} setIaOpen={setIaOpen} playing={playing} onAudio={onAudio} dark />
          {iaOpen && <IASummary bullets={a.why} dark />}
          {playing && <AudioBar playing={playing} onToggle={onAudio} spoken={a.spoken} dark />}
          <div style={{ marginTop: 16 }}>
            <a className="readmore" href={PUB(a.en.title)} target="_blank" rel="noreferrer">Lire sur PubMed {Ic.arrow}</a>
          </div>
        </div>
        <div className="gaugewrap">
          <Gauge pct={a.match} />
          <span className="cap">Pertinence<br />pour votre profil</span>
        </div>
      </div>
    </section>
  );
}

/* ---------- list item ---------- */
function Item({ a, n, playing, onAudio }: { a: Article; n: number; playing: boolean; onAudio: () => void }) {
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const [iaOpen, setIaOpen] = useState(false);
  const [bar, setBar] = useState(0);
  useEffect(() => { const t = setTimeout(() => setBar(a.match), 250); return () => clearTimeout(t); }, [a.match]);
  const t = a[lang];
  const tier = a.match >= 85 ? "" : a.match >= 70 ? "mid" : "low";
  const lab = a.match >= 85 ? "Très pertinent" : a.match >= 70 ? "Pertinent" : "Lié";
  return (
    <article className="item">
      <div className="top">
        <span className="no">{String(n).padStart(2, "0")}</span>
        <span className={`relchip ${tier}`}><span className="d" /> {lab}</span>
      </div>
      <h3>{t.title}</h3>
      <div className="src">{lang === "fr" ? "Source : " : "Original — "}{a.en.title}</div>
      <div className="meta-row">
        <Ev l={a.level} />
        <span className="m">{a.journal} · {a.year}</span>
        <span className="m">{a.read}</span>
      </div>
      <p className="stand">{t.stand}</p>
      <div className="relrow">
        <div className="relbar"><span style={{ width: bar + "%" }} /></div>
        <span className="relpct">{a.match}%</span>
      </div>
      <Actions lang={lang} setLang={setLang} iaOpen={iaOpen} setIaOpen={setIaOpen} playing={playing} onAudio={onAudio} />
      {iaOpen && <IASummary bullets={a.why} />}
      {playing && <AudioBar playing={playing} onToggle={onAudio} spoken={a.spoken} />}
      <div style={{ marginTop: 12 }}>
        <a className="readmore" href={PUB(a.en.title)} target="_blank" rel="noreferrer">PubMed {Ic.arrow}</a>
      </div>
    </article>
  );
}

/* ---------- composant racine ---------- */
export default function DigestMagazine({ data }: { data: DigestData }) {
  const D = data;
  const [playingId, setPlayingId] = useState<string | null>(null);
  useEffect(() => () => TTS.stop(), []);
  useEffect(() => {
    if (TTS.ok) { window.speechSynthesis.getVoices(); window.speechSynthesis.onvoiceschanged = () => {}; }
  }, []);

  function audio(id: string, spoken: string) {
    if (playingId === id) { TTS.stop(); setPlayingId(null); return; }
    setPlayingId(id);
    TTS.speak(spoken, () => setPlayingId((cur) => (cur === id ? null : cur)));
  }

  return (
    <div className="xmed-digest">
      <div className="sysbar">
        <div className="wrap">
          <div className="left">
            <span className="brand"><span className="x">X</span>-MED // DIGEST</span>
            <span className="live"><span className="dot" /> Live</span>
          </div>
          <div className="right">
            <span>Veille générée {D.generated} CET</span>
            <span>Modèle {D.model}</span>
            <span>{D.articles.length + 1} articles</span>
          </div>
        </div>
      </div>

      <header className="masthead wrap">
        <div className="row">
          <div className="word"><span className="x">X</span>-Med <span className="lbl">/ Le Digest</span></div>
          <div className="mm">
            <b>{D.date}</b><br />
            {D.doctor.name} — {D.doctor.specialty}
          </div>
        </div>
        <div className="mast-rule" />
      </header>

      <main className="wrap">
        <Lead a={D.lead} playing={playingId === D.lead.id} onAudio={() => audio(D.lead.id, D.lead.spoken)} />

        <div className="section-h">
          <h2>Sélection du jour</h2>
          <span className="count">{D.articles.length} articles</span>
        </div>
        <div className="grid">
          {D.articles.map((a, i) => (
            <Item key={a.id} a={a} n={i + 2} playing={playingId === a.id} onAudio={() => audio(a.id, a.spoken)} />
          ))}
        </div>

        <footer className="foot">
          <div className="chips">
            {D.themes.map((c) => <span className="chip" key={c}>{c}</span>)}
          </div>
          <span className="ftnote">Sélection établie pour votre profil · <a href="#">ajuster mes thèmes →</a></span>
        </footer>
      </main>
    </div>
  );
}
