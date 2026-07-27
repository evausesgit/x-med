"""Identités de déploiement Coolify — matrice de validation (sans réseau ni DB).

Couvre app/runtime_env.py (helper central API/init) et les gardes du
bootstrap : validation croisée init↔db↔COOLIFY_BRANCH, résolution runtime de
l'hôte db, et la ceinture absolue anti-drop (marqueur mode='production').
Contexte : incident du 2026-07-27, PLAN_EXECUTION_COMPOSE.md § journal.
"""

from __future__ import annotations

import os

import pytest

from app.runtime_env import (
    DeploymentIdentityError,
    branch_pr_number,
    check_api_db_identity,
    in_coolify_context,
    pr_suffix,
    require_consistent_services,
    resolve_db_url,
)
from scripts import bootstrap_app_db as bootstrap

URL = "postgresql+psycopg://xmed_admin:secret@db:5432/xmed_app"


@pytest.fixture(autouse=True)
def hors_coolify(monkeypatch):
    """Chaque test part d'un environnement SANS marqueur Coolify."""
    for key in list(os.environ):
        if key.startswith("SERVICE_NAME_") or key == "COOLIFY_BRANCH":
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def _coolify_prod(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME_INIT", "init")
    monkeypatch.setenv("SERVICE_NAME_DB", "db")
    monkeypatch.setenv("SERVICE_NAME_API", "api")
    monkeypatch.setenv("COOLIFY_BRANCH", '"main"')


def _coolify_preview(monkeypatch, n="51"):
    monkeypatch.setenv("SERVICE_NAME_INIT", f"init-pr-{n}")
    monkeypatch.setenv("SERVICE_NAME_DB", f"db-pr-{n}")
    monkeypatch.setenv("SERVICE_NAME_API", f"api-pr-{n}")
    monkeypatch.setenv("COOLIFY_BRANCH", f'"pull/{n}/head"')


# ---------------------------------------------------------------------------
# Primitives du helper
# ---------------------------------------------------------------------------

def test_hors_coolify_est_detecte_et_tout_est_noop():
    assert not in_coolify_context()
    check_api_db_identity()  # ne lève pas
    assert resolve_db_url(URL) == URL  # URL inchangée, hôte local accepté
    assert resolve_db_url("postgresql+psycopg://x:y@localhost:5432/z").endswith(
        "@localhost:5432/z"
    )


def test_pr_suffix_formats():
    assert pr_suffix("db", "db") is None
    assert pr_suffix("db", "db-pr-51") == "51"
    for invalide in ("db-pr-", "db-pr-x", "db2", "DB", "db-pr-51-old"):
        with pytest.raises(DeploymentIdentityError):
            pr_suffix("db", invalide)


def test_branch_pr_number(monkeypatch):
    assert branch_pr_number() is None
    monkeypatch.setenv("COOLIFY_BRANCH", '"main"')
    assert branch_pr_number() is None
    # Valeur Coolify réelle : guillemets littéraux inclus.
    monkeypatch.setenv("COOLIFY_BRANCH", '"pull/51/head"')
    assert branch_pr_number() == "51"


# ---------------------------------------------------------------------------
# Cohérence api ↔ db (garde de démarrage de l'API, app/db.py)
# ---------------------------------------------------------------------------

def test_api_db_prod_ok(monkeypatch):
    _coolify_prod(monkeypatch)
    check_api_db_identity()  # ne lève pas


def test_api_db_preview_ok(monkeypatch):
    _coolify_preview(monkeypatch)
    check_api_db_identity()  # ne lève pas


def test_api_db_mismatch(monkeypatch):
    _coolify_prod(monkeypatch)
    monkeypatch.setenv("SERVICE_NAME_API", "api-pr-3")
    with pytest.raises(DeploymentIdentityError, match="incohérents"):
        check_api_db_identity()


def test_api_db_absence_partielle(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME_API", "api")
    # SERVICE_NAME_DB absente alors que le contexte Coolify est détecté.
    with pytest.raises(DeploymentIdentityError, match="SERVICE_NAME_DB absente"):
        check_api_db_identity()


def test_require_consistent_services_retourne_le_suffixe(monkeypatch):
    _coolify_preview(monkeypatch, n="7")
    assert require_consistent_services("init", "db") == "7"
    _coolify_prod(monkeypatch)
    assert require_consistent_services("init", "db") is None


# ---------------------------------------------------------------------------
# Résolution runtime de l'hôte db
# ---------------------------------------------------------------------------

def test_resolve_host_db_substitue_en_preview(monkeypatch):
    _coolify_preview(monkeypatch, n="7")
    resolved = resolve_db_url(URL)
    assert "@db-pr-7:5432/" in resolved


def test_resolve_host_db_inchange_en_prod(monkeypatch):
    _coolify_prod(monkeypatch)
    assert resolve_db_url(URL) == URL


def test_resolve_host_non_db_refuse_en_coolify(monkeypatch):
    _coolify_prod(monkeypatch)
    with pytest.raises(DeploymentIdentityError, match="doit être 'db'"):
        resolve_db_url("postgresql+psycopg://x:y@localhost:5432/z")


def test_resolve_host_service_name_db_absente(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME_API", "api")  # contexte Coolify, DB absente
    with pytest.raises(DeploymentIdentityError, match="SERVICE_NAME_DB absente"):
        resolve_db_url(URL)


def test_resolve_host_preserve_mot_de_passe_percent_encode(monkeypatch):
    _coolify_preview(monkeypatch, n="9")
    url = "postgresql+psycopg://xmed_admin:p%40ss%25word@db:5432/xmed_app"
    resolved = resolve_db_url(url)
    assert "@db-pr-9:5432/" in resolved
    assert "p%40ss%25word" in resolved  # jamais de *** ni de décodage perdu


# ---------------------------------------------------------------------------
# Validation croisée du bootstrap (init ↔ db ↔ COOLIFY_BRANCH ↔ mode)
# ---------------------------------------------------------------------------

def test_bootstrap_prod_ok(monkeypatch):
    _coolify_prod(monkeypatch)
    bootstrap._validate_deployment_identity("production")  # ne lève pas


def test_bootstrap_preview_ok(monkeypatch):
    _coolify_preview(monkeypatch)
    bootstrap._validate_deployment_identity("preview")  # ne lève pas


def test_bootstrap_hors_coolify_noop():
    bootstrap._validate_deployment_identity("production")
    bootstrap._validate_deployment_identity("preview")


def test_bootstrap_mismatch_init_db(monkeypatch):
    _coolify_preview(monkeypatch, n="51")
    monkeypatch.setenv("SERVICE_NAME_DB", "db-pr-52")
    with pytest.raises(bootstrap.BootstrapError, match="incohérents"):
        bootstrap._validate_deployment_identity("preview")


def test_bootstrap_mismatch_coolify_branch(monkeypatch):
    _coolify_preview(monkeypatch, n="51")
    monkeypatch.setenv("COOLIFY_BRANCH", '"pull/52/head"')
    with pytest.raises(bootstrap.BootstrapError, match="PR 52"):
        bootstrap._validate_deployment_identity("preview")


def test_bootstrap_format_invalide(monkeypatch):
    _coolify_preview(monkeypatch)
    monkeypatch.setenv("SERVICE_NAME_INIT", "init-pr-abc")
    with pytest.raises(bootstrap.BootstrapError, match="format inattendu"):
        bootstrap._validate_deployment_identity("preview")


def test_bootstrap_absence_partielle(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME_INIT", "init")
    with pytest.raises(bootstrap.BootstrapError, match="SERVICE_NAME_DB absente"):
        bootstrap._validate_deployment_identity("production")


def test_bootstrap_preview_sur_services_prod(monkeypatch):
    # LE cas de l'incident : un init preview visant les services de la prod.
    _coolify_prod(monkeypatch)
    with pytest.raises(bootstrap.BootstrapError, match="PRODUCTION"):
        bootstrap._validate_deployment_identity("preview")


def test_bootstrap_production_sur_services_preview(monkeypatch):
    # Défense en profondeur : le fail-safe amont force normalement preview.
    _coolify_preview(monkeypatch)
    with pytest.raises(bootstrap.BootstrapError, match="mode production"):
        bootstrap._validate_deployment_identity("production")


# ---------------------------------------------------------------------------
# Ceinture absolue anti-drop (marqueur mode='production')
# ---------------------------------------------------------------------------

class _FakeConn:
    """Session de maintenance factice : enregistre les SQL exécutés."""

    def __init__(self):
        self.statements: list[str] = []

    def execute(self, clause, *args, **kwargs):
        self.statements.append(str(clause))


def test_drop_refuse_si_marqueur_production(monkeypatch):
    monkeypatch.setattr(bootstrap, "_marker_mode", lambda url: "production")
    conn = _FakeConn()
    with pytest.raises(bootstrap.BootstrapError, match="REFUS ABSOLU"):
        bootstrap._drop_and_recreate(conn, URL)
    assert conn.statements == []  # AUCUN SQL n'a été émis, surtout pas le DROP


@pytest.mark.parametrize("marker", [None, "preview"])
def test_drop_autorise_sinon(monkeypatch, marker):
    monkeypatch.setattr(bootstrap, "_marker_mode", lambda url: marker)
    conn = _FakeConn()
    bootstrap._drop_and_recreate(conn, URL)
    assert any("DROP DATABASE" in s for s in conn.statements)
    assert any("TEMPLATE template0" in s for s in conn.statements)
