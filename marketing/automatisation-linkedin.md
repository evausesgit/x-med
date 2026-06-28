# Automatisation des posts LinkedIn X-Med

Génération automatique d'un brouillon de post LinkedIn par jour, à partir d'une
**vraie recherche X-Med**, envoyé sur Telegram (via Hermes) pour validation
humaine avant publication manuelle. Rien n'est publié automatiquement.

## Pièces

| Fichier | Rôle |
|---|---|
| `scripts/linkedin/topics.json` | 30 sujets médicaux (accroche FR+EN + requête X-Med) |
| `app/services/linkedin_post.py` | Cœur : recherche X-Med → rédaction codex → envoi Hermes |
| `scripts/linkedin_daily.py` | CLI : sujet+format du jour (rotation), envoi ou dry-run |

## Fonctionnement

1. **Rotation déterministe** sujet + format selon la date (`date.today().toordinal()`).
   3 formats alternent : `science` / `myth` / `brief`.
2. **Recherche X-Med** : d'abord `/saved-searches/lookup` (réutilise une recherche
   identique déjà faite = zéro coût codex). Sinon lance `/search/pubmed/deep` puis
   sauvegarde le snapshot pour les fois suivantes.
3. **Rédaction** : `run_codex` (GPT-5.4) avec schéma JSON imposé → `post_fr`,
   `post_en`, `hashtags`, `citations`. Garde-fous santé câblés dans le prompt :
   citer les PMID, distinguer association/causalité, jamais de conseil clinique,
   ligne disclaimer en FR et EN.
4. **Envoi** : `hermes send --to telegram` (même mécanique que les notifs de
   recherche, `app/services/search_notifications.py`).

## Utilisation manuelle

```bash
cd /home/geekette/projects/x-med
.venv/bin/python -m scripts.linkedin_daily              # post du jour → Telegram
.venv/bin/python -m scripts.linkedin_daily --dry-run    # affiche sans envoyer
.venv/bin/python -m scripts.linkedin_daily --topic ozempic-depression --format myth
.venv/bin/python -m scripts.linkedin_daily --index 5    # forcer la position dans la rotation
```

## Planification (cron local)

Cron utilisateur, tous les jours à **6h00** :

```cron
# PATH du cron complété avec ~/.npm-global/bin (sinon codex introuvable, cf. CLAUDE.md)
PATH=/home/geekette/.npm-global/bin:/home/geekette/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# X-Med — brouillon LinkedIn quotidien (Telegram via Hermes), 6h00
0 6 * * * cd /home/geekette/projects/x-med && /home/geekette/projects/x-med/.venv/bin/python -m scripts.linkedin_daily >> /tmp/xmed-linkedin.log 2>&1
```

⚠️ **Piège PATH** (cf. CLAUDE.md) : le cron a un PATH minimal, comme un agent.
`~/.npm-global/bin` (codex) et `~/.local/bin` (hermes) doivent y figurer, sinon
`codex` est introuvable et la génération échoue. Vérifier : `command -v codex`.

Prérequis : l'API X-Med doit tourner sur `:8800` (cf. `scripts/dev_up.sh`).

Log d'exécution : `/tmp/xmed-linkedin.log`.

## Workflow quotidien (côté humain)

1. 6h00 — un brouillon FR+EN arrive sur Telegram.
2. Relire / ajuster le ton.
3. Coller sur la page entreprise LinkedIn X-Med.

## Évolutions possibles

- Brancher Buffer/Publer (API autorisée LinkedIn) pour programmer la publication
  au lieu du copier-coller manuel.
- Générer plusieurs posts d'avance (calendrier éditorial).
- Visuel auto par post.
