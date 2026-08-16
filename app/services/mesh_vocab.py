"""Validation des descripteurs MeSH produits par codex contre le thésaurus réel.

**Pourquoi ce module existe.** Un LLM génère du texte plausible ; il ne consulte
pas le thésaurus MeSH. Mesuré sur 56 requêtes générées (août 2026) : *16 % des
termes MeSH émis n'existent pas* comme descripteurs. Et PubMed ne signale pas
l'erreur — une clause `"Photodynamic Therapy"[MeSH]` (inventé) renvoie
**silencieusement 0 résultat**, là où `"Photochemotherapy"[MeSH]` (le vrai nom)
en renvoie 32 408. Comme les clauses sont en OU dans leur bloc, les synonymes
`[tiab]` sauvent la requête : on ne voit jamais d'erreur, on perd juste un pan de
littérature. Autres cas mesurés : `Adjuvant Therapy` 0 vs `Chemotherapy,
Adjuvant` 51 053 ; `Vitamin K Antagonists` 0 vs `Anticoagulants` 105 029.

Deux pièges récurrents, tous deux traités ici :

- **le terme d'entrée au lieu du nom du descripteur** — le modèle écrit ce qu'un
  médecin dit. `"Severe Acute Respiratory Syndrome Coronavirus 2"[MeSH]` = 0,
  alors que le nom officiel est simplement `SARS-CoV-2` (211 743) ;
- **les médicaments récents ne sont pas des descripteurs** mais des *concepts
  supplémentaires*, une autre catégorie : aflibercept `[MeSH]` = 0 contre 4 276
  en `[tiab]`. Le terme est juste, le tag est faux.

Le remède est le même dans les deux cas : **ce qui n'est pas un descripteur
officiel n'a pas droit au tag `[MeSH]`** — on le rétrograde en `[tiab]`, qui
retrouve le terme dans le titre et le résumé. Une clause absente vaut mieux
qu'une clause qui rend 0 en donnant l'illusion d'une couverture.

Le thésaurus n'est pas téléchargé : la table `mesh_descriptors` est alimentée à
l'ingestion à partir des articles PubMed eux-mêmes (`tasks/parse_articles.py`),
soit ~30 600 descripteurs — la quasi-totalité du MeSH, et par construction
uniquement ceux qui peuvent matcher quelque chose dans le corpus.
"""

from __future__ import annotations

import logging
import re
import threading

from sqlalchemy import select

log = logging.getLogger(__name__)

# Index {clé normalisée -> nom officiel}, chargé une fois pour toutes. ~30 600
# entrées ≈ 3 Mo : négligeable, et évite un aller-retour SQL par recherche.
_INDEX: dict[str, str] | None = None
_LOCK = threading.Lock()

_TAG = re.compile(r"\s*\[[^\]]*\]\s*$")  # « Heart Failure[MeSH] »
_SPACES = re.compile(r"\s+")


def _key(term: str) -> str:
    """Clé de comparaison : casse, espaces et espaces autour des virgules ignorés.

    On garde la virgule (elle porte l'inversion MeSH : « Chemotherapy, Adjuvant »)
    mais pas son espacement, pour que « Chemotherapy,Adjuvant » tombe juste.
    """
    return _SPACES.sub(" ", term.strip().lower()).replace(" ,", ",").replace(", ", ",")


def load_index(session) -> dict[str, str]:
    """Charge (une seule fois) l'index des descripteurs officiels."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _LOCK:
        if _INDEX is None:  # re-test sous verrou : deux recherches simultanées
            from app.models import MeshDescriptor

            names = session.scalars(select(MeshDescriptor.name)).all()
            _INDEX = {_key(n): n for n in names if n}
            log.info("Thésaurus MeSH chargé : %d descripteurs", len(_INDEX))
    return _INDEX


def reset_index() -> None:
    """Vide le cache (tests, et rechargement après une ingestion massive)."""
    global _INDEX
    with _LOCK:
        _INDEX = None


def _variants(term: str):
    """Réécritures à essayer, de la plus fidèle à la plus permissive.

    Les trois règles couvrent 10 des 27 termes fautifs distincts observés ; le
    reste n'est pas réparable par le code (vrais synonymes, molécules) et part
    en `[tiab]`.
    """
    t = _SPACES.sub(" ", term.strip())
    yield t

    # 1. tag collé par le modèle : « Heart Failure[MeSH] » → « Heart Failure »
    stripped = _TAG.sub("", t).strip()
    if stripped and stripped != t:
        yield stripped
        t = stripped

    # 2. qualificatif MeSH : « Papillomavirus Infections/diagnosis » → le
    #    descripteur seul. Le qualificatif restreint le sujet ; le perdre élargit
    #    un peu, ce qui est le bon sens quand l'alternative est 0 résultat.
    if "/" in t:
        head = t.split("/", 1)[0].strip()
        if head:
            yield head
            t = head

    # 3. inversion MeSH : le thésaurus range « Chemotherapy, Adjuvant », le
    #    modèle écrit « Adjuvant Chemotherapy ». On essaie chaque coupure.
    if "," not in t:
        words = t.split(" ")
        for i in range(1, len(words)):
            yield " ".join(words[i:]) + ", " + " ".join(words[:i])


def resolve(terms, session) -> tuple[list[str], list[str]]:
    """Trie les termes MeSH proposés en (descripteurs officiels, à rétrograder).

    Retourne ``(mesh, tiab)`` : ``mesh`` contient les noms **officiels** (donc
    corrigés à la casse et à l'orthographe du thésaurus, ce qui est aussi un
    facteur de déterminisme : plusieurs graphies convergent vers une seule),
    ``tiab`` les termes que l'appelant doit chercher en plein texte.

    Si le thésaurus est indisponible (base injoignable), on ne rétrograde rien :
    une panne d'infrastructure ne doit pas changer le sens de la recherche.
    """
    try:
        index = load_index(session)
    except Exception as e:  # noqa: BLE001 — jamais bloquant pour une recherche
        log.warning("Thésaurus MeSH indisponible (%s) — validation sautée", e)
        return [t.strip() for t in terms or [] if t and t.strip()], []

    mesh: list[str] = []
    tiab: list[str] = []
    seen: set[str] = set()
    for raw in terms or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        official = next((index[k] for v in _variants(raw) if (k := _key(v)) in index), None)
        target, value = (mesh, official) if official else (tiab, _TAG.sub("", raw).strip())
        if value and value.lower() not in seen:
            seen.add(value.lower())
            target.append(value)
    return mesh, tiab
