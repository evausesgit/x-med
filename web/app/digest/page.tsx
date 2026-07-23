"use client";

// Page « Mon Digest » — digest ON-DEMAND (décision Eva : pas de génération
// automatique, on lance au clic pour maîtriser les tokens).
//
// Le bouton ouvre /api/digest/stream : le backend compose la « query » depuis le
// profil du médecin CONNECTÉ (metaprompt + facettes — elle ne transite jamais
// par l'URL) et la fait avaler par la pipeline v2 de la recherche. Ici on ne
// fait qu'écouter le déroulé (contrat SSE partagé : log* → result →
// translations* → complete) et adapter la réponse (deepSearchToDigestData).
// L'aperçu de démonstration reste affiché tant que rien n'a été généré.
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  digestStream,
  getMe,
  stopDeepSearch,
  type DeepSearchResponse,
  type Doctor,
  type PubmedLog,
} from "@/lib/api";
import DigestView from "./DigestView";
import { sampleDigest } from "./sample-data";
import { deepSearchToDigestData } from "./adapter";

// Date du jour en français, ex. « Lundi 2 juin 2026 » (capitalisée).
function todayFr(): string {
  const s = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function nowHHMM(): string {
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}

// Fenêtres proposées. 7 jours peut rendre un digest vide sur une niche : dans ce
// cas on PROPOSE d'élargir, sans jamais relancer automatiquement (une génération
// = un clic = une recherche, jamais deux).
const PERIODS = [7, 30, 90] as const;
const DEFAULT_DAYS = 30;

export default function DigestPage() {
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [noAccount, setNoAccount] = useState(false); // authentifié mais sans profil rattaché
  const [meError, setMeError] = useState(false);
  const [days, setDays] = useState<number>(DEFAULT_DAYS);
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<PubmedLog[]>([]);
  const [res, setRes] = useState<DeepSearchResponse | null>(null);
  const [generatedAt, setGeneratedAt] = useState("");
  const [genDays, setGenDays] = useState<number>(DEFAULT_DAYS); // fenêtre du digest affiché
  // Incrémenté à chaque résultat : sert de `key` à DigestView pour le REMONTER
  // à la régénération — sinon sélection et analyse critique du digest précédent
  // survivent sous les nouvelles cartes.
  const [genId, setGenId] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    // Lecture pure : visiter le digest ne doit rien écrire en base (le
    // rattachement du compte se fait sur la page Profil).
    getMe()
      .then((d) => (d ? setDoctor(d) : setNoAccount(true)))
      .catch(() => setMeError(true));
  }, []);

  // Démontage : fermer le flux ET arrêter la génération côté serveur
  // (best-effort) — fermer l'onglet ne tue pas le thread producteur tout seul.
  useEffect(
    () => () => {
      esRef.current?.close();
      if (tokenRef.current) void stopDeepSearch(tokenRef.current);
    },
    [],
  );

  function endRun() {
    tokenRef.current = null;
    setRunning(false);
  }

  function generate(nDays: number) {
    if (running) return;
    setDays(nDays);
    setRunning(true);
    setLogs([]);
    setError(null);
    // Jeton NEUF à chaque clic : le backend refuse un jeton déjà vu (protection
    // contre les doubles lancements à la reconnexion EventSource).
    const token = crypto.randomUUID();
    tokenRef.current = token;
    esRef.current?.close();
    esRef.current = digestStream(nDays, token, {
      onLog: (l) => setLogs((prev) => [...prev, l]),
      onResult: (r) => {
        setRes(r);
        setGenDays(nDays);
        setGeneratedAt(nowHHMM());
        setGenId((g) => g + 1);
      },
      // Les traductions FR arrivent après les résultats : on patche les hits,
      // l'adaptateur (useMemo) reconstruit les cartes.
      onTranslations: (fr) =>
        setRes(
          (prev) =>
            prev && {
              ...prev,
              results: prev.results.map((h) => {
                const t = fr[String(h.pmid)];
                return t
                  ? { ...h, title_fr: t.title_fr, abstract_fr: t.abstract_fr }
                  : h;
              }),
            },
        ),
      onComplete: endRun,
      onStopped: endRun,
      onError: (msg) => {
        setError(msg || "La génération du digest a échoué. Réessayez plus tard.");
        endRun();
      },
    });
  }

  function stop() {
    esRef.current?.close();
    if (tokenRef.current) void stopDeepSearch(tokenRef.current);
    endRun();
  }

  const profile = doctor?.profile ?? null;
  const digest = useMemo(
    () =>
      res && doctor
        ? deepSearchToDigestData(res, doctor, {
            date: todayFr(),
            generated: generatedAt,
            days: genDays,
          })
        : null,
    [res, doctor, generatedAt, genDays],
  );
  // Génération aboutie mais aucun article retenu sur la fenêtre.
  const emptyResult = res !== null && digest === null && !running;

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
      {doctor && profile && !digest && !running && (
        <div className="xm-banner warn" style={{ marginTop: 0 }}>
          Aperçu de démonstration — générez votre digest pour voir une vraie
          sélection : veille sur les {days} derniers jours, complétée par le fonds
          local lorsque la date précise manque.
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
            onClick={() => generate(days)}
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

      {running && (
        <div className="xm-live running">
          <div className="xm-live-head">
            <span className="xm-live-dot" />
            <span className="xm-live-title">Génération du digest — en direct</span>
            <span className="xm-live-spin" />
          </div>
          <div className="xm-live-body">
            {logs.length === 0 && (
              <div className="xm-live-line">
                Composition de la recherche à partir de votre profil…
              </div>
            )}
            {logs.map((l, k) => (
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
          Aucun article retenu sur les {genDays} derniers jours pour votre profil.
          {genDays < 90 && (
            <>
              {" "}
              <button
                type="button"
                className="xmr-act"
                onClick={() => generate(90)}
              >
                Élargir à 90 jours
              </button>
            </>
          )}
        </div>
      )}

      {digest ? (
        <DigestView key={genId} data={digest} />
      ) : (
        !running && (
          <DigestView key="apercu" data={{ ...sampleDigest, date: todayFr() }} />
        )
      )}
    </main>
  );
}
