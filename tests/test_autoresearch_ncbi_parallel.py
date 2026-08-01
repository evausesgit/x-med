import time

from experiments.autoresearch_xmed.bench_ncbi_parallel import hydrate_parallel


def test_hydrate_parallel_runs_both_calls_concurrently(monkeypatch):
    def summary(pmids):
        time.sleep(0.05)
        return {pmids[0]: "summary"}

    def abstracts(pmids):
        time.sleep(0.05)
        return {pmids[0]: "abstract"}

    monkeypatch.setattr(
        "experiments.autoresearch_xmed.bench_ncbi_parallel.pubmed_eutils.esummary", summary
    )
    monkeypatch.setattr(
        "experiments.autoresearch_xmed.bench_ncbi_parallel.pubmed_eutils.efetch_abstracts",
        abstracts,
    )
    started = time.monotonic()
    result = hydrate_parallel([1])
    assert time.monotonic() - started < 0.09
    assert result == ({1: "summary"}, {1: "abstract"})
