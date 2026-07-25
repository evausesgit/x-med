"use client";

/* X-Med — barre de navigation (design system « X-Med App »).
   Logomark vert + « Recherche » / « Mon Digest » en accès direct ; les pages
   secondaires (sauvegardées, profils, outils internes…) vivent dans le menu
   « Plus de pages » pour garder la barre calme. État actif via le chemin courant. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { LocaleSwitcher, useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/locale";

type MenuItem = {
  labelKey: MessageKey;
  href: string;
  /** `internal` = outil d'équipe (page non traduite), `↗` = lien sortant. */
  tag?: "internal" | "↗";
  external?: boolean;
};

// Pages secondaires regroupées dans le menu déroulant.
const MENU: MenuItem[] = [
  { labelKey: "nav.saved", href: "/recherches" },
  { labelKey: "nav.profiles", href: "/profil" },
  { labelKey: "nav.annotate", href: "/annotate", tag: "internal" },
  { labelKey: "nav.evaluation", href: "/evaluation", tag: "internal" },
  { labelKey: "nav.vectorization", href: "/embeddings", tag: "internal" },
  { labelKey: "nav.howItWorks", href: "/architecture" },
  {
    labelKey: "nav.guidedTour",
    href: "/recherche-guidee/index.html",
    tag: "↗",
    external: true,
  },
];

export default function Nav() {
  const pathname = usePathname();
  const { user, signOutUser } = useAuth();
  const { t } = useT();
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
        <Link href="/" className="xm-brand" aria-label={t("nav.home")}>
          <span className="xm-logo" aria-hidden="true">
            ✕
          </span>
          <span className="xm-wordmark">X&#8209;Med</span>
        </Link>

        <div className="xm-nav-right">
          <Link href="/" className={`xm-navlink ${isSearch ? "on" : ""}`}>
            {t("nav.search")}
          </Link>
          <Link href="/digest" className={`xm-navlink ${isDigest ? "on" : ""}`}>
            {t("nav.digest")}
          </Link>
          <LocaleSwitcher />

          <div className="xm-menu-wrap" ref={wrapRef}>
            <button
              type="button"
              className="xm-menu-btn"
              aria-label={t("nav.more")}
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
                <div className="xm-menu-head">{t("nav.more")}</div>
                {MENU.map((item) => {
                  const label = t(item.labelKey);
                  const tag = item.tag === "internal" ? t("nav.internalTag") : item.tag;
                  return item.external ? (
                    <a key={item.href} className="xm-menu-item" href={item.href}>
                      {label}
                      {tag && <span className="xm-menu-tag">{tag}</span>}
                    </a>
                  ) : (
                    <Link key={item.href} className="xm-menu-item" href={item.href}>
                      {label}
                      {tag && <span className="xm-menu-tag">{tag}</span>}
                    </Link>
                  );
                })}
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
                      {t("nav.signOut")}
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
