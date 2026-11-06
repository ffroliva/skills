"""`sbx_shard.py plan` and `check` on real JUnit files."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import helpers  # noqa: F401

import sbx_shard


def junit(*cases: tuple[str, str, float], failed: str = "") -> str:
    rows = "".join(f'<testcase classname="{unit}" name="{name}" time="{seconds}">{"<failure/>" if name == failed else ""}</testcase>'
                   for unit, name, seconds in cases)
    return f"<testsuite>{rows}</testsuite>"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def box(self, name: str, text: str) -> None:
        path = self.root / "run" / name / "out"
        path.mkdir(parents=True, exist_ok=True)
        (path / "junit.xml").write_text(text, encoding="utf-8")

    def file(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sbx_shard.main(list(argv))
        return code, out.getvalue()


class Unreadable(Base):
    def test_a_missing_folder_is_exit_two_not_an_empty_plan(self) -> None:
        # review 2, low 3: exit 0 with three empty shards
        code, text = self.cli("plan", "--junit", str(self.root / "gone"), "--n", "3")
        self.assertEqual(code, 2, text)

    def test_a_folder_with_no_junit_is_exit_two(self) -> None:
        (self.root / "empty").mkdir()
        self.assertEqual(self.cli("plan", "--junit", str(self.root / "empty"), "--n", "3")[0], 2)

    def test_a_run_check_with_no_expected_count_says_so(self) -> None:
        code, text = self.cli("check", "--junit", str(self.root / "run"))
        self.assertEqual(code, 2, text)
        self.assertIn("--expect", text)

    def test_expected_count_must_be_positive(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.cli("check", "--junit", str(self.root / "run"), "--expect", "0")
        self.assertEqual(caught.exception.code, 2)


class Plan(Base):
    def plan(self, *extra: str) -> dict[str, Any]:
        code, text = self.cli("plan", "--junit", str(self.root / "run"), "--n", "2", *extra)
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def test_the_assignment_is_json_with_loads(self) -> None:
        self.box("b1", junit(("a", "x", 9.0), ("b", "y", 5.0), ("c", "z", 4.0)))
        body = self.plan()
        self.assertEqual([shard["units"] for shard in body["shards"]], [["a"], ["b", "c"]])
        self.assertEqual([shard["load_s"] for shard in body["shards"]], [9.0, 9.0])

    def test_a_listed_unit_with_no_timing_is_unmeasured(self) -> None:
        self.box("b1", junit(("a", "x", 9.0)))
        self.assertEqual(self.plan("--units", str(self.file("units.txt", "a\nnew\n")))["unmeasured"], ["new"])

    def test_the_ceiling_moves_a_big_unit_to_its_own_job(self) -> None:
        self.box("b1", junit(("big", "x", 500.0), ("a", "y", 1.0)))
        self.assertEqual(self.plan("--ceiling", "100")["own_job"], ["big"])

    def test_heavy_and_timing_files_are_honoured(self) -> None:
        self.box("b1", junit(("h", "x", 50.0), ("t", "y", 1.0), ("a", "z", 1.0)))
        body = self.plan("--heavy", str(self.file("h.txt", "h\n")), "--timing", str(self.file("t.txt", "t\n")))
        self.assertIn("t", body["shards"][1]["units"])
        self.assertNotIn("h", body["shards"][1]["units"])

    def test_a_dominant_unit_gets_advice(self) -> None:
        self.box("b1", junit(("big", "x", 100.0), ("a", "y", 1.0)))
        self.assertTrue(self.plan()["advice"])

    def test_no_junit_is_exit_two(self) -> None:
        code, _ = self.cli("plan", "--junit", str(self.root / "run"), "--n", "0")
        self.assertEqual(code, 2)


class Check(Base):
    def saved_plan(self, body: dict[str, Any]) -> str:
        return str(self.file("plan.json", json.dumps(body)))

    def test_a_good_plan_exits_zero(self) -> None:
        self.box("b1", junit(("a", "x", 1.0), ("b", "y", 1.0)))
        _, text = self.cli("plan", "--junit", str(self.root / "run"), "--n", "2")
        code, out = self.cli("check", "--plan", str(self.file("plan.json", text)))
        self.assertEqual(code, 0, out)

    def test_a_hand_written_assignment_is_checked_too(self) -> None:
        plan = self.saved_plan({"shards": [{"units": ["a", "b"]}, {"units": ["b"]}], "weights": {"a": 1, "b": 1}})
        code, text = self.cli("check", "--plan", plan)
        self.assertEqual(code, 1)
        self.assertIn("in more than one place: b", text)

    def test_a_malformed_plan_is_exit_two(self) -> None:
        self.assertEqual(self.cli("check", "--plan", str(self.file("plan.json", "{}")))[0], 2)

    def test_weights_that_are_no_table_are_exit_two(self) -> None:
        # review 4, Low 7: a traceback, exit 1
        plan = self.saved_plan({"shards": [{"units": ["a"]}], "weights": ["a"]})
        self.assertEqual(self.cli("check", "--plan", plan)[0], 2)

    def test_a_shard_count_the_plan_does_not_hold_is_exit_two(self) -> None:
        plan = self.saved_plan({"n": 5, "shards": [{"units": ["a"]}, {"units": ["b"]}], "weights": {"a": 1, "b": 1}})
        code, text = self.cli("check", "--plan", plan)
        self.assertEqual(code, 2, text)
        self.assertIn("n is 5", text)

    def test_a_time_that_is_no_number_counts_as_zero(self) -> None:
        # review 4, Low 6: plan printed NaN, which is not JSON
        self.box("b1", '<testsuite><testcase classname="a" name="x" time="nan"/><testcase classname="b" name="y" time="inf"/>'
                       '<testcase classname="c" name="z" time="2"/></testsuite>')
        code, text = self.cli("plan", "--junit", str(self.root / "run"), "--n", "2")
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text, parse_constant=lambda name: self.fail(f"{name} in the plan")).get("n"), 2)

    def test_an_unknown_encoding_is_exit_two(self) -> None:
        # review 4, Low 1: a traceback, exit 1
        self.box("b1", '<?xml version="1.0" encoding="no-such"?><testsuite><testcase name="a"/></testsuite>')
        self.assertEqual(self.cli("plan", "--junit", str(self.root / "run"), "--n", "2")[0], 2)

    def test_a_run_at_the_expected_count_passes(self) -> None:
        self.box("b1", junit(("a", "x", 1.0)))
        self.box("b2", junit(("a", "y", 1.0)))
        self.assertEqual(self.cli("check", "--junit", str(self.root / "run"), "--expect", "2")[0], 0)

    def test_a_lost_shard_fails(self) -> None:
        self.box("b1", junit(("a", "x", 1.0)))
        code, text = self.cli("check", "--junit", str(self.root / "run"), "--expect", "2")
        self.assertEqual(code, 1)
        self.assertIn("a shard was lost", text)

    def test_a_skipped_test_does_not_count_as_run(self) -> None:
        # review-3, M3: its docstring promises every test ran once and passed
        self.box("b1", '<testsuite><testcase classname="c" name="a"/><testcase classname="c" name="b"><skipped/></testcase></testsuite>')
        code, text = self.cli("check", "--junit", str(self.root / "run"), "--expect", "2")
        self.assertEqual(code, 1, text)
        self.assertIn("expected 2 unique tests, found 1", text)
        self.assertIn("1 skipped", text)

    def test_a_plan_with_no_shards_is_exit_two(self) -> None:
        code, text = self.cli("check", "--plan", self.saved_plan({"shards": []}))
        self.assertEqual(code, 2, text)

    def test_a_failure_fails(self) -> None:
        self.box("b1", junit(("a", "x", 1.0), failed="x"))
        self.assertEqual(self.cli("check", "--junit", str(self.root / "run"), "--expect", "1")[0], 1)

    def test_broken_xml_is_exit_two(self) -> None:
        self.box("b1", "<testsuite>")
        self.assertEqual(self.cli("check", "--junit", str(self.root / "run"))[0], 2)

    def test_nothing_to_check_is_exit_two(self) -> None:
        self.assertEqual(self.cli("check")[0], 2)


if __name__ == "__main__":
    unittest.main()
