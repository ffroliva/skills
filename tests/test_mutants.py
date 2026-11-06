"""tests/mutants.py: a mutant whose anchor no longer matches the code fails the run, never passes as nothing tested."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mutants


class StaleAnchor(unittest.TestCase):
    def test_a_mutant_whose_anchor_is_gone_fails_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "code.py").write_text("x = 1\n", encoding="utf-8")
            with mock.patch.object(mutants, "SNAP", folder):
                res = [mutants.run(("stale", "code.py", "x = 2", "x = 3"))]
        self.assertEqual(res[0][0], "NOT-APPLIED")
        self.assertEqual(mutants.failures(res), ["NOT-APPLIED stale"])

    def test_only_killed_mutants_pass(self) -> None:
        self.assertEqual(mutants.failures([("killed", "a", "t"), ("killed(timeout)", "b", "")]), [])
        self.assertEqual(mutants.failures([("killed", "a", "t"), ("SURVIVED", "b", "")]), ["SURVIVED b"])


if __name__ == "__main__":
    unittest.main()
