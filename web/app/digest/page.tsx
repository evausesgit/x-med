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
import { useT } from "@/lib/i18n";
import { sampleDigestFor } from "./sample-data";
import { deepSearchToDigestData } from "./adapter";

// « Lundi 2 juin 2026 » / « Monday, June 2, 2026 » (capitalisé : en français
// Intl rend « lundi » en minuscule, or c'est un début de phrase).
function formatDay(d: Date, tag: string): string {
  const s = new Intl.DateTimeFormat(tag, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(d);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Depuis un YYYY-MM-DD. Midi pour éviter qu'un fuseau ne fasse basculer la
// date affichée sur le jour d'avant.
function day(iso: string, tag: string): string {
  return formatDay(new Date(`${iso}T12:00:00`), tag);
}

// « mer. 23 juil. » — libellé court des puces de l'historique.
function dayShort(iso: string, tag: string): string {
  return new Intl.DateTimeFormat(tag, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(`${iso}T12:00:00`));
}

function time(iso: string | null, tag: string): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat(tag, {
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
  const { t, tag, locale } = useT();
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
  // Verrou du POST /digest/generate : `running` ne devient vrai qu'à la
  // réponse, un double-clic lancerait deux générations (la 2e prendrait un 409
  // mais démarrerait sa propre boucle de polling).
  const [launching, setLaunching] = useState(false);
  const pollRef = useRef<number | null>(null);
  // Numéro de la boucle de polling courante : démarrer une nouvelle boucle
  // invalide l'ancienne (sinon deux boucles pourraient poller en parallèle,
  // et `pollRef` ne permettrait d'en annuler qu'une).
  const pollSeqRef = useRef(0);
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
        setError(t("digest.loadRunFailed"));
    }
  }, []);

  // Polling en setTimeout récursif (jamais setInterval : pas de requêtes qui se
  // chevauchent). Quitter la page arrête le POLLING, pas la génération.
  const poll = useCallback(
    async (id: string, seq: number) => {
      const alive = () => mountedRef.current && seq === pollSeqRef.current;
      if (!alive()) return;
      let run: DigestRun;
      try {
        run = await getDigestRun(id);
      } catch {
        // Hoquet réseau : on réessaie au prochain tick (sauf page démontée).
        if (alive())
          pollRef.current = window.setTimeout(() => void poll(id, seq), POLL_MS);
        return;
      }
      if (!alive()) return;
      setCurrent(run);
      if (run.status === "running" || run.status === "translating") {
        pollRef.current = window.setTimeout(() => void poll(id, seq), POLL_MS);
        return;
      }
      // Terminal : le run actif disparaît ; un succès devient le digest affiché.
      setCurrent(null);
      if (run.status === "complete") {
        setView(run);
        setSelectedId(run.id);
      } else if (run.status === "error") {
        setError(run.error || t("digest.genFailed"));
      }
      void refreshHistory();
    },
    [refreshHistory],
  );

  // Point d'entrée UNIQUE du polling : invalide la boucle précédente.
  const startPolling = useCallback(
    (id: string) => {
      pollSeqRef.current += 1;
      if (pollRef.current) clearTimeout(pollRef.current);
      void poll(id, pollSeqRef.current);
    },
    [poll],
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
      if (h.current) startPolling(h.current.id);
    })();
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [refreshHistory, openDay, startPolling]);

  async function generate(nDays: number) {
    if (running || launching) return;
    setDays(nDays);
    setError(null);
    setLaunching(true);
    try {
      const run = await generateDigest(nDays);
      setCurrent({ ...run, logs: [], payload: null });
      startPolling(run.id);
    } catch (e) {
      // 409 : une génération tourne déjà (autre onglet, retour sur la page…)
      // → on s'y raccroche au lieu d'afficher une erreur sèche.
      const h = await refreshHistory();
      if (h?.current) {
        startPolling(h.current.id);
      } else {
        setError(
          e instanceof Error ? e.message : t("digest.genFailed"),
        );
      }
    } finally {
      setLaunching(false);
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
            date: day(displayRun.digest_date, tag),
            generated:
              time(displayRun.finished_at, tag) || t("digest.inProgress"),
            days: displayRun.days,
            t,
          })
        : null,
    [displayRun, doctor, tag, t],
  );
  // Génération aboutie mais aucun article retenu sur la fenêtre.
  const emptyResult =
    !running && view !== null && view.status === "complete" && view.n_results === 0;

  return (
    <main className="xm-page">
      {meError && (
        <div className="xm-banner warn" style={{ marginTop: 0 }}>
          {t("digest.meError")}
        </div>
      )}
      {(noAccount || (doctor && !profile)) && (
        <div className="xm-banner warn" style={{ marginTop: 0 }}>
          {t("digest.noProfile")}{" "}
          <Link href="/profil">{t("digest.createProfile")}</Link>
        </div>
      )}
      <div
        className="xm-method-row"
        style={{ marginTop: 0, marginBottom: 24, gap: 10 }}
      >
        <label htmlFor="digest-days" className="xm-method-label">
          {t("digest.periodLabel")}
        </label>
        <select
          id="digest-days"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          disabled={running || launching}
          style={{ width: "auto" }}
        >
          {PERIODS.map((d) => (
            <option key={d} value={d}>
              {t("digest.lastDays", { count: d })}
            </option>
          ))}
        </select>
        {running ? (
          <button type="button" className="xmr-act" onClick={stop}>
            {t("digest.stop")}
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={!profile || launching}
            onClick={() => void generate(days)}
            title={t(
              profile ? "digest.generateTitle" : "digest.generateNoProfile",
            )}
          >
            {t("digest.generate")}
          </button>
        )}
      </div>

      {history !== null && history.days.length > 0 && (
        <div
          className="xm-method-row"
          style={{ marginTop: 0, marginBottom: 24, gap: 8, flexWrap: "wrap" }}
        >
          <span className="xm-method-label">{t("digest.historyLabel")}</span>
          {history.days.map((d) => (
            <button
              key={d.id}
              type="button"
              className={d.id === selectedId ? "primary" : "xmr-act"}
              title={t("digest.historyTitle", {
                date: day(d.digest_date, tag),
                count: d.n_results,
                days: d.days,
              })}
              onClick={() => void openDay(d)}
            >
              {dayShort(d.digest_date, tag)}
            </button>
          ))}
        </div>
      )}

      {running && (
        <div className="xm-live running">
          <div className="xm-live-head">
            <span className="xm-live-dot" />
            <span className="xm-live-title">{t("digest.runningTitle")}</span>
            <span className="xm-live-spin" />
          </div>
          <div className="xm-live-body">
            {(current?.logs.length ?? 0) === 0 && (
              <div className="xm-live-line">
                {t("digest.runningFirstLine")}
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
          {t("digest.emptyResult", { days: view.days })}
          {view.days < 90 && (
            <>
              {" "}
              <button
                type="button"
                className="xmr-act"
                onClick={() => void generate(90)}
              >
                {t("digest.widen")}
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
              <h2>{t("digest.demoTitle")}</h2>
              <p>{t("digest.demoBody")}</p>
            </div>
            <DigestView
              key="apercu"
              data={{
                ...sampleDigestFor(locale),
                date: formatDay(new Date(), tag),
              }}
            />
          </>
        )
      )}
    </main>
  );
}
