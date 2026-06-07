from app.services.explainability import explain_article


def test_explanation_prefers_specific_concepts_and_pubmed_metadata():
    result = explain_article(
        title="Semaglutide for obesity in adults",
        abstract=(
            "We randomized 240 adults with obesity to semaglutide or placebo. "
            "Participants received weekly semaglutide for 68 weeks."
        ),
        mesh_terms=[
            "Humans",
            "Adult",
            "Obesity",
            "Semaglutide",
            "Weight Loss",
        ],
        publication_types=["Journal Article", "Randomized Controlled Trial"],
        query="sémaglutide obésité adulte",
    )

    assert set(result.concepts[:2]) == {"Semaglutide", "Obesity"}
    assert result.population == "Humans, Adult"
    assert result.intervention is not None
    assert "semaglutide" in result.intervention.lower()
    assert result.study_type == "Randomized Controlled Trial"


def test_explanation_uses_abstract_population_when_mesh_is_missing():
    result = explain_article(
        title="Screening after menopause",
        abstract="The study included 84 postmenopausal women referred for bleeding.",
        mesh_terms=["Uterine Hemorrhage"],
        publication_types=["Observational Study"],
        query="saignements après la ménopause",
    )

    assert result.population == (
        "The study included 84 postmenopausal women referred for bleeding."
    )
    assert result.intervention is None
    assert result.study_type == "Observational Study"


def test_explanation_does_not_invent_missing_fields():
    result = explain_article(
        title="Editorial perspective",
        abstract=None,
        mesh_terms=None,
        publication_types=None,
        query="glaucome",
    )

    assert result.concepts == []
    assert result.population is None
    assert result.intervention is None
    assert result.study_type is None
