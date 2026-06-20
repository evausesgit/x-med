import type { Metadata } from "next";
import { Newsreader, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import "./xmed-app.css";
import Nav from "./Nav";

// Polices du design system « X-Med App », auto-hébergées par next/font (pas de
// requête runtime vers Google, pas de décalage de mise en page). Elles exposent
// les variables CSS consommées par globals.css / xmed-app.css.
// Variables dédiées (--ff-*) référencées par les tokens --font-* de globals.css,
// qui leur ajoutent une pile de repli générique.
const serif = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--ff-serif",
  display: "swap",
});
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--ff-sans",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--ff-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "X-Med — Explorez la recherche médicale",
  description: "Recherche d'articles médicaux par tags MeSH ou par phrase libre",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
