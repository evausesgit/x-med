from copy import deepcopy
import json

import pytest

from experiments.autoresearch_xmed.manifest import (
    BASELINE_BEHAVIOR_CONFIG,
    ManifestError,
    build_protocol,
    load_manifest_identity,
    make_manifest,
    validate_manifest,
    variant_identity,
)
from experiments.autoresearch_xmed.score import InvalidArtifact, compare, load_json


def _experiment(**changes):
    value = {
        "name": "baseline",
        "gate": "fidelity",
        **BASELINE_BEHAVIOR_CONFIG,
    }
    value.update(changes)
    return value


def _case(query_id: str, latency: float = 10.0) -> dict:
    return {
        "query_id": query_id,
        "latency_s": latency,
        "usable_latency_s": latency,
        "complete_latency_s": latency,
        "tokens": {"total": 100},
        "judge_input_sha256": "input",
        "judge_prompt_sha256": "judge",
        "translate_prompt_sha256": "translate",
        "results": [
            {
                "pmid": int(query_id[1:]),
                "score": 3,
                "relevance_pct": 90,
                "reason": "Pertinent.",
                "source": "both",
                "title": "Title",
                "abstract": "Abstract",
                "title_fr": "Titre",
                "abstract_fr": "Résumé",
                "journal": "Journal",
                "pub_year": 2026,
            }
        ],
        "error": None,
    }


def _run(experiment: dict, latency: float = 10.0, *, tier: str = "benchmark_full") -> dict:
    variant = variant_identity(experiment)
    ids = [f"q{index:02d}" for index in range(1, 19)]
    return {
        "schema_version": 1,
        "run_id": "replay-test",
        "run_kind": "replay",
        "complete": True,
        "expected_query_ids": ids,
        "database": "xmed_autoresearch",
        "corpus_scope": "full" if tier == "benchmark_full" else "recent",
        "corpus_fingerprint": "corpus",
        "machine_fingerprint": "machine",
        "protocol_fingerprint": "protocol",
        "source_artifact_sha256": "fixture",
        "benchmark_tier": tier,
        "experiment": experiment,
        **variant,
        "cases": [_case(query_id, latency) for query_id in ids],
    }


def test_variant_identity_excludes_labels_but_includes_behavior():
    baseline = variant_identity(_experiment())
    relabelled = variant_identity(_experiment(name="round-1", gate="auto"))
    changed = variant_identity(_experiment(max_local=100))

    assert baseline["variant_fingerprint"] == relabelled["variant_fingerprint"]
    assert baseline["variant_fingerprint"] != changed["variant_fingerprint"]


def test_protocol_fingerprint_excludes_provenance():
    protocol = {"benchmark": "autoresearch_xmed", "protocol_version": 2}
    first = make_manifest(protocol, {"created_at": "first", "git_commit": "a"})
    second = make_manifest(protocol, {"created_at": "second", "git_commit": "b"})

    assert first["protocol_fingerprint"] == second["protocol_fingerprint"]


def test_manifest_validation_detects_immutable_file_change(tmp_path):
    query_path = tmp_path / "experiments/autoresearch_xmed/queries.jsonl"
    query_path.parent.mkdir(parents=True)
    query_path.write_text('{"id":"q01"}\n')
    fixed = tmp_path / "fixed.py"
    fixed.write_text("VALUE = 1\n")
    files = ("experiments/autoresearch_xmed/queries.jsonl", "fixed.py")
    protocol = build_protocol(
        tmp_path,
        baseline_experiment=_experiment(),
        protocol_files=files,
    )
    manifest = make_manifest(protocol, {"created_at": "now"})

    validate_manifest(manifest, tmp_path, protocol_files=files)
    fixed.write_text("VALUE = 2\n")
    with pytest.raises(ManifestError, match="fixed.py"):
        validate_manifest(manifest, tmp_path, protocol_files=files)


def test_legacy_manifest_requires_explicit_smoke_mode(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "query_count": 18}))

    with pytest.raises(ManifestError, match="legacy"):
        load_manifest_identity(path)
    assert load_manifest_identity(path, allow_legacy_smoke=True)["legacy"] is True


def test_full_artifact_requires_v2_identity(tmp_path):
    run = _run(_experiment())
    run.pop("protocol_fingerprint")
    run.pop("variant_config")
    run.pop("variant_fingerprint")
    run["manifest_fingerprint"] = "legacy"
    path = tmp_path / "legacy-full.json"
    path.write_text(json.dumps(run))

    with pytest.raises(InvalidArtifact, match="legacy autorisé uniquement"):
        load_json(path)


def test_v2_artifact_rejects_tampered_variant(tmp_path):
    run = _run(_experiment())
    run["variant_config"]["max_local"] = 50
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(run))

    with pytest.raises(InvalidArtifact, match="identité de variante"):
        load_json(path)


def test_full_runs_with_different_variants_remain_comparable():
    baseline = _run(_experiment(), 10.0)
    candidate = _run(_experiment(max_local=100), 8.0)

    result = compare(baseline, candidate, "fidelity")

    assert result["verdict"] == "keep"
    comparability = next(
        gate for gate in result["gates"] if gate["name"] == "performance_measurement_comparability"
    )
    assert comparability["passed"] is True


def test_recent_runs_can_never_produce_final_keep():
    baseline = _run(_experiment(), 10.0, tier="smoke_recent")
    candidate = deepcopy(baseline)
    for case in candidate["cases"]:
        case["latency_s"] = 1.0
        case["usable_latency_s"] = 1.0
        case["complete_latency_s"] = 1.0

    result = compare(baseline, candidate, "fidelity")

    assert result["verdict"] == "ineligible"
