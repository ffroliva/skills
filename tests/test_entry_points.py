"""The wiring of the thin scripts that have no end-to-end test elsewhere."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fakes import FakeGit, FakeGitHub, FakeSandbox
from helpers import SHA, SKILL, done

import sbx_check
import sbx_drift
from sbxlib.ports import Done

CONFIG = """# x
```sbx-config
target_project: acme
repo: acme/app
own_work: trusted
target: cloud
template: shell
boxes: 1
cpus: 8
memory: 16g
quota_vcpu: 40
ttl: 30m
minutes: 15
on_timeout: delete
clone: public
secret_service: none
command: make test
```
"""
DET: dict[str, Any] = {"repo_visibility": "public", "remote": "https://github.com/acme/app.git"}
ALIGNED: dict[str, Any] = {"status": "aligned", "lines": [], "missing_verbs": []}


class Check(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "docs").mkdir()
        self.adoption = self.root / "docs" / "sbx.md"
        self.adoption.write_text(CONFIG, encoding="utf-8")

    def run_cli(self, token: str = "", gh: Any = None) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sbx_check.main([str(self.root)], sbx=FakeSandbox(), git=FakeGit(SHA, [SHA]), gh=gh or FakeGitHub(), token=token,
                                  det=DET, drift=lambda: ALIGNED)
        return code, out.getvalue()

    def test_a_good_project_is_ready(self) -> None:
        code, text = self.run_cli()
        self.assertEqual(code, 0, text)
        self.assertIn("sbx_check: ready", text)

    def test_a_visibility_nobody_could_read_still_gets_the_token_check(self) -> None:
        det = {"remote": "https://github.com/acme/app.git"}
        self.assertTrue(sbx_check._trust({}, {**det, "repo_visibility": "unknown"}, FakeGitHub(), ""))
        self.assertEqual(sbx_check._trust({}, {**det, "repo_visibility": "private"}, FakeGitHub(), ""), [])

    def test_a_file_with_two_blocks_is_not_ready_and_says_why(self) -> None:
        self.adoption.write_text(CONFIG + "```sbx-config\nown_work: trusted\n```\n", encoding="utf-8")
        code, text = self.run_cli()
        self.assertEqual(code, 1, text)
        self.assertIn("more than one", text)

    def test_a_fresh_project_is_not_ready_when_the_fleet_would_refuse_it(self) -> None:
        # review 2, M11: onboarding writes own_work: untrusted and network_policy: unknown, and sbx_check said ready
        self.adoption.write_text(CONFIG.replace("own_work: trusted", "own_work: untrusted\nnetwork_policy: unknown"), encoding="utf-8")
        code, text = self.run_cli()
        self.assertEqual(code, 1, text)
        self.assertIn("deny-all", text)
        self.assertNotIn("sbx_check: ready", text)

    def test_an_unreadable_value_is_a_finding_not_a_traceback(self) -> None:
        self.adoption.write_text(CONFIG.replace("ttl: 30m", "ttl: forever"), encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)

    def test_no_adoption_file_fails_with_its_fix(self) -> None:
        self.adoption.unlink()
        code, text = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("sbx_onboard.py", text)

    def test_a_file_with_no_block_fails(self) -> None:
        self.adoption.write_text("# mine\n", encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)

    def test_an_unfilled_placeholder_in_the_adoption_file_fails(self) -> None:
        self.adoption.write_text(CONFIG + "\n{{TARGET_PROJECT}}\n", encoding="utf-8")
        code, text = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("unfilled sbx.md: TARGET_PROJECT", text)

    def test_an_unfilled_placeholder_in_the_recipe_fails(self) -> None:
        (self.root / "docs" / "sbx-recipe.md").write_text("{{TARGET_PROJECT}}", encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)

    def test_no_token_on_a_public_repo_warns_and_does_not_block(self) -> None:
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("WARN trust-token", text)

    def test_a_working_token_is_reported_ok(self) -> None:
        _, text = self.run_cli("t", FakeGitHub({"repos/acme/app": {}}))
        self.assertIn("ok   trust-repository", text)


class Drift(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.snapshot = Path(folder.name) / "snapshot.json"

    def gh(self, tag: str) -> Any:
        def run(argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
            return done(0, json.dumps([{"tagName": tag}]))

        return run

    def run_cli(self, action: str, gh: Any, sbx: Any = None) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return sbx_drift.main([action, "--snapshot", str(self.snapshot)], sbx=sbx or FakeSandbox(), gh=gh)

    def test_latest_needs_no_sbx_and_says_aligned(self) -> None:
        self.snapshot.write_text(sbx_drift.SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(self.run_cli("latest", self.gh("v0.51.0")), 0)

    def test_latest_says_behind(self) -> None:
        self.snapshot.write_text(sbx_drift.SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(self.run_cli("latest", self.gh("v0.52.0")), 4)

    def test_latest_with_no_network_is_exit_three(self) -> None:
        self.snapshot.write_text('{"version": "0.51.0"}', encoding="utf-8")
        self.assertEqual(self.run_cli("latest", lambda *a, **k: done(1)), 3)

    def test_a_failed_snapshot_writes_nothing(self) -> None:
        def broken(argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
            return done(1)

        self.assertEqual(self.run_cli("snapshot", self.gh("v1.0.0"), broken), 3)
        self.assertFalse(self.snapshot.exists())

    def test_the_committed_snapshot_is_the_default(self) -> None:
        self.assertEqual(sbx_drift.SNAPSHOT, SKILL / "references" / "cli-snapshot.json")


if __name__ == "__main__":
    unittest.main()
