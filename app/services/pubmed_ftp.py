"""Découverte et vérification des fichiers PubMed locaux.

Le téléchargement lui-même est assuré par data/pubmed/download_corpus.sh.
Ce module liste les fichiers présents et vérifie leur intégrité MD5.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.config import settings

_FILE_RE = re.compile(r"pubmed\d+n(\d+)\.xml\.gz$")


def list_local_files() -> list[Path]:
    """Tous les .xml.gz sous DATA_DIR (baseline + updatefiles), triés par numéro."""
    root = Path(settings.data_dir)
    files = list(root.glob("**/*.xml.gz"))

    def num(p: Path) -> int:
        m = _FILE_RE.search(p.name)
        return int(m.group(1)) if m else 0

    return sorted(files, key=num)


def md5sum(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify_md5(path: Path) -> bool:
    """Vérifie le .xml.gz contre son .md5 voisin (format NLM : 'MD5(file)= hash')."""
    md5_file = path.with_suffix(path.suffix + ".md5")
    if not md5_file.exists():
        return True  # pas de référence → on ne bloque pas
    expected = md5_file.read_text().strip().split("=")[-1].strip()
    return md5sum(path) == expected
