"""Inventaire des routes de l'API — filet de sécurité pour le nettoyage.

Écrit **avant** le retrait des chantiers abandonnés (embeddings, évaluation,
annotation, anciens endpoints de recherche) : il fige la liste des routes qui
doivent survivre. Voir `PLAN_NETTOYAGE.md` § Étape 0, test 1.

Ce qu'il attrape : une route du cœur supprimée par erreur, ou `app.main` qui ne
s'importe plus (un routeur retiré des imports mais pas de `include_router`, un
symbole disparu…). Ni base ni réseau : s'exécute en quelques dixièmes de seconde.
"""

from app.main import app

# Routes internes générées par FastAPI : hors périmètre.
_FASTAPI_BUILTINS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

# Le cœur du produit : la recherche PubMed+IA dans ses deux modes (v1 « score IA »
# et v2 « fusion RRF » sont deux réglages du *même* endpoint `/search/pubmed/deep`),
# la traduction, l'analyse comparative, et tout ce qui entoure le compte médecin.
CORE_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    # — recherche PubMed + IA (v1 et v2)
    ("POST", "/search/pubmed/deep"),
    ("POST", "/search/pubmed/deep/more"),
    ("GET", "/search/pubmed/deep/more/stream"),
    ("POST", "/search/pubmed/deep/stop/{token}"),
    ("POST", "/search/local/stop/{token}"),
    ("GET", "/articles/{pmid}"),
    # — recherches lancées en arrière-plan
    ("GET", "/search/runs"),
    ("POST", "/search/runs"),
    ("GET", "/search/runs/{run_id}"),
    ("POST", "/search/runs/{run_id}/stop"),
    # — traduction FR (cache `article_fr`)
    ("POST", "/translate"),
    ("POST", "/translate/batch"),
    # — analyse critique comparative
    ("POST", "/analyze/compare"),
    ("GET", "/analyze/compare/stream"),
    # — recherches sauvegardées
    ("GET", "/saved-searches"),
    ("POST", "/saved-searches"),
    ("GET", "/saved-searches/lookup"),
    ("GET", "/saved-searches/{search_id}"),
    ("DELETE", "/saved-searches/{search_id}"),
    # — digest
    ("POST", "/digest/generate"),
    ("GET", "/digest/history"),
    ("GET", "/digest/runs/{run_id}"),
    ("POST", "/digest/runs/{run_id}/stop"),
    # — comptes et profils
    ("GET", "/doctors"),
    ("POST", "/doctors"),
    ("GET", "/doctors/{doctor_id}"),
    ("DELETE", "/doctors/{doctor_id}"),
    ("PUT", "/doctors/{doctor_id}/profile"),
    ("GET", "/me"),
    ("POST", "/me/bootstrap"),
    ("PUT", "/me/profile"),
}


def _routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or ())
        if method not in ("HEAD", "OPTIONS")
    }


def test_core_routes_still_exist():
    missing = CORE_ROUTES - _routes()
    assert not missing, f"routes du cœur disparues : {sorted(missing)}"


def test_no_unexpected_route_appeared():
    """Garde-fou inverse : l'API expose **exactement** `CORE_ROUTES`, rien de plus.

    Le nettoyage étant fait, ce test n'a plus de liste d'exceptions : toute route
    qui apparaît doit être ajoutée sciemment à `CORE_ROUTES`. C'est ce qui empêche
    un endpoint abandonné de revenir en douce."""
    extra = {(m, p) for m, p in _routes() if p not in _FASTAPI_BUILTINS} - CORE_ROUTES
    assert not extra, f"routes inattendues : {sorted(extra)}"
