"""Produit le manifeste v2 immuable du protocole autoresearch X-Med."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from experiments.autoresearch_xmed.experiment import config
from experiments.autoresearch_xmed.manifest import build_protocol, make_manifest

ROOT = Path(__file__).resolve().parents[2]


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def build_manifest() -> dict:
    protocol = build_protocol(ROOT, baseline_experiment=config())
    provenance = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "git_dirty": bool(git_output("status", "--porcelain")),
    }
    return make_manifest(protocol, provenance)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"manifest: {args.out}")
    print(f"protocol_fingerprint: {manifest['protocol_fingerprint']}")
    print(f"git_commit: {manifest['provenance']['git_commit']}")
    print(f"queries: {manifest['protocol']['query_count']}")


if __name__ == "__main__":
    main()
