"""Sélection des candidats — la vraie différence entre v1 et v2.

Écrit **avant** le nettoyage (voir `PLAN_NETTOYAGE.md` § Étape 0, test 3).

v1 « score IA » et v2 « fusion RRF » sont deux réglages du même endpoint
`POST /search/pubmed/deep`. Tout le reste du pipeline est commun : le seul endroit
où les deux modes divergent est l'**ordre des candidats** soumis au juge, décidé
par `_candidate_order`. C'est donc le seul test qui prouve que les deux modes se
comportent encore différemment après le nettoyage.

`_pick_judge_batch` est testé dans la foulée : c'est lui qui garantit que les
candidats locaux ne se font pas enterrer par PubMed dans le lot jugé.

Ni base ni réseau : fonctions pures.
"""

from app.api.search import _candidate_order, _pick_judge_batch

# Deux listes de candidats qui se recoupent sur un seul PMID (3), placé en fin de
# liste PubMed mais en tête de liste locale — le cas d'école où RRF change l'ordre.
A_PMIDS = [1, 2, 3]  # PubMed, ordre Best Match
LOCAL_PMIDS = [3, 4, 5]  # local, ordre ts_rank


# --------------------------------------------------------------------------- #
# _candidate_order : v1 vs v2
# --------------------------------------------------------------------------- #


def test_v1_keeps_pubmed_first_order():
    """v1 (`rrf=False`) : union dédupliquée, PubMed d'abord, ordre inchangé."""
    assert _candidate_order(A_PMIDS, LOCAL_PMIDS, rrf=False) == [1, 2, 3, 4, 5]


def test_v2_promotes_the_article_found_by_both():
    """v2 (`rrf=True`) : le PMID 3, présent dans les deux listes, remonte en tête
    alors qu'il était 3ᵉ côté PubMed."""
    assert _candidate_order(A_PMIDS, LOCAL_PMIDS, rrf=True) == [3, 1, 2, 4, 5]


def test_v1_and_v2_really_differ():
    """L'assertion qui compte : si un jour les deux modes rendent le même ordre
    sur cette entrée, c'est que la fusion RRF a été neutralisée."""
    v1 = _candidate_order(A_PMIDS, LOCAL_PMIDS, rrf=False)
    v2 = _candidate_order(A_PMIDS, LOCAL_PMIDS, rrf=True)
    assert v1 != v2
    assert sorted(v1) == sorted(v2), "les deux modes portent sur les mêmes candidats"


def test_both_modes_deduplicate():
    """Un PMID trouvé des deux côtés n'apparaît qu'une fois, dans les deux modes."""
    for rrf in (False, True):
        out = _candidate_order([1, 2, 3], [3, 2, 9], rrf=rrf)
        assert len(out) == len(set(out)) == 4


def test_rrf_rewards_being_ranked_by_both_lists():
    """Rang 0 des deux côtés (1/60 + 1/60) bat rang 0 d'un seul côté (1/60)."""
    out = _candidate_order([7, 8], [7, 9], rrf=True)
    assert out[0] == 7


def test_rrf_ties_keep_the_original_order():
    """Le tri est stable : à score RRF égal, l'ordre de l'union est conservé.
    (2 est rang 1 côté PubMed, 4 est rang 1 côté local → même score 1/61.)"""
    out = _candidate_order(A_PMIDS, LOCAL_PMIDS, rrf=True)
    assert out.index(2) < out.index(4)


def test_empty_inputs_are_handled():
    assert _candidate_order([], [], rrf=True) == []
    assert _candidate_order([], [4, 5], rrf=True) == [4, 5]
    assert _candidate_order([1, 2], [], rrf=True) == [1, 2]
    assert _candidate_order([], [4, 5], rrf=False) == [4, 5]


# --------------------------------------------------------------------------- #
# _pick_judge_batch : le plancher de candidats locaux
# --------------------------------------------------------------------------- #

# Vivier où PubMed monopolise la tête : sans plancher, aucun local n'est jugé.
JUDGEABLE = [10, 11, 12, 13, 20, 21, 22, 23]
PUBMED = {10, 11, 12, 13}  # → 20..23 sont les « locaux-seuls »


def test_no_floor_takes_the_head_of_the_pool():
    assert _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=4, floor=0) == [10, 11, 12, 13]


def test_floor_reserves_slots_for_local_only_candidates():
    """floor=2 : deux locaux entrent dans le lot, qui garde la taille demandée."""
    batch = _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=4, floor=2)
    assert len(batch) == 4
    assert sum(1 for p in batch if p not in PUBMED) >= 2


def test_floor_keeps_the_pool_order():
    """Le lot reste trié dans l'ordre du vivier — donc dans l'ordre RRF en v2."""
    batch = _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=4, floor=2)
    assert batch == sorted(batch, key=JUDGEABLE.index)


def test_floor_is_capped_by_batch_size():
    """Un plancher plus grand que le lot ne fait pas déborder le lot."""
    batch = _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=3, floor=99)
    assert len(batch) == 3
    assert len(set(batch)) == 3


def test_floor_already_satisfied_changes_nothing():
    """Si la tête du vivier contient déjà assez de locaux, le lot n'est pas retouché."""
    pool = [20, 21, 10, 11]
    assert _pick_judge_batch(pool, PUBMED, batch_n=4, floor=2) == pool


def test_floor_with_too_few_locals_does_not_crash():
    """Moins de locaux que le plancher : on prend ce qu'on a, sans doublon."""
    pool = [10, 11, 12, 20]
    batch = _pick_judge_batch(pool, PUBMED, batch_n=3, floor=2)
    assert len(batch) == len(set(batch)) == 3
    assert 20 in batch


def test_batch_never_exceeds_the_requested_size():
    for floor in range(0, 6):
        for batch_n in range(1, 9):
            batch = _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=batch_n, floor=floor)
            assert len(batch) <= batch_n
            assert len(batch) == len(set(batch))
            assert set(batch) <= set(JUDGEABLE)


def test_v1_default_floor_is_pure_head_of_pool():
    """Rappel des réglages réels : v1 tourne avec `local_floor=0`, donc sans
    plancher — le lot est exactement la tête du vivier."""
    assert _pick_judge_batch(JUDGEABLE, PUBMED, batch_n=50, floor=0) == JUDGEABLE
