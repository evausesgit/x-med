from sqlalchemy.dialects import postgresql

from app.api.search import _build_local_tsquery
from app.services import query_builder
from app.services.codex_cli import CodexUsage
from app.services.query_builder import normalize_keyword_groups


def test_keyword_groups_keep_synonyms_together_and_deduplicate_terms():
    assert normalize_keyword_groups(
        [["endometriosis", " endometriosis "], ["semaglutide", "liraglutide"]]
    ) == [["endometriosis"], ["semaglutide", "liraglutide"]]


def test_old_flat_keyword_output_falls_back_to_one_or_group():
    assert normalize_keyword_groups(None, ["hypertension", "high blood pressure"]) == [
        ["hypertension", "high blood pressure"]
    ]


def test_builder_normalizes_llm_groups_and_keeps_schema_contract(monkeypatch):
    seen = {}

    def fake_run_codex(prompt, schema, timeout):
        seen["schema"] = schema
        return (
            {
                "pubmed_query": "(A[tiab]) AND (B[tiab] OR C[tiab])",
                "mesh_terms": [],
                "keywords_en": ["A", "B", "C", "generic"],
                "keyword_groups_en": [["A"], ["B", "C"]],
            },
            CodexUsage(input_tokens=10, output_tokens=2),
        )

    monkeypatch.setattr(query_builder, "run_codex", fake_run_codex)
    data, _ = query_builder.build_pubmed_query("question")

    assert data["keyword_groups_en"] == [["A"], ["B", "C"]]
    assert data["keywords_en"] == ["A", "B", "C"]
    assert "keyword_groups_en" in seen["schema"]["required"]


def test_local_tsquery_uses_or_inside_groups_and_and_between_groups():
    expression = _build_local_tsquery(
        [["endometriosis"], ["GLP-1", "semaglutide"]],
        "question fallback",
    )
    sql = str(expression.compile(dialect=postgresql.dialect()))

    assert sql.count("websearch_to_tsquery(") == 3
    assert " || " in sql
    assert " && " in sql


def test_local_tsquery_uses_question_when_no_groups_exist():
    expression = _build_local_tsquery([], "endometriosis and GLP-1")
    sql = str(expression.compile(dialect=postgresql.dialect()))

    assert sql.startswith("websearch_to_tsquery")
    assert " || " not in sql
    assert " && " not in sql
