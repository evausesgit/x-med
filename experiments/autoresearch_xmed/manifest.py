"""Identités reproductibles du protocole et des variantes autoresearch X-Med.

Le protocole est immuable pendant les rounds. La configuration de la variante est
volontairement séparée : deux variantes comparables doivent partager le protocole,
pas nécessairement les mêmes knobs expérimentaux.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

PROTOCOL_FILES = (
    "pyproject.toml",
    "uv.lock",
    "app/api/search.py",
    "app/config.py",
    "app/models/__init__.py",
    "app/models/article.py",
    "app/services/codex_cli.py",
    "app/services/query_builder.py",
    "app/services/codex_judge.py",
    "app/services/pubmed_eutils.py",
    "app/services/translate.py",
    "experiments/autoresearch_xmed/__init__.py",
    "experiments/autoresearch_xmed/bench_esearch_cache.py",
    "experiments/autoresearch_xmed/bench_ncbi_parallel.py",
    "experiments/autoresearch_xmed/bench_ncbi_shared.py",
    "experiments/autoresearch_xmed/bench_prefilter.py",
    "experiments/autoresearch_xmed/bench_query_cache.py",
    "experiments/autoresearch_xmed/bench_translation_upsert.py",
    "experiments/autoresearch_xmed/build_annotation_pool.py",
    "experiments/autoresearch_xmed/build_judge_pool.py",
    "experiments/autoresearch_xmed/build_translation_comparison.py",
    "experiments/autoresearch_xmed/build_translation_pool.py",
    "experiments/autoresearch_xmed/esearch_cache.py",
    "experiments/autoresearch_xmed/judge_annotation_pool.py",
    "experiments/autoresearch_xmed/manifest.py",
    "experiments/autoresearch_xmed/optimizations.py",
    "experiments/autoresearch_xmed/prepare_bench.py",
    "experiments/autoresearch_xmed/prepare_bench_db.py",
    "experiments/autoresearch_xmed/program.md",
    "experiments/autoresearch_xmed/queries.jsonl",
    "experiments/autoresearch_xmed/query_cache.py",
    "experiments/autoresearch_xmed/run_fts_screen.py",
    "experiments/autoresearch_xmed/run_judge_screen.py",
    "experiments/autoresearch_xmed/run_live_baseline.py",
    "experiments/autoresearch_xmed/run_live_variant.py",
    "experiments/autoresearch_xmed/run_replay.py",
    "experiments/autoresearch_xmed/run_retrieval_screen.py",
    "experiments/autoresearch_xmed/run_translation_bilingual_judge.py",
    "experiments/autoresearch_xmed/run_translation_screen.py",
    "experiments/autoresearch_xmed/score.py",
    "experiments/autoresearch_xmed/score_fts.py",
    "experiments/autoresearch_xmed/score_judge.py",
    "experiments/autoresearch_xmed/score_retrieval.py",
    "experiments/autoresearch_xmed/score_translation_proxy.py",
    "experiments/autoresearch_xmed/trial_plan.json",
)

BEHAVIOR_KEYS = (
    "k_pubmed",
    "max_local",
    "judge_batch",
    "min_score",
    "rrf",
    "local_floor",
    "use_narrow_search",
    "reuse_query_builder",
    "reuse_esearch",
    "parallel_pubmed_fts",
    "parallel_ncbi_hydration",
    "reuse_hydrated_translation_input",
    "bulk_translation_upsert",
    "project_articles",
)

BASELINE_BEHAVIOR_CONFIG = {
    "k_pubmed": 20,
    "max_local": 200,
    "judge_batch": 50,
    "min_score": 2,
    "rrf": False,
    "local_floor": 0,
    "use_narrow_search": False,
    "reuse_query_builder": False,
    "reuse_esearch": False,
    "parallel_pubmed_fts": False,
    "parallel_ncbi_hydration": False,
    "reuse_hydrated_translation_input": False,
    "bulk_translation_upsert": False,
    "project_articles": False,
}


class ManifestError(ValueError):
    """Le manifeste ou la variante ne prouve pas l'identité déclarée."""


def canonical_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"valeur non canonique: {exc}") from exc
    return rendered.encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def behavior_config(experiment: dict) -> dict:
    if not isinstance(experiment, dict):
        raise ManifestError("configuration expérimentale non objet")
    missing = sorted(set(BEHAVIOR_KEYS) - set(experiment))
    unknown = sorted(set(experiment) - set(BEHAVIOR_KEYS) - {"name", "gate"})
    if missing or unknown:
        raise ManifestError(f"knobs invalides: missing={missing}, unknown={unknown}")

    out = {key: experiment[key] for key in BEHAVIOR_KEYS}
    for key in ("k_pubmed", "max_local", "judge_batch", "min_score", "local_floor"):
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ManifestError(f"{key} doit être un entier positif ou nul")
    if out["k_pubmed"] == 0 or out["judge_batch"] == 0:
        raise ManifestError("k_pubmed et judge_batch doivent être strictement positifs")
    for key in set(BEHAVIOR_KEYS) - {
        "k_pubmed",
        "max_local",
        "judge_batch",
        "min_score",
        "local_floor",
    }:
        if not isinstance(out[key], bool):
            raise ManifestError(f"{key} doit être booléen")
    if "name" in experiment and (
        not isinstance(experiment["name"], str) or not experiment["name"].strip()
    ):
        raise ManifestError("name doit être une chaîne non vide")
    if experiment.get("gate") not in (None, "fidelity", "clinical", "auto"):
        raise ManifestError("gate invalide")
    return out


def variant_identity(experiment: dict, experiment_path: Path | None = None) -> dict:
    config = behavior_config(experiment)
    identity = {
        "variant_config": config,
        "variant_fingerprint": fingerprint(config),
    }
    if experiment_path is not None:
        identity["experiment_file_sha256"] = file_sha256(experiment_path)
    return identity


def build_protocol(
    root: Path = ROOT,
    *,
    baseline_experiment: dict,
    protocol_files: tuple[str, ...] = PROTOCOL_FILES,
) -> dict:
    baseline = behavior_config(baseline_experiment)
    if baseline != BASELINE_BEHAVIOR_CONFIG:
        raise ManifestError(
            "le manifeste doit être généré avec la configuration baseline pré-enregistrée"
        )
    files = {name: file_sha256(root / name) for name in protocol_files}
    query_path = root / "experiments/autoresearch_xmed/queries.jsonl"
    query_count = sum(1 for line in query_path.read_text().splitlines() if line.strip())
    return {
        "benchmark": "autoresearch_xmed",
        "protocol_version": 2,
        "files_sha256": files,
        "query_count": query_count,
        "baseline_behavior_config": baseline,
        "autoresearch_upstream": {
            "url": "https://github.com/karpathy/autoresearch",
            "commit": "228791fb499afffb54b46200aca536f79142f117",
        },
        "safety": {
            "production_http": False,
            "notifications": False,
            "database_mode": "isolated_autoresearch_clone_read_only",
        },
    }


def make_manifest(protocol: dict, provenance: dict) -> dict:
    return {
        "schema_version": 2,
        "protocol": protocol,
        "protocol_fingerprint": fingerprint(protocol),
        "provenance": provenance,
    }


def validate_manifest(
    data: dict,
    root: Path = ROOT,
    *,
    protocol_files: tuple[str, ...] = PROTOCOL_FILES,
) -> dict:
    if data.get("schema_version") != 2 or not isinstance(data.get("protocol"), dict):
        raise ManifestError("manifeste v2 requis")
    protocol = data["protocol"]
    expected_fingerprint = fingerprint(protocol)
    if data.get("protocol_fingerprint") != expected_fingerprint:
        raise ManifestError("protocol_fingerprint incohérent")
    if protocol.get("benchmark") != "autoresearch_xmed" or protocol.get("protocol_version") != 2:
        raise ManifestError("identité de protocole invalide")
    if protocol.get("baseline_behavior_config") != BASELINE_BEHAVIOR_CONFIG:
        raise ManifestError("configuration baseline du protocole invalide")

    recorded = protocol.get("files_sha256")
    if not isinstance(recorded, dict) or set(recorded) != set(protocol_files):
        raise ManifestError("inventaire des fichiers immuables incomplet")
    mismatches = [
        name
        for name in protocol_files
        if not (root / name).is_file() or file_sha256(root / name) != recorded[name]
    ]
    if mismatches:
        raise ManifestError("fichiers immuables divergents: " + ", ".join(mismatches))
    return data


def load_manifest(path: Path, root: Path = ROOT) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"manifeste illisible: {path}") from exc
    return validate_manifest(data, root)


def load_manifest_identity(
    path: Path,
    root: Path = ROOT,
    *,
    allow_legacy_smoke: bool = False,
) -> dict:
    """Charge un v2 vérifié, ou un v1 explicitement borné au smoke récent."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"manifeste illisible: {path}") from exc
    if data.get("schema_version") == 2:
        validate_manifest(data, root)
        return {
            "legacy": False,
            "protocol_fingerprint": data["protocol_fingerprint"],
            "baseline_behavior_config": data["protocol"]["baseline_behavior_config"],
            "query_count": int(data["protocol"]["query_count"]),
        }
    if data.get("schema_version") == 1 and allow_legacy_smoke:
        return {
            "legacy": True,
            "legacy_manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "query_count": int(data.get("query_count", 0)),
        }
    raise ManifestError("un manifeste legacy n'est autorisé que pour un smoke récent")


def validate_variant_identity(run: dict) -> bool:
    config = run.get("variant_config")
    if not isinstance(config, dict):
        return False
    try:
        canonical = behavior_config(config)
    except ManifestError:
        return False
    return canonical == config and run.get("variant_fingerprint") == fingerprint(config)
