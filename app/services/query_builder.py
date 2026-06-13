"""Construction d'une requête PubMed à partir d'une question clinique FR.

Plutôt qu'une clé API, on shelle le CLI `codex` (`codex exec`) avec
`--output-schema` pour obtenir une sortie JSON structurée. C'est l'étape clé du
mode « PubMed d'abord » : sans elle, envoyer la question française brute à PubMed
(lexical/MeSH) reproduit les travers du moteur lexical (mots banals qui dominent).

Si codex est absent, non authentifié, ou trop lent, on lève QueryBuildError et
l'appelant retombe sur la question brute.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pubmed_query": {"type": "string"},
        "mesh_terms": {"type": "array", "items": {"type": "string"}},
        "keywords_en": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["pubmed_query", "mesh_terms", "keywords_en"],
}

_PROMPT = (
    "Tu es expert en recherche bibliographique biomédicale (PubMed). "
    "Transforme la question clinique française suivante en UNE requête PubMed "
    "efficace et ciblée : traduis les concepts en anglais ; ajoute les synonymes "
    "utiles (noms de molécules, codes de développement, variantes) ; utilise les "
    "tags [MeSH] et [tiab] et les opérateurs AND/OR ; reste précis sans "
    "sur-élargir. Question : {q}. Réponds uniquement via le schéma JSON imposé."
)


class QueryBuildError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def build_pubmed_query(question: str, timeout: int = 180) -> dict:
    """Retourne {pubmed_query, mesh_terms, keywords_en}. Lève QueryBuildError sinon."""
    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        out_path = Path(td) / "out.json"
        schema_path.write_text(json.dumps(_SCHEMA))
        cmd = [
            settings.codex_bin, "exec", "--skip-git-repo-check", "--ephemeral",
            "-s", "read-only", "--color", "never",
            "--output-schema", str(schema_path), "-o", str(out_path),
        ]
        if settings.codex_model:
            cmd += ["-m", settings.codex_model]
        cmd.append(_PROMPT.format(q=question))
        try:
            # stdin fermé : sinon `codex exec` se bloque en attente d'entrée.
            subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout, check=True,
            )
        except FileNotFoundError as e:
            raise QueryBuildError(f"codex introuvable ({settings.codex_bin})") from e
        except subprocess.TimeoutExpired as e:
            raise QueryBuildError(f"codex timeout ({timeout}s)") from e
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or b"").decode(errors="replace")[-300:]
            raise QueryBuildError(f"codex a échoué : {tail}") from e
        try:
            data = json.loads(out_path.read_text())
        except Exception as e:  # fichier vide / JSON cassé
            raise QueryBuildError(f"sortie codex illisible : {e}") from e
    if not data.get("pubmed_query"):
        raise QueryBuildError("pubmed_query vide")
    data.setdefault("mesh_terms", [])
    data.setdefault("keywords_en", [])
    return data
