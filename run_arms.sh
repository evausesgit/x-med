#!/bin/bash
# Écran du juge, 4 bras × 3 répétitions, sur le pool de la recherche
# « floppy eyelid syndrome / glaucome à pression normale » du 05/08 (50 abstracts,
# 0 retenu en production). Un seul facteur change par bras.
#
#   A  baseline        réglage de production (gpt-5.6-terra / medium)
#   B  pr73            = PR #73 : retour gpt-5.4 / high, prompt inchangé
#   C  no_evidence     retire « niveau de preuve N » du payload (commit 4f6de6b, 23/07)
#   D  neutral         remplace les 3 exemples floppy-eyelid du prompt par des neutres
set -u
export PATH="$HOME/.npm-global/bin:$HOME/.hermes/node/bin:$PATH"
cd /home/jack/projects/x-med/.claude/worktrees/diag-juge-rejeu
mkdir -p artifacts

run() {
  name=$1
  shift
  echo "=== $name === début $(date +%H:%M:%S)"
  PYTHONPATH=. uv run python -m experiments.autoresearch_xmed.run_judge_screen \
    pool_fes.jsonl --out "artifacts/judge_${name}.json" --repetitions 3 "$@" 2>&1 | tail -3
  echo "--- $name fin $(date +%H:%M:%S)"
}

run A_baseline
run B_pr73 --model gpt-5.4 --reasoning high
run C_no_evidence --metadata-mode no_evidence
run D_neutral --prompt-style neutral
echo "TOUT TERMINE $(date +%H:%M:%S)"
