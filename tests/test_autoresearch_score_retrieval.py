from copy import deepcopy

import pytest

from experiments.autoresearch_xmed.manifest import fingerprint
from experiments.autoresearch_xmed.score_retrieval import (
    RetrievalScoreError,
    _diversity_margin,
    _noninferiority,
    _quality_margin,
    _tail_noninferiority,
    compare,
    validate_pair,
)


def _metadata(pmid, *, journal="J", source="pubmed", year=2026):
    return {
        "pmid": pmid,
        "title": f"title {pmid}",
        "abstract": f"abstract {pmid}",
        "journal": journal,
        "source": source,
        "pub_year": year,
    }


def _case(query_id, width, pmids, total_s, config, metadata=None):
    rows = metadata or [_metadata(pmid) for pmid in pmids]
    builder = {"pubmed_query": f"{query_id}[tiab]", "mesh_terms": [], "keywords_en": [query_id]}
    return {
        "query_id": query_id,
        "query": f"question {query_id}",
        "width": width,
        "date_from": "2024-01-01",
        "date_to": "2026-07-31",
        "config": config,
        "query_builder": builder,
        "query_builder_fingerprint": fingerprint(builder),
        "candidate_pmids": list(pmids),
        "judgeable_pmids": list(pmids),
        "judge_pmids": list(pmids),
        "judge_items": [
            {key: row.get(key) for key in ("pmid", "title", "abstract", "journal", "pub_year")}
            for row in rows
        ],
        "selected_metadata": rows,
        "local_search": {"timed_out": False, "error": None},
        "hydration_errors": {},
        "timings": {"total_s": total_s},
        "error": None,
    }


def _set_statement_timeout(case):
    case["local_search"] = {
        "source": "articles",
        "timed_out": True,
        "error": "OperationalError: canceling statement due to statement timeout",
        "elapsed_s": 120.0,
    }
    case["local_pmids_raw"] = []
    case["local_pmids"] = []
    case["counts"] = {
        "local": 0,
        "local_dropped_window": 0,
        "local_date_unverified": 0,
    }


def _summary(*, recall=0.8, relevant=100.0, ndcg=0.7, entropy=2.0, coverage=10.0):
    return {
        "recall_at_50": recall,
        "relevant_count_total": relevant,
        "ndcg_at_10": ndcg,
        "diversity": {
            "journal_entropy": entropy,
            "journal_coverage": coverage,
            "source_entropy": entropy,
            "source_coverage": coverage,
            "year_entropy": entropy,
            "year_coverage": coverage,
        },
    }


def _tail_metric(ndcg=0.5, entropy=2.0, coverage=10.0):
    return {
        "ndcg_at_10": ndcg,
        "diversity": {
            "journal_entropy": entropy,
            "journal_coverage": coverage,
            "source_entropy": entropy,
            "source_coverage": coverage,
            "year_entropy": entropy,
            "year_coverage": coverage,
        },
    }


def _run(cases, *, config=None):
    config = config or {
        "k_pubmed": 20,
        "max_local": 200,
        "judge_batch": 50,
        "rrf": False,
        "rrf_k": 60,
        "local_floor": 0,
        "use_narrow_search": False,
    }
    copied = deepcopy(cases)
    for case in copied:
        case["config"] = config
    return {
        "schema_version": 1,
        "artifact_type": "retrieval_screen",
        "complete": True,
        "read_only": True,
        "expected_query_ids": [case["query_id"] for case in copied],
        "database": "xmed_autoresearch",
        "corpus_scope": "historical",
        "corpus_fingerprint": "corpus",
        "machine_fingerprint": "machine",
        "source_run_id": "live-source",
        "source_artifact_sha256": "source-sha",
        "runner_sha256": "runner-sha",
        "config": config,
        "config_fingerprint": fingerprint(config),
        "calls": {"query_builder": False, "judge": False, "translate": False},
        "cases": copied,
    }


def _pair():
    config = {
        "k_pubmed": 20,
        "max_local": 200,
        "judge_batch": 50,
        "rrf": False,
        "rrf_k": 60,
        "local_floor": 0,
        "use_narrow_search": False,
    }
    baseline = _run(
        [
            _case("q1", "broad", [1, 2], 10.0, config),
            _case("q2", "narrow", [3, 4], 10.0, config),
        ],
        config=config,
    )
    candidate = _run(
        [
            _case("q1", "broad", [2, 1], 8.0, config),
            _case("q2", "narrow", [3, 4], 8.0, config),
        ],
        config=config,
    )
    qrels = {
        "schema_version": 1,
        "proxy": True,
        "qrels": {"q1": {"1": 2, "2": 3}, "q2": {"3": 3, "4": 2}},
    }
    return baseline, candidate, qrels


def test_keep_screen_requires_complete_proxy_noninferiority_and_ten_percent_gain():
    baseline, candidate, qrels = _pair()

    result = compare(baseline, candidate, qrels)

    assert result["verdict"] == "keep_screen"
    assert result["production_promotion"] is False
    assert result["all_annotated"] is True
    assert result["performance"]["median_total_latency_gain"] == pytest.approx(0.2)
    assert result["per_query"]["q1"]["deltas_diagnostic"]["ndcg_at_10"] > 0


def test_unknown_pmids_are_explicit_and_make_the_screen_ineligible():
    baseline, candidate, qrels = _pair()
    candidate["cases"][0]["judge_pmids"] = [2, 99]
    candidate["cases"][0]["candidate_pmids"] = [2, 99]
    candidate["cases"][0]["judgeable_pmids"] = [2, 99]
    candidate["cases"][0]["selected_metadata"] = [_metadata(2), _metadata(99)]
    candidate["cases"][0]["judge_items"] = [
        {key: row.get(key) for key in ("pmid", "title", "abstract", "journal", "pub_year")}
        for row in candidate["cases"][0]["selected_metadata"]
    ]

    result = compare(baseline, candidate, qrels)

    assert result["verdict"] == "ineligible"
    assert result["all_annotated"] is False
    assert result["unknown_pmids"]["q1"]["candidate"] == [99]
    assert result["per_query"]["q1"]["candidate"]["coverage_top10"] == pytest.approx(0.5)
    assert set(result["bounds"]) == {"unknown_grade_0", "unknown_grade_3"}
    assert result["unknowns_can_change_noninferiority"] is True


def test_unknowns_that_do_not_change_noninferiority_still_cannot_keep():
    baseline, candidate, qrels = _pair()
    for run in (baseline, candidate):
        case = run["cases"][0]
        case["candidate_pmids"].append(99)
        case["judgeable_pmids"].append(99)
        case["judge_pmids"].append(99)
        row = _metadata(99)
        case["selected_metadata"].append(row)
        case["judge_items"].append(
            {key: row.get(key) for key in ("pmid", "title", "abstract", "journal", "pub_year")}
        )

    result = compare(baseline, candidate, qrels)

    assert result["unknowns_can_change_noninferiority"] is False
    assert result["verdict"] == "reject"


def test_quality_regression_or_insufficient_latency_gain_rejects():
    baseline, candidate, qrels = _pair()
    candidate["cases"][0]["judge_pmids"] = [1]
    candidate["cases"][0]["candidate_pmids"] = [1]
    candidate["cases"][0]["judgeable_pmids"] = [1]
    candidate["cases"][0]["selected_metadata"] = [_metadata(1)]
    candidate["cases"][0]["judge_items"] = [
        {key: row.get(key) for key in ("pmid", "title", "abstract", "journal", "pub_year")}
        for row in candidate["cases"][0]["selected_metadata"]
    ]
    assert compare(baseline, candidate, qrels)["verdict"] == "reject"

    baseline, candidate, qrels = _pair()
    for case in candidate["cases"]:
        case["timings"]["total_s"] = 9.5
    assert compare(baseline, candidate, qrels)["verdict"] == "reject"


def test_baseline_statement_timeout_candidate_success_can_keep_screen():
    baseline, candidate, qrels = _pair()
    _set_statement_timeout(baseline["cases"][0])

    result = compare(baseline, candidate, qrels)

    assert result["verdict"] == "keep_screen"
    assert result["robustness"]["gate"]["passed"] is True
    assert result["robustness"]["global"]["baseline"]["timeout_count"] == 1
    assert result["robustness"]["global"]["candidate"]["timeout_count"] == 0
    assert result["robustness"]["per_query"]["q1"]["baseline"]["timeout_count"] == 1


def test_candidate_statement_timeout_when_baseline_succeeds_rejects():
    baseline, candidate, qrels = _pair()
    _set_statement_timeout(candidate["cases"][0])

    result = compare(baseline, candidate, qrels)

    assert result["verdict"] == "reject"
    assert result["robustness"]["gate"] == {
        "passed": False,
        "global_passed": False,
        "width_failures": ["broad"],
    }


def test_non_timeout_local_error_is_still_refused():
    baseline, candidate, _ = _pair()
    candidate["cases"][0]["local_search"]["error"] = "OperationalError: connection lost"

    with pytest.raises(RetrievalScoreError, match="recherche locale en erreur"):
        validate_pair(baseline, candidate)


def test_statement_timeout_requires_empty_coherent_local_results():
    baseline, candidate, _ = _pair()
    _set_statement_timeout(candidate["cases"][0])
    candidate["cases"][0]["local_pmids"] = [99]

    with pytest.raises(RetrievalScoreError, match="listes locales incohérentes"):
        validate_pair(baseline, candidate)


def test_diversity_ignores_non_relevant_articles():
    baseline, candidate, qrels = _pair()
    qrels["qrels"]["q1"]["1"] = 0
    candidate["cases"][0]["selected_metadata"][1].update(
        journal="novel journal", source="local", pub_year=1999
    )

    result = compare(baseline, candidate, qrels)

    base = result["per_query"]["q1"]["baseline"]["diversity"]
    cand = result["per_query"]["q1"]["candidate"]["diversity"]
    assert base == cand


def test_retrieval_margins_pass_at_boundaries_and_fail_beyond_them():
    baseline = _summary()
    candidate = _summary(recall=0.78, relevant=98.0, ndcg=0.68, entropy=1.95, coverage=9.75)

    passed, failures, margins = _noninferiority(baseline, candidate)

    assert passed is True
    assert failures == []
    assert margins["recall_at_50"] == 0.02
    assert margins["relevant_count"] == 2.0
    assert margins["diversity.journal_entropy"] == 0.05
    assert margins["diversity.journal_coverage"] == 0.25

    excessive = deepcopy(candidate)
    excessive["ndcg_at_10"] = 0.679
    assert _noninferiority(baseline, excessive)[1] == ["ndcg_at_10"]

    excessive = deepcopy(candidate)
    excessive["relevant_count_total"] = 97.0
    assert _noninferiority(baseline, excessive)[1] == ["relevant_count"]

    excessive = deepcopy(candidate)
    excessive["diversity"]["journal_coverage"] = 9.749
    assert _noninferiority(baseline, excessive)[1] == ["diversity.journal_coverage"]


def test_relevant_count_margin_rounds_two_percent_down_then_applies_minimum_one():
    assert _quality_margin("relevant_count", 1.0) == 1.0
    assert _quality_margin("relevant_count", 99.0) == 1.0
    assert _quality_margin("relevant_count", 100.0) == 2.0
    assert _quality_margin("relevant_count", 149.0) == 2.0
    assert _quality_margin("relevant_count", 150.0) == 3.0
    assert _quality_margin("ndcg_at_10", 0.9) == 0.02


def test_retrieval_diversity_margins_scale_by_metric():
    assert _diversity_margin("journal_entropy", 2.0) == 0.05
    assert _diversity_margin("journal_entropy", 3.0) == pytest.approx(0.06)
    assert _diversity_margin("journal_coverage", 10.0) == 0.25
    assert _diversity_margin("journal_coverage", 20.0) == pytest.approx(0.4)


def test_retrieval_ndcg_tail_and_bootstrap_floors_are_inclusive():
    baseline = {f"q{index}": _tail_metric() for index in range(4)}
    at_tail = {
        "q0": _tail_metric(ndcg=0.45),
        **{f"q{index}": _tail_metric(ndcg=0.6) for index in range(1, 4)},
    }
    assert _tail_noninferiority(baseline, at_tail)["passed"] is True

    beyond_tail = deepcopy(at_tail)
    beyond_tail["q0"]["ndcg_at_10"] = 0.449999
    result = _tail_noninferiority(baseline, beyond_tail)
    assert result["ndcg"]["worst_quartile_passed"] is False

    at_bootstrap = {query_id: _tail_metric(ndcg=0.48) for query_id in baseline}
    assert _tail_noninferiority(baseline, at_bootstrap)["passed"] is True
    beyond_bootstrap = {query_id: _tail_metric(ndcg=0.479999) for query_id in baseline}
    result = _tail_noninferiority(baseline, beyond_bootstrap)
    assert result["ndcg"]["bootstrap_passed"] is False


def test_retrieval_diversity_tail_uses_entropy_and_category_scales():
    baseline = {f"q{index}": _tail_metric() for index in range(4)}
    at_boundary = {query_id: _tail_metric(entropy=1.9, coverage=9.0) for query_id in baseline}
    assert _tail_noninferiority(baseline, at_boundary)["passed"] is True

    beyond_entropy = deepcopy(at_boundary)
    beyond_entropy["q0"]["diversity"]["journal_entropy"] = 1.899
    result = _tail_noninferiority(baseline, beyond_entropy)
    assert result["diversity"]["failures"] == ["journal_entropy"]

    beyond_coverage = deepcopy(at_boundary)
    beyond_coverage["q0"]["diversity"]["journal_coverage"] = 8.999
    result = _tail_noninferiority(baseline, beyond_coverage)
    assert result["diversity"]["failures"] == ["journal_coverage"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda run: run.update(schema_version=2), "schema_version"),
        (lambda run: run.update(complete=False), "incomplet"),
        (lambda run: run.update(artifact_type="live"), "artifact_type"),
        (lambda run: run.update(config_fingerprint="wrong"), "fingerprint"),
        (lambda run: run["cases"][0].update(error="boom"), "en erreur"),
        (lambda run: run["cases"][0]["hydration_errors"].update(efetch="boom"), "hydratation"),
    ],
)
def test_invalid_or_degraded_screens_are_rejected(mutation, message):
    baseline, candidate, _ = _pair()
    mutation(candidate)
    with pytest.raises(RetrievalScoreError, match=message):
        validate_pair(baseline, candidate)


@pytest.mark.parametrize(
    "key",
    [
        "expected_query_ids",
        "database",
        "corpus_scope",
        "corpus_fingerprint",
        "machine_fingerprint",
        "source_run_id",
        "source_artifact_sha256",
        "runner_sha256",
    ],
)
def test_screen_pair_requires_same_query_corpus_source_and_runner(key):
    baseline, candidate, _ = _pair()
    if key == "expected_query_ids":
        candidate[key] = list(reversed(candidate[key]))
        candidate["cases"] = list(reversed(candidate["cases"]))
    else:
        candidate[key] = "different"
    with pytest.raises(RetrievalScoreError, match=key):
        validate_pair(baseline, candidate)
