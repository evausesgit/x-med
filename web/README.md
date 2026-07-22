This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## Authentification (Firebase — Google)

Toutes les pages **et** le relais `/api/*` sont protégés par un login Google
(Firebase Auth, projet `xmed-veille`, app web `xmed-web`). Seule `/login` est
publique.

Fonctionnement :

- `lib/firebase.ts` — init du SDK client (config publique du projet, surchargeable
  par `NEXT_PUBLIC_FIREBASE_*`) + cookie de session `xmed_session` qui transporte
  l'ID token Firebase (max-age 55 min < validité du jeton).
- `lib/auth-context.tsx` — `AuthProvider` monté dans le layout : maintient le
  cookie au fil des renouvellements de jeton, expose `useAuth()` (utilisateur,
  déconnexion — visible dans le menu « Plus de pages »).
- `proxy.ts` (convention Next 16, ex-middleware) — vérifie cryptographiquement
  l'ID token (jose + clés publiques Google, aucun SDK Admin ni secret serveur).
  Sans jeton valide : redirection `/login?next=…` pour les pages, 401 JSON pour
  `/api/*`.
- `app/login/page.tsx` — page de connexion (design system « X-Med App »),
  popup Google avec repli redirection.

Variables d'environnement (toutes optionnelles) :

- `NEXT_PUBLIC_FIREBASE_API_KEY / _AUTH_DOMAIN / _PROJECT_ID / _APP_ID` —
  surcharge de la config Firebase intégrée (aucun secret : config publique).
- `XMED_ALLOWED_EMAILS` — liste d'e-mails (séparés par des virgules) autorisés.
  **Vide = tout compte Google peut se connecter.** À renseigner côté Coolify
  pour restreindre l'accès (lu au runtime par `proxy.ts`).

Prérequis console Firebase (une fois) : activer le fournisseur **Google**
(Authentication → Sign-in method) et ajouter `x-med.ia-do-it.com` aux
**domaines autorisés** (Authentication → Settings → Authorized domains).
