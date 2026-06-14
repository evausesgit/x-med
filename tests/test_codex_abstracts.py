import json
import subprocess
import unittest
from unittest.mock import patch

from app.services.codex_abstracts import (
    AbstractCandidate,
    CodexAbstractError,
    assess_batch,
    iter_batches,
)


class BatchTests(unittest.TestCase):
    def test_batches_respect_article_limit(self):
        candidates = [
            AbstractCandidate(pmid=i, title=f"title {i}", abstract="abstract")
            for i in range(1, 6)
        ]

        batches = list(iter_batches(candidates, token_budget=10_000, max_articles=2))

        self.assertEqual([[1, 2], [3, 4], [5]], [[c.pmid for c in b] for b in batches])

    def test_batches_respect_token_budget(self):
        candidates = [
            AbstractCandidate(pmid=1, title="a", abstract="x" * 120),
            AbstractCandidate(pmid=2, title="b", abstract="y" * 120),
        ]

        batches = list(iter_batches(candidates, token_budget=90, max_articles=10))

        self.assertEqual([[1], [2]], [[c.pmid for c in b] for b in batches])


class AssessmentTests(unittest.TestCase):
    @staticmethod
    def _write_codex_output(cmd, payload):
        output_path = cmd[cmd.index("-o") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_assess_batch_uses_gpt_54_and_applies_threshold(self):
        batch = [
            AbstractCandidate(11, "Relevant", "Directly answers the question."),
            AbstractCandidate(12, "Weak", "Only shares the broad topic."),
        ]

        def fake_run(cmd, **kwargs):
            self.assertIn("gpt-5.4", cmd)
            self.assertEqual("-", cmd[-1])
            self.assertIn('"pmid":11', kwargs["input"])
            self._write_codex_output(
                cmd,
                {
                    "assessments": [
                        {
                            "pmid": 11,
                            "score": 0.8,
                            "relevant": True,
                            "justification": "Direct match.",
                        },
                        {
                            "pmid": 12,
                            "score": 0.4,
                            "relevant": False,
                            "justification": "Broad topic only.",
                        },
                    ]
                },
            )
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.services.codex_abstracts.subprocess.run", side_effect=fake_run):
            assessments = assess_batch("PRM", batch, threshold=0.55)

        self.assertEqual([11, 12], [item.pmid for item in assessments])
        self.assertTrue(assessments[0].relevant)
        self.assertFalse(assessments[1].relevant)

    def test_assess_batch_rejects_missing_pmid(self):
        batch = [
            AbstractCandidate(21, "One", "Abstract one."),
            AbstractCandidate(22, "Two", "Abstract two."),
        ]

        def fake_run(cmd, **_kwargs):
            self._write_codex_output(
                cmd,
                {
                    "assessments": [
                        {
                            "pmid": 21,
                            "score": 0.9,
                            "relevant": True,
                            "justification": "Relevant.",
                        }
                    ]
                },
            )
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.services.codex_abstracts.subprocess.run", side_effect=fake_run):
            with self.assertRaises(CodexAbstractError):
                assess_batch("PRM", batch)


if __name__ == "__main__":
    unittest.main()
