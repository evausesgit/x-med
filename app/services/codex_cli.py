"""Exécution centralisée de `codex exec`, avec capture de l'usage de tokens.

Les 3 appels codex du mode « PubMed + codex » (construction de requête, jugement,
traduction) passent par `run_codex()`. On lance `codex exec --json` (événements
JSONL sur stdout, dont `turn.completed` qui porte l'usage) en plus de
`--output-schema`/`-o` (résultat structuré écrit dans un fichier). On renvoie
`(data, CodexUsage)`.

Chaque service traduit `CodexCliError` en son erreur métier
(QueryBuildError / JudgeError / TranslateError) ; `query_builder.is_usage_limit`
reste utilisable sur le message (il embarque la fin du stderr).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.services.search_cancel import SearchCancelled, current_search, kill_proc_tree


@dataclass
class CodexUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


class CodexCliError(RuntimeError):
    """codex introuvable, non authentifié, trop lent, ou sortie illisible."""


def _parse_usage(stdout: bytes | None) -> CodexUsage:
    """Lit l'event `turn.completed` (le dernier) pour en extraire l'usage."""
    usage = CodexUsage()
    for line in (stdout or b"").decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        if evt.get("type") == "turn.completed" and isinstance(evt.get("usage"), dict):
            u = evt["usage"]
            usage = CodexUsage(
                input_tokens=int(u.get("input_tokens", 0) or 0),
                cached_input_tokens=int(u.get("cached_input_tokens", 0) or 0),
                output_tokens=int(u.get("output_tokens", 0) or 0),
                reasoning_output_tokens=int(u.get("reasoning_output_tokens", 0) or 0),
            )
    return usage


def run_codex(
    prompt: str,
    schema: dict,
    timeout: int,
    model: str | None = None,
    reasoning: str | None = None,
) -> tuple[dict, CodexUsage]:
    """Lance `codex exec` avec un schéma JSON imposé. Retourne (data, usage).

    `model` et `reasoning` remplacent les défauts (settings.codex_model /
    settings.codex_reasoning) pour cet appel — la traduction tourne sur un
    modèle moins cher en raisonnement bas. L'effort est TOUJOURS passé
    explicitement : sinon codex hériterait du config.toml du CODEX_HOME
    ambiant, qui n'appartient pas à x-med.

    Lève `CodexCliError` si codex échoue / sortie illisible, `SearchCancelled` si
    le process a été tué par le bouton « Arrêter la recherche » (jeton d'annulation
    de la recherche courante, cf. `search_cancel.current_search`).
    """
    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        out_path = Path(td) / "out.json"
        schema_path.write_text(json.dumps(schema))
        cmd = [
            settings.codex_bin, "exec", "--json", "--skip-git-repo-check",
            "--ephemeral", "-s", "read-only", "--color", "never",
            "--output-schema", str(schema_path), "-o", str(out_path),
        ]
        if model or settings.codex_model:
            cmd += ["-m", model or settings.codex_model]
        effort = reasoning or settings.codex_reasoning
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        cmd.append(prompt)
        # Popen (et non subprocess.run) : le bouton « Arrêter la recherche » doit
        # pouvoir tuer le process en plein vol via l'état d'annulation partagé.
        cancel_state = current_search.get()
        try:
            # stdin fermé : sinon `codex exec` se bloque en attente d'entrée.
            # start_new_session : codex et ses enfants forment un groupe qu'une
            # annulation (ou un timeout) peut tuer d'un bloc — tuer le seul parent
            # laisserait des enfants tenir les pipes et bloquerait communicate().
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
            )
        except FileNotFoundError as e:
            raise CodexCliError(f"codex introuvable ({settings.codex_bin})") from e
        if cancel_state is not None:
            cancel_state.attach_proc(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            kill_proc_tree(proc)
            proc.communicate()
            raise CodexCliError(f"codex timeout ({timeout}s)") from e
        finally:
            if cancel_state is not None:
                cancel_state.detach_proc()
        if cancel_state is not None and cancel_state.cancelled:
            raise SearchCancelled
        if proc.returncode != 0:
            tail = (stderr or b"").decode(errors="replace")[-300:]
            raise CodexCliError(f"codex a échoué : {tail}")
        try:
            data = json.loads(out_path.read_text())
        except Exception as e:  # fichier vide / JSON cassé
            raise CodexCliError(f"sortie codex illisible : {e}") from e

    return data, _parse_usage(stdout)
