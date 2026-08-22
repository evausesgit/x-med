"""Recommandations de sociétés savantes : reconnaissance et niveau de preuve.

Les recommandations des grandes sociétés savantes (ESC, AHA/ACC, ESMO, ADA,
IDSA, KDIGO…) sont publiées dans des revues indexées MEDLINE : elles arrivent
**déjà** par le flux FTP quotidien, porteuses d'un `PublicationType` dédié.
Ce n'est donc pas une source à ingérer, mais un type de document que le code ne
savait pas nommer — `grep -rin guideline app/` ne renvoyait rien.

Deux conséquences, traitées ici :

1. **À l'ingestion** — `_EVIDENCE_BY_TYPE` (`app/tasks/parse_articles.py`)
   ignorait ces types, et `min(levels) if levels else 4` classait une
   recommandation ESC 2024 au **niveau 4**, à égalité avec un éditorial ou une
   lettre à la rédaction. `GUIDELINE_EVIDENCE` est la table de vérité, fusionnée
   dans la grille d'ingestion.

2. **À la lecture** — corriger l'ingestion ne répare que les articles à venir.
   Les recommandations déjà en base (ordre de grandeur : ~26 000, soit ~0,10 %
   des 25 M de lignes, estimé par échantillonnage de pages) gardent leur
   `evidence_level = 4`, et un `UPDATE` global sur 30 Go de heap n'est pas une
   opération acceptable en production. `effective_evidence_level()` applique
   donc la correction **au moment de lire**, à partir de `publication_types`
   déjà stocké : aucun backfill, aucun verrou, effet immédiat sur tout le
   corpus historique.

Le niveau attribué est une convention de **priorisation**, pas une affirmation
méthodologique : une recommandation n'est pas un essai randomisé, elle en
synthétise plusieurs après revue systématique. La placer au niveau 1 dit « ne
pas l'enterrer sous les RCT », pas « niveau de preuve équivalent ». La grille
`evidence_level` mélange de ce fait deux sémantiques (qualité de preuve et
catégorie de document) ; une colonne `doc_kind` orthogonale serait plus propre
le jour où la distinction devra être exposée au médecin.
"""

from __future__ import annotations

# `PublicationType` NLM → niveau attribué dans la grille projet (1 = plus haut).
# « Consensus Development Conference » est un cran en dessous : consensus
# d'experts, sans la revue systématique qui fonde une recommandation de bonne
# pratique.
GUIDELINE_EVIDENCE: dict[str, int] = {
    "Practice Guideline": 1,
    "Guideline": 1,
    "Consensus Development Conference": 2,
    "Consensus Development Conference, NIH": 2,
}

GUIDELINE_TYPES = frozenset(GUIDELINE_EVIDENCE)


def is_guideline(publication_types: list[str] | None) -> bool:
    """L'article est-il une recommandation / un consensus de société savante ?"""
    return any(t in GUIDELINE_TYPES for t in (publication_types or []))


def effective_evidence_level(
    stored_level: int | None, publication_types: list[str] | None
) -> int | None:
    """Niveau de preuve corrigé à la lecture, sans backfill du corpus.

    Renvoie le meilleur (= le plus petit) entre le niveau stocké et celui que
    méritent les `publication_types` de recommandation. Les articles ingérés
    après le correctif ont déjà le bon niveau en base : la fonction est alors
    idempotente et ne change rien.
    """
    candidates = [
        GUIDELINE_EVIDENCE[t]
        for t in (publication_types or [])
        if t in GUIDELINE_EVIDENCE
    ]
    if stored_level is not None:
        candidates.append(stored_level)
    return min(candidates) if candidates else None
