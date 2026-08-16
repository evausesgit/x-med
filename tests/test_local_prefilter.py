"""Pré-filtre local : concepts en ET + échelle de relâchement.

Corrige le défaut de performance qui rendait la base locale inutilisable : les
mots-clés de codex étaient aplatis en un seul OU (`" OR ".join(keywords)`), ce
qui fait payer à la requête le mot le plus banal de la liste. Le coût d'une FTS
est dominé par le NOMBRE DE LIGNES QUI MATCHENT (`ORDER BY ts_rank` détoaste le
tsvector de chacune), pas par la taille de la table. Mesuré sur la fenêtre
2025-2026 : 268 137 lignes en 92,8 s pour le OU à plat, 1 546 lignes en 21 ms
pour le ET des mêmes concepts.

Ces tests sont sans base : ils vérifient le SQL produit et la logique des
paliers. Le chemin réel contre Postgres est couvert par test_deep_search_smoke.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.api import search
from app.api.search import (
    LOCAL_MIN_POOL,
    _concept_groups,
    _interleave,
    _local_prefilter,
    _local_tsquery,
)
from app.models import ArticleSearch
from app.services.query_builder import normalize_concepts

ENDO = [
    ["endometriosis", "endometriotic"],
    ["endometrioma", "chocolate cyst"],
    ["surgery", "laparoscopy", "cystectomy"],
]


# --------------------------------------------------------------------------- #
# La tsquery : ET des concepts, OU des synonymes
# --------------------------------------------------------------------------- #


def _sql(groups) -> str:
    from sqlalchemy import func, select

    tsq = _local_tsquery(groups)
    stmt = (
        select(ArticleSearch.pmid)
        .where(ArticleSearch.fts.op("@@")(tsq))
        .order_by(func.ts_rank(ArticleSearch.fts, tsq).desc())
    )
    return str(stmt.compile(dialect=postgresql.dialect()))


def _where(groups) -> str:
    """La clause WHERE seule — la tsquery apparaît aussi dans le ORDER BY."""
    return _sql(groups).split("WHERE")[1].split("ORDER BY")[0]


def test_concepts_are_combined_with_and():
    """Un `&&` (ET tsquery) par concept au-delà du premier — jamais un OU à plat."""
    assert _where(ENDO).count("&&") == len(ENDO) - 1


def test_synonyms_stay_inside_their_group():
    """Les synonymes d'un concept partent en OU dans le MÊME websearch_to_tsquery."""
    params = _local_tsquery(ENDO).compile(dialect=postgresql.dialect()).params
    assert "endometriosis OR endometriotic" in params.values()
    assert "endometrioma OR chocolate cyst" in params.values()


def test_the_tsquery_is_parenthesised_under_the_match_operator():
    """`fts @@ (a && b)` et pas `(fts @@ a) && b`.

    Piège Postgres : `@@` et `&&` ont la même précédence et sont associatifs à
    gauche. Sans les parenthèses, la requête filtrerait sur le premier concept
    seulement, puis tenterait un ET entre un booléen et une tsquery. SQLAlchemy
    groupe l'expression — ce test garde le comportement s'il change de version.
    """
    assert "@@ ((" in _where(ENDO), _where(ENDO)


def test_a_single_concept_needs_no_and():
    assert "&&" not in _where([["vismodegib", "erivedge"]])


# --------------------------------------------------------------------------- #
# Le choix des groupes : concepts > mots-clés > rien (jamais la question FR)
# --------------------------------------------------------------------------- #


def test_concepts_win_over_flat_keywords():
    assert _concept_groups(ENDO, ["endometriosis", "pain"]) == ENDO


def test_keywords_fall_back_to_a_single_group():
    """codex n'a pas honoré le schéma : on garde l'ancien comportement (un OU),
    borné par le garde-fou — mais on ne perd pas la recherche locale."""
    assert _concept_groups([], ["endometriosis", "pain"]) == [["endometriosis", "pain"]]


def test_no_keywords_means_no_local_search():
    """Sans mot-clé ANGLAIS, le pré-filtre est sauté.

    Le code envoyait la question FRANÇAISE à `websearch_to_tsquery('english', …)`,
    qui n'en tire quasi aucun lexème utile : le vivier local tombait à 0 sans le
    dire. Mieux vaut annoncer qu'on s'appuie sur PubMed seul.
    """
    assert _concept_groups([], []) == []
    assert _concept_groups(None, None) == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ([["a", " "], [], ["b"]], [["a"], ["b"]]),  # termes et groupes vides
        ([["a", "a "], ["b"]], [["a"], ["b"]]),  # doublon dans un groupe
        ([["a"], ["A"]], [["a"]]),  # groupe dupliqué (casse ignorée)
        (["a", ["b"]], [["a"], ["b"]]),  # concept aplati en chaîne
        ([["a"], 42], [["a"]]),  # type inattendu
    ],
)
def test_normalize_concepts_cleans_what_codex_sends(raw, expected):
    assert normalize_concepts(raw) == expected


# --------------------------------------------------------------------------- #
# La fusion des paliers
# --------------------------------------------------------------------------- #


def test_interleave_keeps_the_strict_pool_first():
    assert _interleave([1, 2], [[3, 4], [5, 6]], 10) == [1, 2, 3, 5, 4, 6]


def test_interleave_gives_each_variant_its_share():
    """Bout à bout, la première variante remplirait toutes les places : chacune
    est classée par SON ts_rank, donc on prend en tourniquet."""
    assert _interleave([], [[1, 2, 3], [7, 8, 9]], 4) == [1, 7, 2, 8]


def test_interleave_dedupes_and_respects_the_limit():
    assert _interleave([1], [[1, 2], [2, 3]], 3) == [1, 2, 3]


# --------------------------------------------------------------------------- #
# L'échelle de relâchement
# --------------------------------------------------------------------------- #


class _FakeRuns:
    """Doublure de `_run_prefilter` : rend un résultat par nombre de groupes reçus."""

    def __init__(self, results: dict[int, tuple[list[int], str]]):
        self.results = results
        self.calls: list[list[list[str]]] = []

    def __call__(self, corpus, Src, groups, conditions, limit, timeout_ms, token):
        self.calls.append(groups)
        assert timeout_ms > 0, "chaque tentative doit recevoir un budget positif"
        return self.results.get(len(groups), ([], "ok"))


def _ladder(monkeypatch, results):
    fake = _FakeRuns(results)
    monkeypatch.setattr(search, "_run_prefilter", fake)
    events: list[str] = []
    pmids, state = _local_prefilter(
        None, ArticleSearch, ENDO, [], 200, None,
        lambda phase, msg, **d: events.append(phase),
    )
    return fake, pmids, state, events


def test_a_wide_enough_pool_stops_at_the_strict_and(monkeypatch):
    """Le palier strict suffit : une seule requête, pas d'élargissement.

    Cas mesuré « kystes d'endométriose » : 236 articles en 1,9 s pour le ET des
    3 concepts, largement au-dessus du seuil.
    """
    pool = list(range(236))
    fake, pmids, state, events = _ladder(monkeypatch, {3: (pool, "ok")})

    assert len(fake.calls) == 1
    assert pmids == pool
    assert state == "ok"
    assert "filter_relax" not in events


def test_a_narrow_pool_relaxes_one_concept_at_a_time(monkeypatch):
    """Cas mesuré « GLP-1 et douleurs » : 3 articles en ET strict, 4 en retirant
    le concept `pain` — le quatrième est pertinent mais n'emploie pas ce mot."""
    fake, pmids, state, events = _ladder(
        monkeypatch, {3: ([1, 2, 3], "ok"), 2: ([1, 2, 3, 4], "ok")}
    )

    assert len(fake.calls) == 1 + len(ENDO), "une variante par concept retiré"
    assert all(len(g) == 2 for g in fake.calls[1:]), "toujours 2 concepts en ET"
    assert set(pmids) == {1, 2, 3, 4}
    assert pmids[:3] == [1, 2, 3], "le palier strict garde la tête"
    assert state == "ok"
    assert "filter_relax" in events


def test_the_ladder_never_drops_below_two_concepts(monkeypatch):
    """Avec 2 concepts, relâcher laisserait UN concept seul — donc les centaines
    de milliers de lignes que ce code corrige. On rend le vivier étroit tel quel."""
    fake = _FakeRuns({2: ([1], "ok")})
    monkeypatch.setattr(search, "_run_prefilter", fake)
    pmids, state = _local_prefilter(
        None, ArticleSearch, ENDO[:2], [], 200, None, lambda *a, **k: None
    )
    assert len(fake.calls) == 1
    assert (pmids, state) == ([1], "ok")


def test_a_timeout_on_the_strict_and_is_not_retried(monkeypatch):
    """Si le ET strict a déjà épuisé le budget, relâcher ne ferait qu'élargir :
    on remonte le timeout pour que le médecin le voie."""
    fake, pmids, state, _ = _ladder(monkeypatch, {3: ([], "timeout")})
    assert len(fake.calls) == 1
    assert (pmids, state) == ([], "timeout")


def test_the_stop_button_ends_the_ladder(monkeypatch):
    """Bouton stop pendant une variante : on rend ce que le palier strict avait
    déjà trouvé plutôt que de repartir pour un tour."""
    fake, pmids, state, _ = _ladder(
        monkeypatch, {3: ([1, 2], "ok"), 2: ([], "stopped")}
    )
    assert len(fake.calls) == 2, "on n'enchaîne pas les autres variantes"
    assert (pmids, state) == ([1, 2], "ok")


def test_the_stop_token_survives_between_attempts(monkeypatch):
    """Le PID reste enregistré pendant TOUTE l'échelle, et est nettoyé à la fin.

    S'il était retiré après chaque tentative, un clic sur « arrêter » tombant
    entre deux paliers ne trouverait rien à annuler.
    """
    seen: list[bool] = []

    def fake(corpus, Src, groups, conditions, limit, timeout_ms, token):
        search._LOCAL_SEARCH_PIDS[token] = 4242  # ce que fait _run_prefilter
        seen.append(token in search._LOCAL_SEARCH_PIDS)
        return ([1], "ok") if len(groups) == 3 else ([2], "ok")

    monkeypatch.setattr(search, "_run_prefilter", fake)
    _local_prefilter(None, ArticleSearch, ENDO, [], 200, "jeton", lambda *a, **k: None)

    assert len(seen) > 1 and all(seen), "le jeton doit rester posé d'un palier à l'autre"
    assert "jeton" not in search._LOCAL_SEARCH_PIDS, "nettoyé à la sortie"


def test_the_pool_threshold_is_the_relax_trigger(monkeypatch):
    """Juste au seuil : pas d'élargissement. Juste en dessous : élargissement."""
    fake, _, _, _ = _ladder(monkeypatch, {3: (list(range(LOCAL_MIN_POOL)), "ok")})
    assert len(fake.calls) == 1
    fake, _, _, _ = _ladder(monkeypatch, {3: (list(range(LOCAL_MIN_POOL - 1)), "ok")})
    assert len(fake.calls) > 1
