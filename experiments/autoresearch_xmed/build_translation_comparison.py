"""Construit un comparatif A/B aveugle depuis deux screens de traduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from experiments.autoresearch_xmed.build_translation_pool import text_features
from experiments.autoresearch_xmed.run_translation_screen import load_pool


class TranslationComparisonError(ValueError):
    """Les sources ne permettent pas une comparaison aveugle démontrable."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_screen(path: Path, source_pool_sha256: str, repetition: int) -> tuple[dict, dict]:
    try:
        screen = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationComparisonError(f"screen illisible: {path}") from exc
    if screen.get("artifact_type") != "translation_screen" or screen.get("complete") is not True:
        raise TranslationComparisonError(f"screen complet requis: {path}")
    if screen.get("source_pool_sha256") != source_pool_sha256:
        raise TranslationComparisonError(f"pool source différent: {path}")
    if not screen.get("config_fingerprint") or not screen.get("runner_sha256"):
        raise TranslationComparisonError(f"fingerprints absents: {path}")
    repetitions = screen.get("repetitions")
    if not isinstance(repetitions, list) or not 1 <= repetition <= len(repetitions):
        raise TranslationComparisonError(f"répétition {repetition} absente: {path}")
    rows = repetitions[repetition - 1].get("translations")
    if not isinstance(rows, list):
        raise TranslationComparisonError(f"translations absentes: {path}")
    parsed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TranslationComparisonError(f"traduction non objet: {path}")
        item_id = row.get("item_id")
        pmid = row.get("pmid")
        if not isinstance(item_id, str) or not item_id or not isinstance(pmid, int):
            raise TranslationComparisonError(f"identité traduction invalide: {path}")
        if item_id in parsed:
            raise TranslationComparisonError(f"item_id dupliqué dans {path}: {item_id}")
        if not isinstance(row.get("title_fr"), str) or not isinstance(row.get("abstract_fr"), str):
            raise TranslationComparisonError(f"texte traduit invalide pour {item_id}")
        parsed[item_id] = {
            "pmid": pmid,
            "title_fr": row["title_fr"],
            "abstract_fr": row["abstract_fr"],
        }
    expected = screen.get("expected_item_ids")
    if not isinstance(expected, list) or expected != list(parsed):
        raise TranslationComparisonError(f"bijection item_id invalide: {path}")
    return screen, parsed


def _private_stratum(item: dict) -> dict:
    features = text_features(item["abstract"], None)
    technical = any(
        features[key]
        for key in ("numbers", "percent", "confidence_interval", "units", "acronyms", "negation")
    )
    return {
        "length": features["length"],
        "risk": "technical" if technical else "plain",
        "combined": f"{features['length']}:{'technical' if technical else 'plain'}",
    }


def build(
    pool_path: Path,
    baseline_path: Path,
    candidate_path: Path,
    *,
    seed: int = 20260731,
    baseline_repetition: int = 1,
    candidate_repetition: int = 1,
) -> tuple[list[dict], dict]:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TranslationComparisonError("seed doit être entier")
    pool_bytes = pool_path.read_bytes()
    source_pool_sha256 = _sha256_bytes(pool_bytes)
    items = load_pool(pool_path)
    baseline_screen, baseline = _load_screen(baseline_path, source_pool_sha256, baseline_repetition)
    candidate_screen, candidate = _load_screen(
        candidate_path, source_pool_sha256, candidate_repetition
    )
    expected_ids = [item["item_id"] for item in items]
    if set(baseline) != set(expected_ids) or set(candidate) != set(expected_ids):
        raise TranslationComparisonError("screens sans bijection avec le pool aveugle")

    blind_items = []
    private_items = {}
    for item in items:
        item_id = item["item_id"]
        base = baseline[item_id]
        cand = candidate[item_id]
        if base["pmid"] != item["pmid"] or cand["pmid"] != item["pmid"]:
            raise TranslationComparisonError(f"PMID incohérent pour {item_id}")
        digest = hashlib.sha256(f"{seed}:{item_id}".encode()).digest()
        baseline_label = "A" if digest[0] % 2 == 0 else "B"
        candidate_label = "B" if baseline_label == "A" else "A"
        by_label = {baseline_label: base, candidate_label: cand}
        blind_items.append(
            {
                "item_id": item_id,
                "query_id": item["query_id"],
                "pmid": item["pmid"],
                "source": {"title": item["title"], "abstract": item["abstract"]},
                "options": {
                    label: {
                        "title_fr": by_label[label]["title_fr"],
                        "abstract_fr": by_label[label]["abstract_fr"],
                    }
                    for label in ("A", "B")
                },
            }
        )
        private_items[item_id] = {
            "pmid": item["pmid"],
            "labels": {"baseline": baseline_label, "candidate": candidate_label},
            "stratum": _private_stratum(item),
        }

    blind_value = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in blind_items
    ).encode()
    key = {
        "schema_version": 1,
        "artifact_type": "translation_comparison_private_key",
        "seed": seed,
        "blind_pool_sha256": _sha256_bytes(blind_value),
        "source_pool_sha256": source_pool_sha256,
        "sources": {
            "pool": {"path": str(pool_path.resolve()), "sha256": source_pool_sha256},
            "baseline": {
                "path": str(baseline_path.resolve()),
                "sha256": _sha256_bytes(baseline_path.read_bytes()),
                "config_fingerprint": baseline_screen["config_fingerprint"],
                "runner_sha256": baseline_screen["runner_sha256"],
                "repetition": baseline_repetition,
            },
            "candidate": {
                "path": str(candidate_path.resolve()),
                "sha256": _sha256_bytes(candidate_path.read_bytes()),
                "config_fingerprint": candidate_screen["config_fingerprint"],
                "runner_sha256": candidate_screen["runner_sha256"],
                "repetition": candidate_repetition,
            },
        },
        "items": private_items,
    }
    return blind_items, key


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_outputs(blind_path: Path, key_path: Path, items: list[dict], key: dict) -> None:
    if blind_path.resolve() == key_path.resolve():
        raise TranslationComparisonError("blind-out et key-out doivent être distincts")
    blind_value = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items
    ).encode()
    if _sha256_bytes(blind_value) != key.get("blind_pool_sha256"):
        raise TranslationComparisonError("fingerprint du pool aveugle incohérent")
    _atomic_write(blind_path, blind_value)
    _atomic_write(key_path, (json.dumps(key, ensure_ascii=False, indent=2) + "\n").encode())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--baseline-repetition", type=int, default=1)
    parser.add_argument("--candidate-repetition", type=int, default=1)
    parser.add_argument("--blind-out", type=Path, required=True)
    parser.add_argument("--key-out", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        items, key = build(
            args.pool,
            args.baseline,
            args.candidate,
            seed=args.seed,
            baseline_repetition=args.baseline_repetition,
            candidate_repetition=args.candidate_repetition,
        )
        write_outputs(args.blind_out, args.key_out, items, key)
    except (OSError, TranslationComparisonError, ValueError) as exc:
        raise SystemExit(f"REFUS: {exc}") from exc
    print(json.dumps({"items": len(items), "blind_pool_sha256": key["blind_pool_sha256"]}))


if __name__ == "__main__":
    main()
