from types import SimpleNamespace

from experiments.autoresearch_xmed.optimizations import translation_inputs_from_hits


def test_translation_inputs_reuse_hydrated_abstracts_and_preserve_missing_fallback():
    hits = [
        SimpleNamespace(pmid=1, title="A", abstract="abstract A", in_db=True, abstract_fr=None),
        SimpleNamespace(pmid=2, title="B", abstract=None, in_db=True, abstract_fr=None),
        SimpleNamespace(
            pmid=3,
            title="C",
            abstract="abstract C",
            in_db=True,
            abstract_fr="déjà traduit",
        ),
    ]
    ready, missing = translation_inputs_from_hits(hits)
    assert ready == [{"pmid": 1, "title": "A", "abstract": "abstract A"}]
    assert [hit.pmid for hit in missing] == [2]


def test_translation_inputs_match_current_db_then_external_order():
    hits = [
        SimpleNamespace(pmid=30, title="db 30", abstract="a", in_db=True, abstract_fr=None),
        SimpleNamespace(pmid=10, title="db 10", abstract="b", in_db=True, abstract_fr=None),
        SimpleNamespace(pmid=20, title="ext 20", abstract="c", in_db=False, abstract_fr=None),
        SimpleNamespace(pmid=5, title="ext 5", abstract="d", in_db=False, abstract_fr=None),
    ]
    ready, missing = translation_inputs_from_hits(hits)
    assert [row["pmid"] for row in ready] == [10, 30, 20, 5]
    assert missing == []
