from pathlib import Path

import pytest

from experiments.autoresearch_xmed.manifest import (
    BASELINE_BEHAVIOR_CONFIG,
    variant_identity,
)
from experiments.autoresearch_xmed.run_live_baseline import (
    HERE,
    _collection_contract,
)
from experiments.autoresearch_xmed import run_live_variant


def _experiment(**changes):
    value = {
        "name": "test",
        "gate": "fidelity",
        **BASELINE_BEHAVIOR_CONFIG,
    }
    value.update(changes)
    return value


def _manifest(*, legacy: bool = False) -> dict:
    value = {
        "legacy": legacy,
        "query_count": 18,
    }
    if legacy:
        value["legacy_manifest_sha256"] = "legacy"
    else:
        value.update(
            {
                "protocol_fingerprint": "protocol",
                "baseline_behavior_config": BASELINE_BEHAVIOR_CONFIG,
            }
        )
    return value


def _rows() -> list[dict]:
    return [{"id": f"q{index:02d}"} for index in range(1, 19)]


def _contract(**changes) -> str:
    values = {
        "run_role": "baseline",
        "manifest": _manifest(),
        "experiment": _experiment(),
        "corpus_scope": "full",
        "selected": None,
        "queries_path": HERE / "queries.jsonl",
        "rows": _rows(),
    }
    values.update(changes)
    return _collection_contract(**values)


def test_baseline_runner_rejects_candidate_behavior():
    with pytest.raises(SystemExit, match="configuration baseline"):
        _contract(experiment=_experiment(max_local=100))


def test_variant_runner_accepts_distinct_behavior_with_distinct_identity():
    baseline = variant_identity(_experiment())
    candidate_experiment = _experiment(max_local=100)
    candidate = variant_identity(candidate_experiment)

    tier = _contract(run_role="variant", experiment=candidate_experiment)

    assert tier == "benchmark_full"
    assert candidate["variant_fingerprint"] != baseline["variant_fingerprint"]


def test_variant_runner_rejects_legacy_even_for_recent_smoke():
    with pytest.raises(SystemExit, match="manifeste v2"):
        _contract(
            run_role="variant",
            manifest=_manifest(legacy=True),
            corpus_scope="recent",
            rows=[{"id": "q01"}],
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"selected": {"q01"}}, "canonique complet"),
        ({"queries_path": Path("custom.jsonl")}, "canonique complet"),
        ({"rows": _rows()[:-1]}, "couverture incomplète"),
        (
            {"rows": [*_rows()[:-1], {"id": "q99"}]},
            "couverture incomplète",
        ),
        ({"manifest": _manifest(legacy=True)}, "smoke récent"),
    ],
)
def test_full_contract_is_closed(changes, message):
    with pytest.raises(SystemExit, match=message):
        _contract(**changes)


def test_recent_v2_is_explicitly_non_promotable_smoke():
    assert _contract(corpus_scope="recent", rows=[{"id": "q01"}]) == "smoke_recent"


def test_variant_entrypoint_dispatches_to_shared_collector(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_live_variant,
        "shared_main",
        lambda *, run_role: calls.append(run_role),
    )

    run_live_variant.main()

    assert calls == ["variant"]
