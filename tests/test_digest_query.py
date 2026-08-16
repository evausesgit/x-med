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


def test_sanitized_digest_payload_leaks_no_clinical_term():
    """Le payload du digest est PERSISTÉ : aucun terme clinique ne doit y survivre.

    Le test balaie la réponse **sérialisée** plutôt que trois champs nommés : un
    futur champ qui transporterait les termes du profil (c'est exactement ce qui
    vient d'arriver avec `concepts_en`) fera échouer ce test au lieu de fuiter en
    silence dans une ligne de base de données.
    """
    from app.api.digest import _sanitize_digest_payload
    from app.api.search import DeepSearchResponse

    secrets = ["Atrial Fibrillation", "ablation", "anticoagulant"]
    resp = DeepSearchResponse(
        query="fibrillation atriale et ablation chez le sujet âgé",
        pubmed_query='"Atrial Fibrillation"[MeSH] AND "ablation"[tiab]',
        mesh_terms=["Atrial Fibrillation"],
        keywords_en=["ablation", "anticoagulant"],
        concepts_en=[["Atrial Fibrillation"], ["ablation", "anticoagulant"]],
        local_state="relaxed",
        query_builder="codex",
        judge="codex",
        counts={"local": 3},
        results=[],
    )

    _sanitize_digest_payload("Digest on-demand · Cardiologie · 30 j")(resp)

    blob = resp.model_dump_json().lower()
    for term in secrets:
        assert term.lower() not in blob, f"« {term} » survit dans le payload persisté"
    assert resp.query == "Digest on-demand · Cardiologie · 30 j"
    # L'état d'exécution, lui, doit rester : il ne dit rien du profil clinique et
    # c'est ce qui permet de diagnostiquer un digest au vivier local vide.
    assert resp.local_state == "relaxed"
