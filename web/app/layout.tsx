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
              <Link href="/evaluation">Évaluation</Link>
              <Link href="/architecture">Comment ça marche</Link>
            </div>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
