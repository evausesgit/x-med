import json

from experiments.autoresearch_xmed.build_annotation_pool import build


def test_annotation_pool_deduplicates_and_hides_system_scores(tmp_path):
    paths = []
    for index, score in enumerate((3, 2), 1):
        path = tmp_path / f"run{index}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": f"run{index}",
                    "cases": [
                        {
                            "query_id": "q1",
                            "query": "question",
                            "results": [
                                {
                                    "pmid": 1,
                                    "title": "title",
                                    "abstract": "abstract",
                                    "score": score,
                                    "source": "pubmed",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        paths.append(path)
    items, key = build(paths, top_k=10, seed=1)
    assert len(items) == 1
    assert "score" not in items[0]
    assert "source" not in items[0]
    assert key["systems"][items[0]["item_id"]] == ["run1", "run2"]
