import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "X-Med — Explorez la recherche médicale",
  description: "Recherche d'articles médicaux par tags MeSH ou par phrase libre",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body>
        <nav className="topnav">
          <div className="topnav-inner">
            <Link href="/" className="brand">
              X-Med
            </Link>
            <div className="topnav-links">
              <Link href="/">Recherche</Link>
              <Link href="/digest">Digest</Link>
              <Link href="/profil">Profils</Link>
              <Link href="/annotate">Annoter</Link>
              <Link href="/evaluation">Évaluation</Link>
              <Link href="/embeddings">Vectorisation</Link>
              <Link href="/architecture">Comment ça marche</Link>
              {/* Page statique servie depuis public/recherche-guidee/ : <a> et non
                  <Link> (le routeur Next traiterait ce chemin comme une route → 404).
                  On vise index.html explicitement : l'URL « dossier » /recherche-guidee/
                  déclenche le 308 de Next (strip du slash) puis un 404. */}
              <a href="/recherche-guidee/index.html">Visite guidée</a>
            </div>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
