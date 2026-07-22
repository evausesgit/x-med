"use client";

/* X-Med — barre de navigation (design system « X-Med App »).
   Logomark vert + « Recherche » / « Mon Digest » en accès direct ; les pages
   secondaires (sauvegardées, profils, outils internes…) vivent dans le menu
   « Plus de pages » pour garder la barre calme. État actif via le chemin courant. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";

type MenuItem = { label: string; href: string; tag?: string; external?: boolean };

// Pages secondaires regroupées dans le menu déroulant.
const MENU: MenuItem[] = [
  { label: "Sauvegardées", href: "/recherches" },
  { label: "Profils", href: "/profil" },
  { label: "Annoter", href: "/annotate", tag: "interne" },
  { label: "Évaluation", href: "/evaluation", tag: "interne" },
  { label: "Vectorisation", href: "/embeddings", tag: "interne" },
  { label: "Comment ça marche", href: "/architecture" },
  { label: "Visite guidée", href: "/recherche-guidee/index.html", tag: "↗", external: true },
];

export default function Nav() {
  const pathname = usePathname();
  const { user, signOutUser } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Ferme le menu au clic extérieur ou sur Échap.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Referme le menu à chaque changement de page.
  useEffect(() => setOpen(false), [pathname]);

  // La page de connexion est un sas plein écran : pas de barre de navigation.
  if (pathname === "/login") return null;

  const isSearch = pathname === "/";
  const isDigest = pathname === "/digest" || pathname.startsWith("/digest/");

  return (
    <nav className="xm-nav">
      <div className="xm-nav-inner">
        <Link href="/" className="xm-brand" aria-label="X-Med — accueil">
          <span className="xm-logo" aria-hidden="true">
            ✕
          </span>
          <span className="xm-wordmark">X&#8209;Med</span>
        </Link>

        <div className="xm-nav-right">
          <Link href="/" className={`xm-navlink ${isSearch ? "on" : ""}`}>
            Recherche
          </Link>
          <Link href="/digest" className={`xm-navlink ${isDigest ? "on" : ""}`}>
            Mon Digest
          </Link>
          <span className="xm-lang" title="Langue de l’interface">
            FR
          </span>

          <div className="xm-menu-wrap" ref={wrapRef}>
            <button
              type="button"
              className="xm-menu-btn"
              aria-label="Plus de pages"
              aria-haspopup="true"
              aria-controls="xm-more-menu"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <span />
              <span />
              <span />
            </button>
            {open && (
              <div className="xm-menu" id="xm-more-menu">
                <div className="xm-menu-head">Plus de pages</div>
                {MENU.map((item) =>
                  item.external ? (
                    <a key={item.href} className="xm-menu-item" href={item.href}>
                      {item.label}
                      {item.tag && <span className="xm-menu-tag">{item.tag}</span>}
                    </a>
                  ) : (
                    <Link key={item.href} className="xm-menu-item" href={item.href}>
                      {item.label}
                      {item.tag && <span className="xm-menu-tag">{item.tag}</span>}
                    </Link>
                  ),
                )}
                {user && (
                  <div className="xm-menu-user">
                    <div className="xm-menu-user-mail" title={user.email ?? undefined}>
                      {user.email}
                    </div>
                    <button
                      type="button"
                      className="xm-menu-signout"
                      onClick={signOutUser}
                    >
                      Se déconnecter
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
