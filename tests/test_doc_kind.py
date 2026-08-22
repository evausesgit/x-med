"""Recommandations de sociétés savantes : reconnaissance, niveau, non-régression.

Le défaut corrigé : `_EVIDENCE_BY_TYPE` ignorait les `PublicationType` de
recommandation, donc une recommandation ESC 2024 sortait au niveau 4 — reléguée
par le tri de la recherche et dépriorisée par le juge IA, alors que
PRESENTATION_MEDECINS.md la promet au médecin.
"""

from app.services.doc_kind import (
    GUIDELINE_EVIDENCE,
    effective_evidence_level,
    is_guideline,
)
from app.services.digest_query import build_digest_query
from app.services.explainability import explain_article
from app.tasks.parse_articles import _evidence_level


def test_recommandation_reconnue_et_editorial_non():
    assert is_guideline(["Journal Article", "Practice Guideline"])
    assert is_guideline(["Guideline"])
    assert is_guideline(["Consensus Development Conference"])
    assert not is_guideline(["Journal Article", "Editorial"])
    assert not is_guideline([])
    assert not is_guideline(None)


def test_ingestion_ne_classe_plus_une_recommandation_au_niveau_4():
    # Le défaut d'origine : min(levels) if levels else 4 → niveau 4.
    assert _evidence_level(["Journal Article", "Practice Guideline"]) == 1
    assert _evidence_level(["Guideline"]) == 1
    assert _evidence_level(["Consensus Development Conference"]) == 2
    # Non-régression de la grille existante.
    assert _evidence_level(["Meta-Analysis"]) == 1
    assert _evidence_level(["Case Reports"]) == 3
    assert _evidence_level(["Editorial"]) == 4
    assert _evidence_level([]) == 4


def test_correction_a_la_lecture_sans_backfill_du_corpus():
    # Les ~26 000 recommandations déjà ingérées portent evidence_level = 4 en
    # base : la correction doit se faire à la lecture, sans UPDATE sur 30 Go.
    assert effective_evidence_level(4, ["Practice Guideline"]) == 1
    assert effective_evidence_level(4, ["Consensus Development Conference"]) == 2
    # Idempotent sur les articles ingérés après le correctif.
    assert effective_evidence_level(1, ["Practice Guideline"]) == 1
    # Ne dégrade jamais un niveau déjà meilleur.
    assert effective_evidence_level(1, ["Consensus Development Conference"]) == 1
    # Neutre hors recommandation.
    assert effective_evidence_level(2, ["Clinical Trial"]) == 2
    assert effective_evidence_level(None, ["Editorial"]) is None
    assert effective_evidence_level(None, ["Guideline"]) == 1


def test_ingestion_et_lecture_partagent_la_meme_table_de_verite():
    # Les deux chemins doivent converger, sinon un article ingéré avant et un
    # après le correctif s'afficheraient à des niveaux différents.
    for pub_type, level in GUIDELINE_EVIDENCE.items():
        assert _evidence_level([pub_type]) == level
        assert effective_evidence_level(4, [pub_type]) == level


def test_panneau_pourquoi_ce_resultat_nomme_la_recommandation():
    # Une recommandation cite des RCT sans en être un : le type affiché doit
    # être « Practice Guideline », pas « Randomized Controlled Trial ».
    result = explain_article(
        title="2024 ESC Guidelines for the management of atrial fibrillation",
        abstract="These guidelines summarize randomized controlled trials.",
        mesh_terms=["Atrial Fibrillation", "Humans"],
        publication_types=["Journal Article", "Randomized Controlled Trial", "Practice Guideline"],
        query="fibrillation auriculaire anticoagulation",
    )
    assert result.study_type == "Practice Guideline"


class _Doctor:
    email = "test@example.com"
    name = "Dr Test"


class _Profile:
    specialty_main = "Cardiologie"
    subspecialties = ["Rythmologie"]
    pathologies = ["Fibrillation auriculaire"]
    treatments = []
    study_types = []
    preferred_journals = []
    mesh_terms_extra = []
    keywords_extra = []
    min_evidence_level = 1


def test_le_digest_ne_demande_plus_au_juge_d_enterrer_les_recommandations():
    # Profil « niveau I uniquement » (celui de PRESENTATION_MEDECINS.md) : la
    # consigne de priorisation ne doit pas écarter les textes de référence.
    query = build_digest_query(_Doctor(), _Profile())
    assert "Privilégier les" in query  # consigne existante conservée
    assert "recommandations et consensus de sociétés savantes" in query
    assert "ESC" in query and "HAS" in query
