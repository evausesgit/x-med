"""Mise à jour quotidienne PubMed : télécharge les nouveaux `updatefiles` NLM
puis les ingère dans `articles` (suivi `ftp_state`).

À lancer par cron une fois par jour (voir crontab : 05:00 UTC). Idempotent :
- le download saute les fichiers déjà présents et valides (MD5) et s'arrête au
  premier numéro absent du serveur (les updatefiles sont séquentiels, sans trou) ;
- l'ingestion saute les fichiers déjà dans `ftp_state` ;
- borné aux updatefiles (n° >= UPDATE_MIN) : ne touche jamais la baseline.

Cela couvre aussi le rattrapage : tout updatefile présent localement mais pas
encore ingéré (ex. lacune après une interruption) sera ingéré au prochain passage.

Usage :
    uv run python -m scripts.pubmed_daily
    uv run python -m scripts.pubmed_daily --no-download    # ingestion seule
    uv run python -m scripts.pubmed_daily --max-new 50     # plafonne le download
    uv run python -m scripts.pubmed_daily --no-ingest      # download seul

Limite connue : au changement de baseline annuelle (déc.), NLM réinitialise les
updatefiles avec un nouveau préfixe (`pubmed27n…`). Ce script détecte le préfixe
depuis les fichiers locaux ; le passage à la nouvelle année annuelle reste une
opération manuelle (re-télécharger la baseline via data/pubmed/download_corpus.sh).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

from app.config import settings
from app.services.pubmed_ftp import md5sum
from scripts.load_baseline import ingest_local_files

UPDATE_URL = "https://ftp.ncbi.nlm.nih.gov/pubmed/updatefiles"
UPDATE_MIN = 1335  # premier updatefile de la baseline 2026 (avant = baseline)
_NAME_RE = re.compile(r"^(pubmed\d+n)(\d+)\.xml\.gz$")


def _updatefiles_dir() -> Path:
    d = Path(settings.data_dir) / "updatefiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _highest_local(dir_: Path) -> tuple[str | None, int]:
    """(préfixe, plus grand numéro) parmi les updatefiles locaux."""
    prefix, hi = None, 0
    for p in dir_.glob("*.xml.gz"):
        m = _NAME_RE.match(p.name)
        if m and int(m.group(2)) > hi:
            prefix, hi = m.group(1), int(m.group(2))
    return prefix, hi


def _download_one(prefix: str, num: int, dest: Path) -> str:
    """Télécharge un updatefile + son .md5. Renvoie 'ok' | 'missing' | 'badmd5'."""
    fname = f"{prefix}{num:04d}.xml.gz"
    r = requests.get(f"{UPDATE_URL}/{fname}", timeout=180)
    if r.status_code == 404:
        return "missing"
    r.raise_for_status()
    (dest / fname).write_bytes(r.content)

    rm = requests.get(f"{UPDATE_URL}/{fname}.md5", timeout=60)
    if rm.status_code == 200:
        (dest / f"{fname}.md5").write_bytes(rm.content)
        expected = rm.text.strip().split("=")[-1].strip()
        if md5sum(dest / fname) != expected:
            return "badmd5"
    return "ok"


def download_new(max_new: int = 200) -> int:
    """Télécharge les updatefiles plus récents que le plus grand local. Renvoie le nb obtenu."""
    dest = _updatefiles_dir()
    prefix, hi = _highest_local(dest)
    if prefix is None:
        print("Aucun updatefile local : lance d'abord data/pubmed/download_corpus.sh.")
        return 0

    print(f"Plus grand updatefile local : {prefix}{hi:04d}. Recherche des suivants…")
    got = 0
    num = hi + 1
    while got < max_new:
        status = _download_one(prefix, num, dest)
        if status == "missing":
            print(f"  {prefix}{num:04d} absent du serveur → fin.")
            break
        if status == "badmd5":
            # 1 nouvel essai puis on s'arrête pour ne pas ingérer un fichier corrompu
            print(f"  [retry] MD5 invalide {prefix}{num:04d}")
            if _download_one(prefix, num, dest) != "ok":
                print(f"  [FAIL] MD5 invalide {prefix}{num:04d} → arrêt du download.")
                break
        print(f"  [ok] {prefix}{num:04d}.xml.gz")
        got += 1
        num += 1

    print(f"{got} nouveau(x) fichier(s) téléchargé(s).")
    return got


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true", help="ne pas télécharger, ingérer seulement")
    ap.add_argument("--no-ingest", action="store_true", help="ne pas ingérer, télécharger seulement")
    ap.add_argument("--max-new", type=int, default=200, help="nb max de fichiers téléchargés par run")
    args = ap.parse_args()

    if not args.no_download:
        download_new(max_new=args.max_new)
    if not args.no_ingest:
        ingest_local_files(from_num=UPDATE_MIN)


if __name__ == "__main__":
    main()
