#!/bin/bash
# Désimbrication modèle / effort. Le bras B du premier run changeait les deux à la
# fois (terra/medium → gpt-5.4/high), comme la PR #73. Ces deux bras complètent le
# carré : à effort égal on lit le modèle, à modèle égal on lit l'effort.
#
#   E  gpt-5.4 / medium   ← modèle seul (face à A = terra/medium)
#   F  terra   / high     ← effort seul (face à A = terra/medium)
set -u
export PATH="$HOME/.npm-global/bin:$HOME/.hermes/node/bin:$PATH"
cd /home/jack/projects/x-med/.claude/worktrees/diag-juge-rejeu

run() {
  name=$1
  shift
  echo "=== $name === début $(date +%H:%M:%S)"
  PYTHONPATH=. uv run python -m experiments.autoresearch_xmed.run_judge_screen \
    pool_fes.jsonl --out "artifacts/judge_${name}.json" --repetitions 3 "$@" 2>&1 | tail -3
  echo "--- $name fin $(date +%H:%M:%S)"
}

run E_54_medium --model gpt-5.4 --reasoning medium
run F_terra_high --reasoning high
echo "TOUT TERMINE $(date +%H:%M:%S)"
