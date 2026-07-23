"use client";

// Page « Mon Digest » — digest ON-DEMAND (décision Eva : pas de génération
// automatique, on lance au clic pour maîtriser les tokens), généré en
// ARRIÈRE-PLAN côté serveur.
//
// Le bouton POSTe /api/digest/generate : le backend compose la « query » depuis
// le profil du médecin CONNECTÉ (metaprompt + facettes — elle ne transite
// jamais par l'URL) et lance la pipeline v2 dans un thread détaché. Ici on ne
// fait que POLLER le run (GET /digest/runs/{id}) : quitter la page n'interrompt
// plus rien, et on raccroche la génération en cours en revenant.
//
// L'historique liste le dernier run complet de chaque journée ; régénérer un
// jour remplace son digest affiché (le backend garde l'audit des tentatives).
// L'aperçu de démonstration reste affiché tant que rien n'a été généré.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  generateDigest,
  getDigestHistory,
  getDigestRun,
  getMe,
  stopDigestRun,
  type DigestHistory,
  type DigestRun,
  type DigestRunSummary,
  type Doctor,
} from "@/lib/api";
import DigestView from "./DigestView";
import { sampleDigest } from "./sample-data";
import { deepSearchToDigestData } from "./adapter";

// « Lundi 2 juin 2026 » (capitalisé).
function formatDayFr(d: Date): string {
  const s = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(d);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Depuis un YYYY-MM-DD. Midi pour éviter qu'un fuseau ne fasse basculer la
// date affichée sur le jour d'avant.
function dayFr(iso: string): string {
  return formatDayFr(new Date(`${iso}T12:00:00`));
}

// « mer. 23 juil. » — libellé court des puces de l'historique.
function dayShortFr(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(`${iso}T12:00:00`));
}

function timeFr(iso: string | null): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

// Fenêtres proposées. 7 jours peut rendre un digest vide sur une niche : dans ce
// cas on PROPOSE d'élargir, sans jamais relancer automatiquement (une génération
// = un clic = une recherche, jamais deux).
const PERIODS = [7, 30, 90] as const;
const DEFAULT_DAYS = 30;
const POLL_MS = 2500;

export default function DigestPage() {
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [noAccount, setNoAccount] = useState(false); // authentifié mais sans profil rattaché
  const [meError, setMeError] = useState(false);
  const [days, setDays] = useState<number>(DEFAULT_DAYS);
  const [history, setHistory] = useState<DigestHistory | null>(null);
  // Run actif pollé (running/translating) — null quand rien ne tourne.
  const [current, setCurrent] = useState<DigestRun | null>(null);
  // Run affiché (payload chargé) : le digest du jour sélectionné.
  const [view, setView] = useState<DigestRun | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const running =
    current !== null &&
    (current.status === "running" || current.status === "translating");

  const refreshHistory = useCallback(async (): Promise<DigestHistory | null> => {
    const h = await getDigestHistory().catch(() => null);
    if (mountedRef.current && h) setHistory(h);
    return h;
  }, []);

  const openDay = useCallback(async (summary: DigestRunSummary) => {
    setSelectedId(summary.id);
    try {
      const run = await getDigestRun(summary.id);
      if (mountedRef.current) setView(run);
    } catch {
      if (mountedRef.current)
        setError("Impossible de charger ce digest — rechargez la page.");
    }
  }, []);

  // Polling en setTimeout récursif (jamais setInterval : pas de requêtes qui se
  // chevauchent). Quitter la page arrête le POLLING, pas la génération.
  const poll = useCallback(
    async (id: string) => {
      let run: DigestRun;
      try {
        run = await getDigestRun(id);
      } catch {
        // Hoquet réseau : on réessaie au prochain tick.
        pollRef.current = window.setTimeout(() => void poll(id), POLL_MS);
        return;
      }
      if (!mountedRef.current) return;
      setCurrent(run);
      if (run.status === "running" || run.status === "translating") {
        pollRef.current = window.setTimeout(() => void poll(id), POLL_MS);
        return;
      }
      // Terminal : le run actif disparaît ; un succès devient le digest affiché.
      setCurrent(null);
      if (run.status === "complete") {
        setView(run);
        setSelectedId(run.id);
      } else if (run.status === "error") {
        setError(
          run.error || "La génération du digest a échoué. Réessayez plus tard.",
        );
      }
      void refreshHistory();
    },
    [refreshHistory],
  );

  useEffect(() => {
    mountedRef.current = true;
    // Lecture pure : visiter le digest ne doit rien écrire en base (le
    // rattachement du compte se fait sur la page Profil).
    getMe()
      .then((d) => (d ? setDoctor(d) : setNoAccount(true)))
      .catch(() => setMeError(true));
    void (async () => {
      const h = await refreshHistory();
      if (!mountedRef.current || !h) return;
      // On montre le dernier digest tout de suite, même si une régénération
      // tourne (l'ancien reste le digest officiel tant qu'elle n'a pas abouti).
      if (h.days.length > 0) void openDay(h.days[0]);
      if (h.current) void poll(h.current.id);
    })();
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [refreshHistory, openDay, poll]);

  async function generate(nDays: number) {
    if (running) return;
    setDays(nDays);
    setError(null);
    try {
      const run = await generateDigest(nDays);
      setCurrent({ ...run, logs: [], payload: null });
      void poll(run.id);
    } catch (e) {
      // 409 : une génération tourne déjà (autre onglet, retour sur la page…)
      // → on s'y raccroche au lieu d'afficher une erreur sèche.
      const h = await refreshHistory();
      if (h?.current) {
        void poll(h.current.id);
      } else {
        setError(
          e instanceof Error
            ? e.message
            : "La génération du digest a échoué. Réessayez plus tard.",
        );
      }
    }
  }

  function stop() {
    // Le run passera à « stopped » côté serveur ; le polling en cours le verra.
    if (current) void stopDigestRun(current.id);
  }

  const profile = doctor?.profile ?? null;
  // Pendant la phase de traduction, le payload du run en cours est déjà là :
  // on l'affiche en direct (les traductions FR se complètent au fil des polls).
  const displayRun = running && current?.payload ? current : view;
  const digest = useMemo(
    () =>
      displayRun?.payload && doctor
        ? deepSearchToDigestData(displayRun.payload, doctor, {
            date: dayFr(displayRun.digest_date),
            generated: timeFr(displayRun.finished_at) || "en cours",
            days: displayRun.days,
          })
        : null,
    [displayRun, doctor],
  );
  // Génération aboutie mais aucun article retenu sur la fenêtre.
  const emptyResult =
    !running && view !== null && view.status === "complete" && view.n_results === 0;

  return (
    <main className="xm-page">
      {meError && (
        <div className="xm-banner warn" style={{ marginTop: 0 }}>
          Impossible de charger votre profil — reconnectez-vous puis rechargez la
          page.
        </div>
      )}
      {(noAccount || (doctor && !profile)) && (
        <div className="xm-banner warn" style={{ marginTop: 0 }}>
          Votre digest se personnalise à partir de votre profil.{" "}
          <Link href="/profil">Créer mon profil →</Link>
        </div>
      )}
      <div
        className="xm-method-row"
        style={{ marginTop: 0, marginBottom: 24, gap: 10 }}
      >
        <label htmlFor="digest-days" className="xm-method-label">
          PÉRIODE
        </label>
        <select
          id="digest-days"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          disabled={running}
          style={{ width: "auto" }}
        >
          {PERIODS.map((d) => (
            <option key={d} value={d}>
              {d} derniers jours
            </option>
          ))}
        </select>
        {running ? (
          <button type="button" className="xmr-act" onClick={stop}>
            ⏹ Arrêter
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={!profile}
            onClick={() => void generate(days)}
            title={
              profile
                ? "Lancer la sélection d'articles pour votre profil"
                : "Créez d'abord votre profil"
            }
          >
            ✨ Générer mon digest
          </button>
        )}
      </div>

      {history !== null && history.days.length > 0 && (
        <div
          className="xm-method-row"
          style={{ marginTop: 0, marginBottom: 24, gap: 8, flexWrap: "wrap" }}
        >
          <span className="xm-method-label">HISTORIQUE</span>
          {history.days.map((d) => (
            <button
              key={d.id}
              type="button"
              className={d.id === selectedId ? "primary" : "xmr-act"}
              title={`${dayFr(d.digest_date)} · ${d.n_results} articles · ${d.days} derniers jours`}
              onClick={() => void openDay(d)}
            >
              {dayShortFr(d.digest_date)}
            </button>
          ))}
        </div>
      )}

      {running && (
        <div className="xm-live running">
          <div className="xm-live-head">
            <span className="xm-live-dot" />
            <span className="xm-live-title">
              Génération du digest — en arrière-plan (vous pouvez quitter la
              page, elle continuera)
            </span>
            <span className="xm-live-spin" />
          </div>
          <div className="xm-live-body">
            {(current?.logs.length ?? 0) === 0 && (
              <div className="xm-live-line">
                Composition de la recherche à partir de votre profil…
              </div>
            )}
            {current?.logs.map((l, k) => (
              <div key={k} className="xm-live-line">
                {l.msg}
              </div>
            ))}
          </div>
        </div>
      )}

      {error && <p className="xm-banner warn">⚠ {error}</p>}
      {emptyResult && (
        <div className="xm-banner warn">
          Aucun article retenu sur les {view.days} derniers jours pour votre
          profil.
          {view.days < 90 && (
            <>
              {" "}
              <button
                type="button"
                className="xmr-act"
                onClick={() => void generate(90)}
              >
                Élargir à 90 jours
              </button>
            </>
          )}
        </div>
      )}

      {digest ? (
        <DigestView key={displayRun?.id} data={digest} />
      ) : (
        !running && (
          <>
            {/* Grosse bannière : tout ce qui suit est un exemple inventé,
                pas une sélection PubMed réelle. */}
            <div className="xm-demo-title">
              <h2>🧪 Ceci est un aperçu de démonstration</h2>
              <p>
                Tout ce qui s&apos;affiche ci-dessous est un exemple fictif —
                profil « Dr Lefèvre » et articles inventés. Cliquez sur
                «&nbsp;✨ Générer mon digest&nbsp;» pour obtenir une vraie
                sélection PubMed adaptée à votre profil.
              </p>
            </div>
            <DigestView
              key="apercu"
              data={{ ...sampleDigest, date: formatDayFr(new Date()) }}
            />
          </>
        )
      )}
    </main>
  );
}
