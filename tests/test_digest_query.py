from app.models import Doctor, DoctorProfile
from app.services.digest_query import build_digest_query, digest_usage_label


def _profile(**overrides) -> DoctorProfile:
    base = dict(
        specialty_main="Cardiologie",
        subspecialties=["Rythmologie"],
        pathologies=["Fibrillation atriale", "Insuffisance cardiaque"],
        treatments=["Anticoagulants oraux directs"],
        study_types=["Essai randomisé"],
        min_evidence_level=2,
        preferred_journals=["NEJM"],
        mesh_terms_extra=["Atrial Fibrillation"],
        keywords_extra=["ablation"],
    )
    base.update(overrides)
    return DoctorProfile(**base)


def test_digest_query_contains_clinical_facets_only():
    doctor = Doctor(email="eva@example.com", name="Eva Attal")
    q = build_digest_query(doctor, _profile())

    assert "Digest de veille" in q
    assert "Cardiologie" in q
    assert "Fibrillation atriale" in q
    assert "Anticoagulants oraux directs" in q
    # Préférences marquées « priorisation, pas filtre » pour le query-builder.
    assert "pas des filtres bloquants" in q
    # Jamais de données d'identité dans la query (elle part chez GPT-5.4/PubMed).
    assert "Eva" not in q
    assert "eva@example.com" not in q


def test_digest_query_omits_empty_facets():
    doctor = Doctor(email="d@x.fr", name="D")
    q = build_digest_query(
        doctor,
        _profile(
            subspecialties=[], pathologies=[], treatments=[], study_types=[],
            preferred_journals=[], mesh_terms_extra=["  "], keywords_extra=[],
            min_evidence_level=None,
        ),
    )
    assert "Sous-spécialités" not in q
    assert "Termes MeSH" not in q
    assert "Privilégier" not in q
    assert "Cardiologie" in q


def test_usage_label_is_compact_without_full_profile():
    label = digest_usage_label(_profile(), days=30)
    assert label == "Digest on-demand · Cardiologie · 30 j"
    assert "Fibrillation" not in label
