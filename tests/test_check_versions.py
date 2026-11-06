"""scripts/check_versions.py: one version, one name, one copy of the skill, and a tag that equals them."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from helpers import ROOT

SCRIPT = ROOT / "scripts" / "check_versions.py"
FILES = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json",
         ".antigravity-plugin/plugin.json", ".agents/plugins/marketplace.json", "gemini-extension.json", "CHANGELOG.md",
         "skills/sandbox-runbook/SKILL.md")
CODEX, AGY, GEMINI = FILES[2], FILES[3], FILES[5]


class Check(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def run_it(self, **env: str) -> tuple[int, str]:
        clean = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_REF")}
        done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)], capture_output=True, text=True,
                              env={**clean, **env}, check=False)
        return done.returncode, done.stdout

    def edit(self, manifest: str, **changes: Any) -> None:
        path = self.root / manifest
        path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), **changes}), encoding="utf-8")

    def test_this_repository_is_aligned(self) -> None:
        code, text = self.run_it()
        self.assertEqual(code, 0, text)
        self.assertIn("0.1.0", text)

    def test_a_drifted_manifest_is_named(self) -> None:
        self.edit(CODEX, version="0.2.0")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn(".codex-plugin/plugin.json", text)

    def test_a_manifest_with_no_version_is_refused(self) -> None:
        path = self.root / GEMINI
        path.write_text('{"name": "sandbox-runbook"}', encoding="utf-8")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("gemini-extension.json", text)

    def test_broken_json_is_a_finding_not_a_traceback(self) -> None:
        (self.root / AGY).write_text("{", encoding="utf-8")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("not JSON", text)

    def test_a_missing_manifest_is_a_finding(self) -> None:
        (self.root / GEMINI).unlink()
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("gemini-extension.json", text)

    def test_a_name_that_is_not_the_skill_folder_is_refused(self) -> None:
        self.edit(CODEX, name="ffroliva-skills-two")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("name must be ffroliva-skills", text)

    def test_a_marketplace_missing_the_plugin_is_refused(self) -> None:
        self.edit(".claude-plugin/marketplace.json", plugins=[])
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("does not list ffroliva-skills", text)

    def test_the_antigravity_description_stays_short(self) -> None:
        self.edit(AGY, description="x" * 161)
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("160", text)

    def test_codex_must_point_at_the_one_skills_folder(self) -> None:
        self.edit(CODEX, skills="./elsewhere/")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("./skills/", text)

    def test_a_second_copy_of_the_skill_is_refused(self) -> None:
        extra = self.root / "plugins" / "ffroliva-skills" / "skills" / "sandbox-runbook" / "SKILL.md"
        extra.parent.mkdir(parents=True)
        extra.write_text("copy", encoding="utf-8")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("one copy", text)

    def test_a_version_with_no_changelog_heading_is_refused(self) -> None:
        (self.root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        code, text = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md", text)

    def test_a_tag_run_must_equal_the_version(self) -> None:
        code, text = self.run_it(GITHUB_REF_TYPE="tag", GITHUB_REF_NAME="v9.9.9")
        self.assertEqual(code, 1)
        self.assertIn("v9.9.9", text)

    def test_the_matching_tag_passes(self) -> None:
        self.assertEqual(self.run_it(GITHUB_REF_TYPE="tag", GITHUB_REF_NAME="v0.1.0")[0], 0)

    def test_a_branch_named_like_a_tag_is_no_tag_run(self) -> None:
        self.assertEqual(self.run_it(GITHUB_REF_TYPE="branch", GITHUB_REF_NAME="v9.9.9")[0], 0)


if __name__ == "__main__":
    unittest.main()
