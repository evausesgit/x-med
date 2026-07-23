#!/usr/bin/env python3
"""Gère les domaines autorisés Firebase Auth du projet xmed-veille.

Usage :
    domains.py list
    domains.py add <domaine>
    domains.py remove <domaine>
    domains.py prune            # retire tous les N.x-med.ia-do-it.com (previews PR)

Auth : réutilise la session `firebase login` de la machine
(~/.config/configstore/firebase-tools.json). Voir SKILL.md pour le contexte.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT = "xmed-veille"
CONFIG_URL = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT}/config"
# Client OAuth PUBLIC de firebase-tools (constantes publiées dans son code
# source open source) — le secret réel est le refresh token local.
CLIENT_ID = "563584335869-fgrhgmd47bqnekij5i8b5pr03ho849e6.apps.googleusercontent.com"
CLIENT_SECRET = "j9iVZfS8kkCEFUPaAeJV0sAi"
# Jamais retirés, quoi qu'il arrive.
PROTECTED = {
    "localhost",
    f"{PROJECT}.firebaseapp.com",
    f"{PROJECT}.web.app",
    "x-med.ia-do-it.com",
}


def access_token() -> str:
    store = Path.home() / ".config/configstore/firebase-tools.json"
    refresh = json.loads(store.read_text())["tokens"]["refresh_token"]
    data = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    return json.load(urllib.request.urlopen(req))["access_token"]


def get_domains(tok: str) -> list[str]:
    req = urllib.request.Request(CONFIG_URL, headers={"Authorization": f"Bearer {tok}"})
    return json.load(urllib.request.urlopen(req)).get("authorizedDomains", [])


def set_domains(tok: str, domains: list[str]) -> list[str]:
    body = json.dumps({"authorizedDomains": domains}).encode()
    req = urllib.request.Request(
        CONFIG_URL + "?updateMask=authorizedDomains",
        data=body,
        method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req)).get("authorizedDomains", [])


def is_preview(domain: str) -> bool:
    return domain.endswith(".x-med.ia-do-it.com") and domain.split(".")[0].isdigit()


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "add", "remove", "prune"}:
        sys.exit(__doc__)
    action = sys.argv[1]
    tok = access_token()
    domains = get_domains(tok)

    if action == "list":
        pass
    elif action == "add":
        target = sys.argv[2]
        if target not in domains:
            domains = set_domains(tok, domains + [target])
    elif action == "remove":
        target = sys.argv[2]
        if target in PROTECTED:
            sys.exit(f"Refus : {target} est un domaine protégé.")
        if target in domains:
            domains = set_domains(tok, [d for d in domains if d != target])
    elif action == "prune":
        kept = [d for d in domains if d in PROTECTED or not is_preview(d)]
        if kept != domains:
            domains = set_domains(tok, kept)

    print("\n".join(domains))


if __name__ == "__main__":
    main()
