"""validate_skill.py on planted fixtures. Fake token shapes are built at run time so this file holds none."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT, SCRIPTS, SKILL

import validate_skill

GOOD_SKILL = """---
name: sandbox-runbook
description: Use when a task involves a sandbox, sbx, a fleet, testcontainers in a box, parallel agents, a cloud box, a kit, or a request to offload tests.
compatibility: Docker Sandboxes sbx 0.51.0
---

# sbx

## Use case: full suite

Trust: trusted. Script: `sbx_fleet.py`. Deep note: [note](docs/use-cases/full.md)
"""
GOOD_NOTE = """---
type: Knowledge
title: Full suite
description: A note.
tags: [sbx]
status: stable
date: 2026-11-05
state: measured
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L346
---

# Full suite

See [the index](../index.md).
"""
GOOD_INDEX = GOOD_NOTE.replace("state: measured\ntrust: trusted\n", "").replace("[the index](../index.md)", "[Full](use-cases/full.md)")
ENTRY = "### {anchor}\n\n- **Symptom:** s\n- **Error:** `e`\n- **Cause:** c\n- **Fix:** f\n- **Confirm:** k\n- **Seen on:** sbx 0.51.0\n\n"
SNAPSHOT = '{"version": "0.51.0", "cloud_commands": [], "verbs": {%s}}'


def good_snapshot() -> str:
    from sbxlib.domain.drift import VERBS

    return SNAPSHOT % ", ".join(f'"{verb}": {{"flags": {{}}, "commands": []}}' for verb in VERBS)


def good_guide() -> str:
    from sbxlib.domain.known_errors import KNOWN

    head = GOOD_INDEX.replace("# Full suite", "# Troubleshooting").replace("See [Full](use-cases/full.md).", "")
    return head + "".join(ENTRY.format(anchor=anchor) for anchor in sorted({anchor for _, anchor in KNOWN}))


class Base(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.write("skills/sandbox-runbook/SKILL.md", GOOD_SKILL)
        self.write("skills/sandbox-runbook/scripts/sbx_fleet.py", "")
        self.write("skills/sandbox-runbook/docs/index.md", GOOD_INDEX)
        self.write("skills/sandbox-runbook/docs/troubleshooting.md", good_guide())
        self.write("skills/sandbox-runbook/docs/use-cases/full.md", GOOD_NOTE)
        self.write("skills/sandbox-runbook/templates/python.md", "# {{TARGET_PROJECT}}\n")
        self.write("skills/sandbox-runbook/references/cli-snapshot.json", good_snapshot())
        self.write("README.md", "# readme\n")

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def findings(self, deny: frozenset[str] = frozenset()) -> list[str]:
        return validate_skill.validate(self.root, deny)

    def assert_finding(self, fragment: str, deny: frozenset[str] = frozenset()) -> None:
        joined = "\n".join(self.findings(deny))
        self.assertIn(fragment, joined)


class Clean(Base):
    def test_a_good_fixture_is_clean(self) -> None:
        self.assertEqual(self.findings(), [])

    def test_compatibility_pin_is_required(self) -> None:
        self.write("skills/sandbox-runbook/SKILL.md", GOOD_SKILL.replace("compatibility: Docker Sandboxes sbx 0.51.0\n", ""))
        self.assert_finding("compatibility must pin")

    def test_current_fact_wording_is_rejected(self) -> None:
        self.write("skills/sandbox-runbook/SKILL.md", GOOD_SKILL.replace("# sbx", "# sbx\n\nCurrent release is 0.51.0."))
        self.assert_finding("replace current/latest factual wording")


class Leaks(Base):
    def plant(self, text: str, name: str = "docs.md") -> None:
        self.write(name, text)

    def test_a_denied_word(self) -> None:
        self.plant("about acmecorp here")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_an_accented_form_of_a_denied_word(self) -> None:
        self.plant("about \u00e4cmecorp here")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_cyrillic_look_alike_of_a_denied_word(self) -> None:
        self.plant("about " + chr(0x430) + "cmecorp here")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_denied_word_joined_to_another(self) -> None:
        self.plant("about my-acmecorp-tool here")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_denied_word_inside_a_longer_word(self) -> None:
        self.plant("see AcmecorpCloud")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_denied_word_in_a_file_path(self) -> None:
        self.plant("x", "docs/acmecorp-notes.md")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_denied_word_in_a_file_with_no_suffix(self) -> None:
        self.plant("acmecorp", "Dockerfile")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_shell_script_is_scanned(self) -> None:
        self.plant("acmecorp", "run.sh")
        self.assert_finding("leak", frozenset({"acmecorp"}))

    def test_a_finding_never_repeats_the_word(self) -> None:
        self.plant("acmecorp")
        self.assertNotIn("acmecorp", "\n".join(self.findings(frozenset({"acmecorp"}))))

    def test_each_local_path_shape(self) -> None:
        colon, back = chr(58), chr(92)
        for path in (f"C{colon}{back}Users{back}bob", f"c{colon}{back}users{back}bob", "/" + "c/" + "users/bob", "/" + "c/" + "Users/bob",
                     f"D{colon}{back}work{back}x", "/" + "mnt/data/bob", "/" + "root/x", back * 2 + "fileserver" + back + "share",
                     "/" + "Users" + "/bob/x", "/" + "home/bob/x", "/" + "c/development/x"):
            self.plant(path)
            self.assert_finding("local path", frozenset())

    def test_the_box_home_is_allowed(self) -> None:
        self.plant("/home/agent/out.tgz")
        self.assertEqual(self.findings(), [])

    def test_a_token_shape(self) -> None:
        for token in ("gh" + "p_" + "a" * 36, "AK" + "IA" + "A" * 16, "dckr" + "_pat_" + "a" * 20, "github" + "_pat_" + "a" * 30):
            self.plant(token)
            self.assert_finding("secret shape", frozenset())

    def test_a_personal_email(self) -> None:
        self.plant("write to bob" + chr(64) + "acme.example")
        self.assert_finding("email", frozenset())

    def test_private_project_wording_is_refused(self) -> None:
        self.plant("measured on a " + "private project")
        self.assert_finding("target project", frozenset())


class DenyFile(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def load(self, text: str) -> frozenset[str]:
        path = self.folder / "deny.txt"
        path.write_text(text, encoding="utf-8")
        with mock.patch.dict(os.environ, {"SBX_SKILL_DENYLIST": str(path)}):
            return validate_skill.load_denylist(self.folder / "repo")

    def test_no_variable_is_no_list(self) -> None:
        with mock.patch.dict(os.environ, {"SBX_SKILL_DENYLIST": ""}):
            self.assertEqual(validate_skill.load_denylist(self.folder), frozenset())

    def test_entries_are_normalised_like_the_text(self) -> None:
        self.assertEqual(self.load("  \u00c4cmeCorp \n\n"), frozenset({"acmecorp"}))

    def test_a_compound_entry_keeps_its_punctuation_out(self) -> None:
        self.assertEqual(self.load("big corp\nbig_corp\nbig.corp\n"), frozenset({"bigcorp"}))

    def test_a_too_short_entry_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.load("!!\n")

    def test_a_list_inside_the_repo_is_refused(self) -> None:
        repo = self.folder
        path = repo / "deny.txt"
        path.write_text("x1\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SBX_SKILL_DENYLIST": str(path)}), self.assertRaises(ValueError):
            validate_skill.load_denylist(repo)

    def test_a_missing_list_is_refused_not_ignored(self) -> None:
        with mock.patch.dict(os.environ, {"SBX_SKILL_DENYLIST": str(self.folder / "absent")}), self.assertRaises(ValueError):
            validate_skill.load_denylist(self.folder / "repo")


class Links(Base):
    def test_a_broken_link(self) -> None:
        self.write("README.md", "[x](nope.md)\n")
        self.assert_finding("broken link")

    def test_a_link_leaving_the_skill_folder(self) -> None:
        self.write("skills/sandbox-runbook/docs/index.md", GOOD_INDEX + "\n[x](../../../README.md)\n")
        self.assert_finding("leaves the skill folder")

    def test_a_link_in_a_code_fence_is_not_a_link(self) -> None:
        self.write("README.md", "```\n[x](nope.md)\n```\n")
        self.assertEqual(self.findings(), [])

    def test_a_url_in_a_code_span_is_still_checked(self) -> None:
        self.write("README.md", "`https://internal.example/x`\n")
        self.assert_finding("not on the public allow-list")

    def test_a_url_in_a_fence_is_still_checked(self) -> None:
        self.write("README.md", "```\nhttps://internal.example/x\n```\n")
        self.assert_finding("not on the public allow-list")

    def test_an_unpinned_link(self) -> None:
        self.write("README.md", "[x](https://github.com/ffroliva/sbx-team-kit/blob/main/FINDINGS.md)\n")
        self.assert_finding("not pinned")

    def test_a_pinned_link(self) -> None:
        self.write("README.md", "[x](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md)\n")
        self.assertEqual(self.findings(), [])

    def test_two_pins_of_one_repo_disagree(self) -> None:
        # fix-6: a repin that misses one link leaves the tree citing two versions of the same evidence
        self.write("README.md", "[x](https://github.com/ffroliva/sbx-team-kit/blob/49bff7343c7f2e7986102499015920175b98fa87/FINDINGS.md)\n")
        self.assert_finding("ffroliva/sbx-team-kit is pinned at 2 commits")

    def test_a_pin_in_a_template_counts(self) -> None:
        self.write("skills/sandbox-runbook/templates/ci.yml", "# https://github.com/ffroliva/sbx-team-kit/tree/49bff7343c7f2e7986102499015920175b98fa87\n")
        self.assert_finding("ffroliva/sbx-team-kit is pinned at 2 commits")

    def test_the_two_named_sharpit_branches_may_differ_and_a_third_may_not(self) -> None:
        shas = ("31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700", "e1e5f7e33535e25bb0fd11abc0011d46c4e71abb")
        links = "".join(f"[x](https://github.com/ffroliva/sharpit/blob/{sha}/a.py)\n" for sha in shas)
        self.write("README.md", links)
        self.assertEqual(self.findings(), [])
        self.write("README.md", links + f"[x](https://github.com/ffroliva/sharpit/blob/{'a' * 40}/a.py)\n")
        self.assert_finding("ffroliva/sharpit is pinned at 3 commits")

    def test_an_unknown_repo(self) -> None:
        self.write("README.md", "[x](https://github.com/acme/secret/blob/49bff7343c7f2e7986102499015920175b98fa87/a.md)\n")
        self.assert_finding("allow-list")

    def test_an_issue_link_needs_no_sha(self) -> None:
        self.write("README.md", "[x](https://github.com/docker/sbx-releases/issues/773)\n")
        self.assertEqual(self.findings(), [])

    def test_a_repo_root_is_fine_in_the_readme(self) -> None:
        self.write("README.md", "[x](https://github.com/docker/sbx-releases)\n")
        self.assertEqual(self.findings(), [])

    def test_a_repo_root_elsewhere_is_not(self) -> None:
        self.write("skills/sandbox-runbook/docs/index.md", GOOD_INDEX + "\n[x](https://github.com/docker/sbx-releases)\n")
        self.assert_finding("not pinned")

    def test_a_malformed_url_is_a_finding_not_a_crash(self) -> None:
        self.write("README.md", "`https:///x`\n")
        self.assert_finding("allow-list")


class Docs(Base):
    NOTE = "skills/sandbox-runbook/docs/use-cases/full.md"

    def test_no_frontmatter(self) -> None:
        self.write("skills/sandbox-runbook/docs/x.md", "# x\n")
        self.assert_finding("no OKF frontmatter")

    def test_wrong_type(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace("type: Knowledge", "type: Other"))
        self.assert_finding("type must be Knowledge")

    def test_a_missing_field(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace("date: 2026-11-05\n", ""))
        self.assert_finding("lacks date")

    def test_an_invented_state(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace("state: measured", "state: great"))
        self.assert_finding("state must be")

    def test_a_missing_trust_level(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace("trust: trusted\n", ""))
        self.assert_finding("trust must be")

    def test_a_missing_source(self) -> None:
        self.write(self.NOTE, "\n".join(line for line in GOOD_NOTE.splitlines() if not line.startswith("source:")))
        self.assert_finding("lacks source")

    def test_a_bare_scheme_is_not_a_source(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace(GOOD_NOTE.split("source: ")[1].split("\n")[0], "http"))
        self.assert_finding("needs a URL source")

    def test_the_target_project_label_is_a_source(self) -> None:
        self.write(self.NOTE, GOOD_NOTE.replace(GOOD_NOTE.split("source: ")[1].split("\n")[0], "measured on a target project, not independently reproducible"))
        self.assertEqual(self.findings(), [])


class Skill(Base):
    PATH = "skills/sandbox-runbook/SKILL.md"

    def test_the_name(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("name: sandbox-runbook", "name: other"))
        self.assert_finding("name must be sandbox-runbook")

    def test_the_description_trigger(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("Use when", "For"))
        self.assert_finding("must start")

    def test_a_keyword(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("testcontainers", "containers"))
        self.assert_finding("lacks keyword")

    def test_a_workflow_in_the_description(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("Use when", "Use when first"))
        self.assert_finding("summarises a workflow")

    def test_the_word_limit(self) -> None:
        self.write(self.PATH, GOOD_SKILL + "word " * 1600)
        self.assert_finding("over 1500")

    def test_a_section_with_no_script_line(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("Script: `sbx_fleet.py`. ", ""))
        self.assert_finding("names no Script")

    def test_a_section_with_no_trust_line(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("Trust: trusted. ", ""))
        self.assert_finding("states no trust level")

    def test_a_section_naming_a_missing_script(self) -> None:
        self.write(self.PATH, GOOD_SKILL.replace("sbx_fleet.py", "sbx_nope.py"))
        self.assert_finding("does not exist")

    def test_a_section_and_note_disagreeing_on_trust(self) -> None:
        self.write("skills/sandbox-runbook/docs/use-cases/full.md", GOOD_NOTE.replace("trust: trusted", "trust: untrusted"))
        self.assert_finding("disagree on trust")

    def test_a_note_with_no_section(self) -> None:
        self.write("skills/sandbox-runbook/docs/use-cases/other.md", GOOD_NOTE)
        self.assert_finding("no use case section")


class Troubleshooting(Base):
    PATH = "skills/sandbox-runbook/docs/troubleshooting.md"

    def test_an_entry_missing_a_field(self) -> None:
        for field in ("Symptom", "Error", "Cause", "Fix", "Confirm", "Seen on"):
            self.write(self.PATH, good_guide().replace(f"**{field}:**", "**Other:**", 1))
            self.assert_finding(f"lacks {field}")

    def test_a_known_error_with_no_entry(self) -> None:
        self.write(self.PATH, good_guide().replace("### deny-all-403", "### renamed"))
        self.assert_finding("deny-all-403")

    def test_a_missing_guide(self) -> None:
        (self.root / self.PATH).unlink()
        self.assert_finding("troubleshooting.md: missing")


class Templates(Base):
    def test_an_unknown_placeholder(self) -> None:
        self.write("skills/sandbox-runbook/templates/python.md", "{{OTHER_THING}}\n")
        self.assert_finding("OTHER_THING")

    def test_the_old_placeholder_is_refused(self) -> None:
        self.write("skills/sandbox-runbook/templates/python.md", "<your-repo>\n")
        self.assert_finding("{{TARGET_PROJECT}}")


class Snapshot(Base):
    PATH = "skills/sandbox-runbook/references/cli-snapshot.json"

    def test_a_missing_snapshot(self) -> None:
        (self.root / self.PATH).unlink()
        self.assert_finding("snapshot missing")

    def test_an_unreadable_snapshot(self) -> None:
        self.write(self.PATH, "nope")
        self.assert_finding("snapshot unreadable")

    def test_a_verb_absent_from_the_snapshot(self) -> None:
        self.write(self.PATH, SNAPSHOT % '"create": {"flags": {}, "commands": []}')
        self.assert_finding("absent from the snapshot")


class ThisRepo(unittest.TestCase):
    def test_this_repo_validates(self) -> None:
        self.assertEqual(validate_skill.validate(ROOT, frozenset()), [])

    def test_no_denylist_ships(self) -> None:
        self.assertFalse((SCRIPTS / "denylist.sha256").exists())

    def test_every_script_answers_help_from_another_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for script in sorted(SCRIPTS.glob("*.py")):
                done = subprocess.run([sys.executable, str(script), "--help"], cwd=folder, capture_output=True, text=True, check=False, timeout=30)
                self.assertEqual(done.returncode, 0, f"{script.name}: {done.stderr}")

    def test_runtime_code_imports_the_standard_library_only(self) -> None:
        allowed = {*sys.stdlib_module_names, "sbxlib", "sbx_drift", "sbx_fleet"}
        for path in [*SCRIPTS.glob("*.py"), *(SCRIPTS / "sbxlib").rglob("*.py")]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            names += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module]
            self.assertLessEqual({name.split(".")[0] for name in names}, allowed, path.name)

    def test_the_skill_folder_runs_from_a_copy(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / "skill"
            shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
            project = Path(folder) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")
            done = subprocess.run([sys.executable, str(copy / "scripts" / "sbx_onboard.py"), str(project)], cwd=folder, capture_output=True,
                                  text=True, check=False, timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue((project / "docs" / "sbx.md").is_file())


if __name__ == "__main__":
    unittest.main()
