import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "X-Med — Recherche PubMed",
  description: "Recherche d'articles médicaux par tags MeSH ou par phrase libre",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
