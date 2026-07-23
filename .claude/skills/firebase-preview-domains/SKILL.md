---
name: firebase-preview-domains
description: Gérer les domaines autorisés Firebase Auth du projet xmed-veille — ajouter le domaine d'une preview PR (N.x-med.ia-do-it.com) pour que le login Google y fonctionne, et le retirer après merge. À utiliser quand une preview Coolify est déployée, quand le login échoue sur un sous-domaine (auth/unauthorized-domain), ou pour lister/nettoyer les domaines.
---

# Domaines autorisés Firebase (previews PR)

## Le problème

Le login Google (Firebase Auth, projet `xmed-veille`) ne fonctionne que sur les
**domaines autorisés** (Authentication → Settings → Authorized domains). Il n'y a
**pas de wildcard possible** : chaque preview Coolify (`{{pr_id}}.x-med.ia-do-it.com`,
ex. `34.x-med.ia-do-it.com`) doit être ajoutée individuellement, sinon la popup
Google échoue avec `auth/unauthorized-domain`.

Le MCP Firebase n'expose **aucun outil** pour ça. La console web marche mais n'est
pas scriptable. La méthode fiable : l'API REST Identity Toolkit, authentifiée avec
la session `firebase login` déjà présente sur la machine.

## La méthode

Utiliser le script fourni à côté de ce skill :

```bash
python3 .claude/skills/firebase-preview-domains/domains.py list
python3 .claude/skills/firebase-preview-domains/domains.py add 42.x-med.ia-do-it.com
python3 .claude/skills/firebase-preview-domains/domains.py remove 42.x-med.ia-do-it.com
python3 .claude/skills/firebase-preview-domains/domains.py prune   # retire tous les N.x-med.ia-do-it.com
```

Il échange le `refresh_token` de `~/.config/configstore/firebase-tools.json`
(session `firebase login` de l'utilisateur) contre un access token OAuth, puis
fait GET/PATCH sur
`https://identitytoolkit.googleapis.com/admin/v2/projects/xmed-veille/config`
avec `?updateMask=authorizedDomains`.

## Règles

- **Ajouter** le domaine dès qu'une preview est déployée et qu'on veut s'y connecter.
- **Retirer** les domaines de preview une fois la PR mergée/fermée (`prune` est
  idempotent : il ne touche que les sous-domaines numériques `N.x-med.ia-do-it.com`).
- Ne jamais retirer : `localhost`, `xmed-veille.firebaseapp.com`,
  `xmed-veille.web.app`, `x-med.ia-do-it.com` (le script les protège).
- Ne jamais afficher l'access token dans la sortie.

## Pièges connus

- Le `client_id`/`client_secret` dans le script sont ceux du **client OAuth public
  de firebase-tools** (publiés dans son code source open source) — ce ne sont pas
  des secrets du projet. Le vrai secret est le refresh token, qui reste dans
  `~/.config` et ne doit jamais être commité ni affiché.
- Si `~/.config/configstore/firebase-tools.json` manque ou que l'échange échoue
  (`invalid_grant`), la session a expiré : demander à l'utilisateur de refaire
  `firebase login` (binaire absent du PATH par défaut — voir `npx firebase-tools login`).
- Le certificat TLS d'une preview n'est émis par Traefik qu'au premier déploiement
  réussi : un échec TLS juste après le deploy est normal pendant ~1 minute et n'a
  rien à voir avec Firebase.
