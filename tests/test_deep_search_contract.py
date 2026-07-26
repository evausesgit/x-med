"""Contrat de réponse de la recherche PubMed+IA — figé sur de vraies données.

Écrit **avant** le nettoyage (voir `PLAN_NETTOYAGE.md` § Étape 0, test 2).

Les trois fixtures de `tests/fixtures/` sont des `payload` réels extraits de la
table `saved_searches` : ce sont des réponses `/search/pubmed/deep` complètes,
telles qu'elles ont été enregistrées par les utilisateurs. Elles couvrent
volontairement des générations différentes du format (`counts` s'est enrichi au
fil du temps : `judgeable`, puis `kept_pubmed`/`kept_local`/`kept_both`).

L'enjeu dépasse les tests : si le modèle de réponse change de façon incompatible,
ce ne sont pas seulement ces fixtures qui cassent, ce sont les **42 recherches
sauvegardées** qui deviennent illisibles sur `/recherches`.

Note de couverture, à assumer : les 42 snapshots en base sont tous en méthode v2.
Le format de réponse est cependant le *même objet* `DeepSearchResponse` pour v1 et
v2 — les deux modes ne diffèrent que par la sélection des candidats, pas par la
forme de la réponse. La différence v1/v2 est couverte par le test 3.
"""

import json
from pathlib import Path

import pytest

from app.api.search import DeepSearchResponse

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("deep_v2_*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixtures_are_present():
    # Un glob vide ferait passer tous les tests paramétrés en silence.
    assert len(FIXTURES) == 3, f"fixtures attendues manquantes : {FIXTURES}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_saved_snapshot_still_parses(path: Path):
    """Une recherche sauvegardée doit toujours se relire dans le modèle actuel."""
    resp = DeepSearchResponse.model_validate(_load(path))

    assert resp.query
    assert resp.query_builder in ("codex", "fallback")
    assert resp.judge in ("codex", "skipped")
    assert resp.results, "une recherche sauvegardée a forcément au moins un résultat"
    assert resp.counts["kept"] == len(resp.results)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_hits_keep_their_display_fields(path: Path):
    """Les champs dont dépend l'affichage d'un résultat sur `/recherches`."""
    resp = DeepSearchResponse.model_validate(_load(path))

    for hit in resp.results:
        assert hit.pmid > 0
        assert hit.title
        assert hit.pubmed_url.endswith(f"/{hit.pmid}/")
        assert hit.source in ("pubmed", "local", "both")
        assert isinstance(hit.in_db, bool)
        # Un résultat conservé a forcément été jugé : le score est la clé de tri.
        assert hit.score is not None and 0 <= hit.score <= 3
        # `relevance_pct` est plus récent que `score` : 201 des 444 résultats
        # sauvegardés ne l'ont pas. Il doit donc rester facultatif — mais valide
        # quand il est là.
        if hit.relevance_pct is not None:
            assert 0 <= hit.relevance_pct <= 100


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_snapshot_round_trips(path: Path):
    """Relecture puis ré-sérialisation : aucun champ ne doit se perdre en route
    (c'est exactement ce que fait `/saved-searches` en relisant le jsonb)."""
    original = _load(path)
    again = DeepSearchResponse.model_validate(original).model_dump()

    for key, value in original.items():
        assert key in again, f"champ perdu à la relecture : {key}"
        if key != "results":
            assert again[key] == value, f"champ modifié à la relecture : {key}"

    assert [h["pmid"] for h in again["results"]] == [
        h["pmid"] for h in original["results"]
    ], "l'ordre des résultats doit être préservé"


def test_translated_snapshot_keeps_french():
    """Le cache de traduction FR (`article_fr`, payé en tokens) transite par la
    réponse : `title_fr` / `abstract_fr` ne doivent pas disparaître du modèle."""
    path = next(p for p in FIXTURES if p.stem == "deep_v2_translated")
    resp = DeepSearchResponse.model_validate(_load(path))

    assert any(h.abstract_fr for h in resp.results)
    assert any(h.title_fr for h in resp.results)
