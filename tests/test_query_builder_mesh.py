"""Étape 1 : le modèle décrit le sens, le code rédige la requête.

Deux propriétés sont testées ici, et ce sont les deux raisons d'être du module :

- **justesse** — un descripteur MeSH inventé ne doit jamais partir en `[MeSH]`.
  PubMed ne signale pas l'erreur, il renvoie 0 en silence (mesuré :
  `"Photodynamic Therapy"[MeSH]` = 0 contre `"Photochemotherapy"[MeSH]` = 32 408) ;
- **déterminisme** — deux réponses du modèle qui disent la même chose dans un
  ordre différent doivent produire la MÊME chaîne, octet pour octet.
"""

from __future__ import annotations

import pytest

from app.services import mesh_vocab
from app.services.query_builder import (
    QueryBuildError,
    build_from_concepts,
    build_pubmed_query,
    compose_pubmed_query,
)

# Vrais descripteurs, copiés du thésaurus (table `mesh_descriptors`).
THESAURUS = [
    "Heart Failure",
    "Chemotherapy, Adjuvant",
    "Administration, Oral",
    "Photochemotherapy",
    "SARS-CoV-2",
    "Papillomavirus Infections",
    "Anticoagulants",
]


class _FakeSession:
    """Doublure de session : rend les noms du thésaurus, ou lève (base HS)."""

    def __init__(self, names=THESAURUS, boom=False):
        self.names = names
        self.boom = boom
        self.calls = 0

    def scalars(self, _stmt):
        self.calls += 1
        if self.boom:
            raise RuntimeError("corpus injoignable")
        return self

    def all(self):
        return list(self.names)


@pytest.fixture(autouse=True)
def _fresh_index():
    """L'index est un cache de module : on le vide autour de chaque test."""
    mesh_vocab.reset_index()
    yield
    mesh_vocab.reset_index()


# --------------------------------------------------------------------------- #
# Validation des descripteurs
# --------------------------------------------------------------------------- #


def test_a_real_descriptor_is_kept_under_its_official_name():
    mesh, tiab = mesh_vocab.resolve(["heart   FAILURE"], _FakeSession())
    # La casse et l'espacement du modèle sont remplacés par la forme du
    # thésaurus : plusieurs graphies convergent vers une seule chaîne.
    assert (mesh, tiab) == (["Heart Failure"], [])


def test_an_invented_descriptor_is_demoted_instead_of_returning_zero():
    mesh, tiab = mesh_vocab.resolve(["Photodynamic Therapy"], _FakeSession())
    assert mesh == []
    assert tiab == ["Photodynamic Therapy"], (
        "le terme doit rester cherchable en plein texte, pas disparaître"
    )


@pytest.mark.parametrize(
    "written,expected",
    [
        # 1. le modèle colle le tag dans le terme
        ("Heart Failure[MeSH]", "Heart Failure"),
        # 2. qualificatif MeSH — le descripteur seul existe
        ("Papillomavirus Infections/diagnosis", "Papillomavirus Infections"),
        # 3. inversion : le thésaurus range « Chemotherapy, Adjuvant »
        ("Adjuvant Chemotherapy", "Chemotherapy, Adjuvant"),
        ("Oral Administration", "Administration, Oral"),
        # la virgule sans espace tombe juste aussi
        ("chemotherapy,adjuvant", "Chemotherapy, Adjuvant"),
    ],
)
def test_the_three_repair_rules(written, expected):
    mesh, tiab = mesh_vocab.resolve([written], _FakeSession())
    assert (mesh, tiab) == ([expected], [])


def test_a_drug_is_not_a_descriptor_and_goes_to_full_text():
    # Mesuré sur PubMed : aflibercept[MeSH] = 0, [tiab] = 4 276. Le terme est
    # juste, c'est le tag qui est faux — d'où la rétrogradation plutôt que le rejet.
    mesh, tiab = mesh_vocab.resolve(["Aflibercept", "brolucizumab"], _FakeSession())
    assert mesh == []
    assert tiab == ["Aflibercept", "brolucizumab"]


def test_an_unreachable_thesaurus_changes_nothing():
    """Une panne d'infrastructure ne doit pas modifier le sens de la recherche."""
    mesh, tiab = mesh_vocab.resolve(["Whatever Term"], _FakeSession(boom=True))
    assert (mesh, tiab) == (["Whatever Term"], [])


def test_the_thesaurus_is_loaded_only_once():
    s = _FakeSession()
    mesh_vocab.resolve(["Heart Failure"], s)
    mesh_vocab.resolve(["Anticoagulants"], s)
    assert s.calls == 1, "30 600 lignes ne doivent pas être relues à chaque recherche"


# --------------------------------------------------------------------------- #
# Assemblage de la requête
# --------------------------------------------------------------------------- #


def test_the_query_is_an_and_of_or_blocks():
    q = compose_pubmed_query([(["Heart Failure"], ["HFpEF"]), ([], ["empagliflozin"])])
    assert q == '("Heart Failure"[MeSH] OR "HFpEF"[tiab]) AND ("empagliflozin"[tiab])'


def test_terms_are_quoted_and_sorted():
    """Les guillemets ne changent aucun compte PubMed (vérifié, troncature
    comprise : `"gliflozin*"[tiab]` = `gliflozin*[tiab]` = 433) mais ils
    suppriment une variation gratuite. Le tri fait le reste."""
    q = compose_pubmed_query([([], ["zebra", "Alpha", "gliflozin*"])])
    assert q == '("Alpha"[tiab] OR "gliflozin*"[tiab] OR "zebra"[tiab])'


def test_two_answers_of_the_same_meaning_give_the_same_query():
    """Le déterminisme visé : le CLI codex n'a ni température ni graine, donc il
    ne peut venir que du rétrécissement de l'espace de sortie."""
    a = [{"label_fr": "IC", "mesh": ["Heart Failure"], "synonyms_en": ["HFpEF", "CHF"]}]
    b = [{"label_fr": "ic", "mesh": ["heart failure"], "synonyms_en": ["CHF", "HFpEF"]}]
    s = _FakeSession()
    assert (
        build_from_concepts(a, s)["pubmed_query"]
        == build_from_concepts(b, _FakeSession())["pubmed_query"]
    )


def test_a_rejected_descriptor_joins_the_full_text_clause_of_its_own_concept():
    out = build_from_concepts(
        [{"label_fr": "traitement", "mesh": ["Photodynamic Therapy"],
          "synonyms_en": ["PDT"]}],
        _FakeSession(),
    )
    assert out["pubmed_query"] == '("PDT"[tiab] OR "Photodynamic Therapy"[tiab])'
    assert out["mesh_terms"] == []
    assert out["mesh_rejected"] == ["Photodynamic Therapy"]


def test_the_local_pool_keeps_synonyms_only():
    """`concepts_en` nourrit le ET du pré-filtre local. Y injecter un nom de
    descripteur (« Heart Failure ») ferait matcher des millions de lignes —
    exactement ce que le passage du OU à plat au ET a corrigé."""
    out = build_from_concepts(
        [{"label_fr": "IC", "mesh": ["Heart Failure"], "synonyms_en": ["HFpEF"]}],
        _FakeSession(),
    )
    assert out["concepts_en"] == [["HFpEF"]]
    assert out["keywords_en"] == ["HFpEF"]
    assert out["mesh_terms"] == ["Heart Failure"]


def test_an_empty_concept_is_dropped_not_left_as_an_empty_parenthesis():
    out = build_from_concepts(
        [{"label_fr": "vide", "mesh": [], "synonyms_en": ["  ", ""]},
         {"label_fr": "IC", "mesh": [], "synonyms_en": ["HFpEF"]}],
        _FakeSession(),
    )
    assert out["pubmed_query"] == '("HFpEF"[tiab])'


def test_concept_order_is_preserved():
    """Il est signifiant en aval : l'échelle de relâchement du pré-filtre retire
    les concepts les plus GÉNÉRAUX en premier, et le modèle les classe du plus
    spécifique au plus général."""
    out = build_from_concepts(
        [{"label_fr": "a", "mesh": [], "synonyms_en": ["zebra"]},
         {"label_fr": "b", "mesh": [], "synonyms_en": ["alpha"]}],
        _FakeSession(),
    )
    assert out["pubmed_query"] == '("zebra"[tiab]) AND ("alpha"[tiab])'
    assert out["concepts_en"] == [["zebra"], ["alpha"]]


def test_a_mute_model_raises_rather_than_searching_for_nothing(monkeypatch):
    from app.services import query_builder

    monkeypatch.setattr(
        query_builder, "run_codex", lambda *a, **k: ({"concepts": []}, None)
    )
    with pytest.raises(QueryBuildError):
        build_pubmed_query("question")
