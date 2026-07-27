"""Identités de déploiement Coolify — helper CENTRAL (API + init + bootstrap).

Incident du 2026-07-27 (PLAN_EXECUTION_COMPOSE.md § journal) : un réseau
compose nommé était partagé entre la prod et les previews, l'alias de la base
résolvait vers les DEUX bases, et l'init d'une preview a drop/re-seedé la base
de la stack de production. La leçon : les noms d'hôte internes se résolvent AU
RUNTIME à partir des variables que Coolify pose par déploiement, et chaque
process VALIDE la cohérence de son identité avant de toucher une base.

Les faits (vérifiés sur cette instance) :
- Coolify injecte dans CHAQUE conteneur d'une ressource compose les variables
  ``SERVICE_NAME_<SERVICE>`` de TOUS les services, avec la valeur du
  déploiement courant : ``db``/``api``/``init`` en production,
  ``db-pr-N``/``api-pr-N``/``init-pr-N`` en preview de la PR N ;
- ``COOLIFY_BRANCH`` vaut la branche (``"main"``) en prod et la référence PR
  (``"pull/N/head"``) en preview — valeur AVEC guillemets littéraux, d'où des
  comparaisons par recherche de motif, jamais par égalité ;
- les apps Dockerfile (prod monolithique actuelle, worker) n'ont AUCUNE
  ``SERVICE_NAME_*`` : hors contexte Coolify-compose, tout ici est no-op —
  dev local, tests, CI compris.

La substitution d'hôte vit en Python (importée par ``app/db.py`` à la création
des engines et par ``scripts/bootstrap_app_db.py``) et pas dans un CMD shell :
un ``docker compose exec`` ou une Scheduled Task contournerait un entrypoint.
"""

from __future__ import annotations

import os
import re

SERVICE_ENV_PREFIX = "SERVICE_NAME_"

# Référence PR dans COOLIFY_BRANCH ("pull/51/head", guillemets compris).
_BRANCH_PR_RE = re.compile(r"pull/([0-9]+)")


class DeploymentIdentityError(RuntimeError):
    """Incohérence d'identité de déploiement — refuser de démarrer.

    Fail-closed : un conteneur dont l'identité ne recoupe pas celle de sa base
    ne doit JAMAIS « dégrader » — il pointe peut-être la base d'un autre
    déploiement (prod depuis une preview, ou l'inverse).
    """


def in_coolify_context() -> bool:
    """Vrai si au moins une SERVICE_NAME_* est présente (ressource compose)."""
    return any(key.startswith(SERVICE_ENV_PREFIX) for key in os.environ)


def service_name(base: str) -> str | None:
    """Valeur de SERVICE_NAME_<BASE> (None si absente ou vide)."""
    return os.environ.get(f"{SERVICE_ENV_PREFIX}{base.upper()}") or None


def _seen_services() -> str:
    """Les SERVICE_NAME_* visibles, pour des messages d'erreur qui nomment tout."""
    seen = sorted(
        f"{key}={os.environ[key]!r}"
        for key in os.environ
        if key.startswith(SERVICE_ENV_PREFIX)
    )
    return ", ".join(seen) if seen else "aucune SERVICE_NAME_*"


def pr_suffix(base: str, value: str) -> str | None:
    """Suffixe PR d'un nom de service : None (prod) ou "N" (preview PR N).

    Format STRICT : ``<base>`` exactement, ou ``<base>-pr-<N>`` avec N
    numérique. Tout autre format est une identité inconnue → erreur.
    """
    if value == base:
        return None
    match = re.fullmatch(re.escape(base) + r"-pr-([0-9]+)", value)
    if match:
        return match.group(1)
    raise DeploymentIdentityError(
        f"SERVICE_NAME_{base.upper()}={value!r} : format inattendu (attendu "
        f"{base!r} ou '{base}-pr-<N>'). Contexte vu : {_seen_services()}."
    )


def branch_pr_number() -> str | None:
    """Numéro de PR porté par COOLIFY_BRANCH ("pull/N/head"), sinon None."""
    match = _BRANCH_PR_RE.search(os.environ.get("COOLIFY_BRANCH", ""))
    return match.group(1) if match else None


def require_consistent_services(*bases: str) -> str | None:
    """Valide que les services `bases` existent et portent LE MÊME suffixe PR.

    À appeler en contexte Coolify uniquement. Retourne le suffixe commun :
    None = déploiement de production, "N" = preview de la PR N.
    Absence partielle, format invalide ou suffixes divergents → erreur qui
    nomme les valeurs vues.
    """
    values: dict[str, str] = {}
    for base in bases:
        value = service_name(base)
        if value is None:
            raise DeploymentIdentityError(
                f"SERVICE_NAME_{base.upper()} absente alors que le contexte "
                f"Coolify est détecté ({_seen_services()}) : identité de "
                "déploiement invérifiable — refus de continuer."
            )
        values[base] = value

    suffixes = {base: pr_suffix(base, value) for base, value in values.items()}
    if len(set(suffixes.values())) > 1:
        detail = ", ".join(
            f"SERVICE_NAME_{base.upper()}={values[base]!r}" for base in bases
        )
        raise DeploymentIdentityError(
            f"suffixes de déploiement incohérents ({detail}) : ces services "
            "n'appartiennent pas au même déploiement — refus de continuer "
            "(schéma de l'incident du 2026-07-27)."
        )
    suffix = next(iter(suffixes.values()))
    # Des services suffixés -pr-N doivent venir d'un déploiement de PR : la
    # branche Coolify porte alors TOUJOURS un motif pull/N (vérifié
    # empiriquement sur cette instance). Branche absente, `main` ou N
    # divergent = identité invérifiable → refus (conformité stricte, revue
    # Codex). L'inverse (branche pull/N avec services nus) est déjà refusé
    # par les appelants via le mode.
    if suffix is not None:
        branch_n = branch_pr_number()
        if branch_n != suffix:
            raise DeploymentIdentityError(
                f"services suffixés -pr-{suffix} mais COOLIFY_BRANCH="
                f"{os.environ.get('COOLIFY_BRANCH')!r} ne porte pas pull/"
                f"{suffix} : identité de PR invérifiable — refus de continuer."
            )
    return suffix


def check_api_db_identity() -> None:
    """Garde de démarrage de l'API : api ↔ db du MÊME déploiement.

    ``api`` va avec ``db``, ``api-pr-N`` avec ``db-pr-N`` (même N). Toute
    divergence lève — l'API ne démarre pas sur la base d'un autre déploiement.
    No-op hors Coolify (dev local, tests, prod monolithique).
    """
    if not in_coolify_context():
        return
    require_consistent_services("api", "db")


def resolve_db_url(url: str) -> str:
    """Hôte ``db`` de l'URL app résolu au runtime via SERVICE_NAME_DB.

    Hors Coolify : URL retournée telle quelle. En contexte Coolify :
    - l'hôte DOIT être ``db`` (le compose ne référence que le nom de service
      nu ; tout autre hôte signifie une URL trafiquée ou un contournement de
      la résolution runtime) → sinon erreur, jamais de pass-through silencieux ;
    - SERVICE_NAME_DB doit exister et avoir un format valide ;
    - l'hôte est substitué par sa valeur (``db`` → inchangé, ``db-pr-N`` →
      la base de LA preview courante).

    `render_as_string(hide_password=False)` préserve le mot de passe (y
    compris percent-encodé) — `str()` le masquerait en `***`.
    """
    if not in_coolify_context():
        return url

    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.host != "db":
        raise DeploymentIdentityError(
            f"en contexte Coolify, l'hôte de l'URL app doit être 'db' (résolu "
            f"au runtime via SERVICE_NAME_DB) ; vu : {parsed.host!r}. "
            f"Contexte : {_seen_services()}."
        )
    target = service_name("db")
    if target is None:
        raise DeploymentIdentityError(
            f"SERVICE_NAME_DB absente alors que le contexte Coolify est "
            f"détecté ({_seen_services()}) : impossible de résoudre l'hôte db."
        )
    pr_suffix("db", target)  # valide le format, lève sinon
    if target == "db":
        return url
    return parsed.set(host=target).render_as_string(hide_password=False)
