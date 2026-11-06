"""Deterministic validation for the manual skill scenarios."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "sandbox-runbook" / "scripts"))

from eval_scenarios import score  # noqa: E402


class ScenarioEvals(unittest.TestCase):
    def test_scenarios_have_prompts_ordered_expectations_and_forbids(self) -> None:
        scenarios = json.loads((ROOT / "evals" / "scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual({item["id"] for item in scenarios}, {"targeted-tests", "sharded-fleet", "contributor-pr", "stale-skill", "leaked-box-cleanup"})
        for item in scenarios:
            self.assertTrue(item["prompt"])
            self.assertTrue(item["expected"])
            self.assertTrue(item["forbid"])

    def test_transcript_commands_must_be_in_order(self) -> None:
        self.assertTrue(score({"expected": ["check", "fleet"], "forbid": []}, ["fleet", "check"]))

    def test_forbidden_commands_are_reported(self) -> None:
        scenario = {"expected": ["check", "fleet"], "forbid": ["rm --all"]}
        self.assertTrue(score(scenario, ["check", "rm --all", "fleet"]))

    def test_a_missing_expected_command_is_reported(self) -> None:
        self.assertTrue(score({"expected": ["check", "fleet"], "forbid": []}, ["check"]))
