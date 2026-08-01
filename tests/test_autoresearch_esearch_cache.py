from pathlib import Path

from experiments.autoresearch_xmed.esearch_cache import search_cached


def test_esearch_cache_keys_all_parameters_and_honours_ttl(tmp_path: Path):
    calls = []

    def search(term, **params):
        calls.append((term, params))
        return 2, [1, 2]

    first = search_cached("term", tmp_path, mindate="2026", search=search)
    second = search_cached("term", tmp_path, mindate="2026", search=search)
    changed = search_cached("term", tmp_path, mindate="2025", search=search)
    expired = search_cached("term", tmp_path, mindate="2026", ttl_s=-1, search=search)

    assert first == (2, [1, 2], False)
    assert second == (2, [1, 2], True)
    assert changed[2] is False
    assert expired[2] is False
    assert len(calls) == 3
