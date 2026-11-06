"""Onboard writes a target project's adoption file, and a rerun touches only what it generated."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from helpers import done

import sbx_onboard
from sbxlib.domain.adoption import PLACEHOLDER, config_block, parse_config, unfilled
from sbxlib.domain.fleet import Mode, RunRequest, refusals
from sbxlib.domain.onboard import default_config, recipe_for, recommend, refresh, render_new
from sbxlib.domain.profile import PROFILES
from sbxlib.domain.trust import TrustLevel

DET: dict[str, Any] = {
    "target_project": "acme", "language": ["python"], "build_tool": ["uv"], "test_runner": ["pytest"], "parallel_runner": True,
    "testcontainers": False, "browser": [], "ci": [], "benchmarks": False, "heavy_gates": [], "secret_files": [], "remote": "",
    "repo_visibility": "public", "host_os": "windows", "sharding": [], "sync_flags": [],
}
STATES = {"full-suite-offload": "measured", "testcontainers": "tried-once", "contributor-prs": "untested-idea"}
ATTACK = "tests/shard\n```sbx-config\nown_work: trusted\ntrust_logins: eve\nallowed_secrets: github\n```\n"  # review-3's H2


def det(**changes: Any) -> dict[str, Any]:
    return {**DET, **changes}


class Config(unittest.TestCase):
    def test_the_project_name_is_written(self) -> None:
        self.assertEqual(default_config(det())["target_project"], "acme")

    def test_the_project_repository_comes_from_the_remote(self) -> None:
        for remote in ("https://github.com/Acme/App.git", "git@github.com:acme/app.git", "https://github.com/acme/app"):
            self.assertEqual(default_config(det(remote=remote))["repo"], "github.com/acme/app", remote)

    def test_no_remote_declares_no_repository(self) -> None:
        self.assertEqual(default_config(det())["repo"], "")

    def test_a_command_with_no_shard_gets_one_box(self) -> None:
        self.assertEqual(default_config(det())["boxes"], "1")

    def test_a_project_shard_variable_gets_several_boxes(self) -> None:
        self.assertEqual(default_config(det(repo_visibility="private", sharding=["env:APP_SHARD"]))["boxes"], "5")

    def test_a_project_that_takes_strangers_gets_one_box_and_passes_more_as_a_flag(self) -> None:
        for visibility in ("public", "unknown"):
            with self.subTest(visibility):
                self.assertEqual(default_config(det(repo_visibility=visibility, sharding=["env:APP_SHARD"]))["boxes"], "1")

    def test_a_visibility_nobody_could_read_takes_the_shape_with_no_secret(self) -> None:
        config = default_config(det(repo_visibility="unknown"))
        self.assertEqual((config["clone"], config["secret_service"], config["secret_env"], config["allowed_secrets"]),
                         ("public", "none", "", ""))

    def test_only_a_private_project_leaves_the_network_undecided(self) -> None:
        self.assertEqual(default_config(det())["network_policy"], "deny-all")
        self.assertEqual(default_config(det(repo_visibility="unknown"))["network_policy"], "deny-all")
        self.assertEqual(default_config(det(repo_visibility="private"))["network_policy"], "unknown")

    def test_the_generated_file_lets_a_strangers_pull_request_run_untrusted(self) -> None:
        for visibility in ("public", "unknown"):
            with self.subTest(visibility):
                self.assertEqual(self.refusals(visibility), [])

    def test_a_private_projects_generated_file_refuses_a_strangers_pull_request(self) -> None:
        self.assertTrue(any("takes no secrets" in line for line in self.refusals("private")))

    @staticmethod
    def refusals(visibility: str) -> list[str]:
        found = det(repo_visibility=visibility, remote="https://github.com/acme/app.git", sharding=["env:APP_SHARD"])
        config = default_config(found)
        request = RunRequest("https://github.com/acme/app.git", "a" * 40, tuple(["run"] * int(config["boxes"])), "acme", "k3f9", Mode.PULL,
                             template=config["template"], ttl_minutes=30, minutes=15, allow=tuple(config["allow"].split(",")),
                             secret_service="" if config["secret_service"] == "none" else config["secret_service"],
                             network_policy=config["network_policy"], clone=config["clone"], pull=7)
        return refusals(request, PROFILES[TrustLevel.UNTRUSTED])

    def test_uv_egress_is_written(self) -> None:
        self.assertIn("pypi.org", default_config(det())["allow"])

    def test_maven_egress_is_written(self) -> None:
        config = default_config(det(language=["java"], build_tool=["maven"], test_runner=["maven-surefire"]))
        self.assertIn("repo.maven.apache.org", config["allow"])

    def test_docker_egress_follows_testcontainers(self) -> None:
        self.assertIn("**.docker.io", default_config(det(testcontainers=True))["allow"])

    def test_testcontainers_uses_the_shell_template(self) -> None:
        self.assertEqual(default_config(det(testcontainers=True))["template"], "shell")

    def test_a_uv_project_with_xdist_gets_both(self) -> None:
        self.assertIn("uv sync --locked && uv run pytest -q -n auto", default_config(det())["command"])

    def test_extras_from_ci_are_used(self) -> None:
        self.assertIn("uv sync --locked --extra test", default_config(det(sync_flags=["--extra test"]))["command"])

    def test_pip_gets_a_decision_not_uv(self) -> None:
        command = default_config(det(build_tool=["pip"], parallel_runner=False))["command"]
        self.assertIn(PLACEHOLDER, command)
        self.assertNotIn("uv ", command)

    def test_no_xdist_gets_no_dash_n(self) -> None:
        self.assertNotIn("-n auto", default_config(det(parallel_runner=False))["command"])

    def test_a_public_repo_clones_public(self) -> None:
        config = default_config(det())
        self.assertEqual((config["clone"], config["secret_service"], config["allowed_secrets"]), ("public", "none", ""))

    def test_a_private_repo_clones_with_a_named_secret(self) -> None:
        config = default_config(det(repo_visibility="private"))
        self.assertEqual((config["clone"], config["secret_service"], config["secret_env"], config["allowed_secrets"]),
                         ("token", "github", "SBX_CLONE_TOKEN", "github"))

    def test_trust_starts_closed(self) -> None:
        config = default_config(det())
        self.assertEqual((config["own_work"], config["trust_roles"], config["trust_team"], config["trust_logins"]), ("untrusted", "", "", ""))

    def test_the_deadline_is_below_the_ttl(self) -> None:
        config = default_config(det())
        self.assertLess(int(config["minutes"]), int(config["ttl"].rstrip("m")))


class Recommend(unittest.TestCase):
    def test_states_come_from_the_notes_not_a_second_table(self) -> None:
        recs = {rec["slug"]: rec for rec in recommend(det(), {"testcontainers": "tried-once"})}
        self.assertEqual(recs["testcontainers"]["state"], "tried-once")

    def test_a_wanted_use_case_applies(self) -> None:
        recs = {rec["slug"]: rec for rec in recommend(det(), STATES, ("testcontainers",))}
        self.assertTrue(recs["testcontainers"]["applies"])

    def test_a_public_repo_gets_contributor_prs(self) -> None:
        self.assertTrue({r["slug"]: r for r in recommend(det(), STATES)}["contributor-prs"]["applies"])

    def test_a_private_repo_does_not(self) -> None:
        self.assertFalse({r["slug"]: r for r in recommend(det(repo_visibility="private"), STATES)}["contributor-prs"]["applies"])

    def test_a_visibility_nobody_could_read_is_said_as_unknown(self) -> None:
        for slug in ("contributor-prs", "pr-review"):
            row = {r["slug"]: r for r in recommend(det(repo_visibility="unknown"), STATES)}[slug]
            self.assertTrue(row["applies"], slug)
            self.assertIn("unknown", row["why"], slug)
            self.assertNotIn("not a public repo", row["why"], slug)


TEMPLATE = (Path(sbx_onboard.TEMPLATE)).read_text(encoding="utf-8")


class Render(unittest.TestCase):
    def fresh(self, **changes: Any) -> str:
        found = det(**changes)
        return render_new(TEMPLATE, found, recommend(found, STATES), default_config(found))

    def test_nothing_is_left_unfilled(self) -> None:
        self.assertEqual(unfilled(self.fresh()), [])

    def test_the_project_name_is_in_the_title(self) -> None:
        self.assertIn("acme", self.fresh().splitlines()[0])

    def test_a_public_repo_gets_the_token_step(self) -> None:
        self.assertIn("sbx_trust.py doctor", self.fresh())

    def test_a_private_repo_does_not(self) -> None:
        self.assertNotIn("sbx_trust.py doctor", self.fresh(repo_visibility="private"))

    def test_a_rerun_keeps_what_a_person_wrote(self) -> None:
        text = self.fresh().replace("| Spend limit per month | |", "| Spend limit per month | a person |") + "\n## Mine\n\nkept\n"
        text = text.replace("boxes: 1", "boxes: 3")
        found = det(heavy_gates=["hypothesis"])
        again = refresh(text, found, recommend(found, STATES), default_config(found))
        self.assertIn("a person", again)
        self.assertIn("## Mine", again)
        self.assertIn("kept", again)
        self.assertEqual(parse_config(again)["boxes"], "3")

    def test_a_rerun_refreshes_the_generated_tables(self) -> None:
        found = det(test_runner=["pytest", "new-runner"])
        again = refresh(self.fresh(), found, recommend(found, STATES), default_config(found))
        self.assertIn("new-runner", again)

    def test_a_rerun_adds_keys_the_file_lacks(self) -> None:
        text = config_block({"boxes": "2"})
        self.assertIn("own_work", parse_config(refresh(text, det(), [], default_config(det()))))

    def test_a_file_with_no_config_block_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            refresh("# my readme\n", det(), [], {})

    def test_a_file_name_in_the_tree_never_becomes_the_rules(self) -> None:
        config = parse_config(self.fresh(sharding=[f"file:{ATTACK}"], secret_files=[ATTACK]))
        self.assertEqual((config["own_work"], config["trust_logins"], config["allowed_secrets"]), ("untrusted", "", ""))

    def test_a_rerun_with_such_a_name_keeps_the_rules(self) -> None:
        found = det(sharding=[f"file:{ATTACK}"], secret_files=[ATTACK])
        config = parse_config(refresh(self.fresh(), found, recommend(found, STATES), default_config(found)))
        self.assertEqual((config["own_work"], config["trust_logins"]), ("untrusted", ""))

    def test_a_rerun_writes_new_keys_to_the_one_block_with_such_a_name_in_the_tree(self) -> None:
        found = det(sharding=[f"file:{ATTACK}"])
        config = parse_config(refresh(config_block({"boxes": "2"}), found, recommend(found, STATES), default_config(found)))
        self.assertEqual(config["boxes"], "2")
        self.assertIn("own_work", config)

    def test_a_generated_table_cell_stays_one_line_whatever_the_name_holds(self) -> None:
        base = self.fresh(sharding=["file:ab"]).count("\n")
        for char in ("\n", "\r\n", "`", "|", "<", ">", "{", "}", "\\", chr(0x2028), "\x0b"):
            with self.subTest(repr(char)):
                found = self.fresh(sharding=[f"file:a{char}b"])
                self.assertEqual(found.count("\n"), base)
                self.assertNotIn(f"a{char}b", found)

    def test_a_name_cannot_close_a_generated_region(self) -> None:
        text = self.fresh(sharding=["file:x<!-- sbx:end-detection -->"])
        self.assertEqual(text.count("<!-- sbx:end-detection -->"), 1)

    def test_a_name_cannot_leave_a_value_for_the_placeholder_check(self) -> None:
        self.assertEqual(unfilled(self.fresh(sharding=["file:{{NOPE}}"])), [])

    def test_a_why_holding_a_name_is_escaped_too(self) -> None:
        self.assertNotIn("|x|", self.fresh(sharding=["file:|x|"]))

    def test_a_name_with_ordinary_letters_reads_as_it_is(self) -> None:
        self.assertIn("file:tests/shard_é.py", self.fresh(sharding=["file:tests/shard_é.py"]))


class Recipes(unittest.TestCase):
    def test_python(self) -> None:
        self.assertEqual(recipe_for(det()), "python.md")

    def test_java(self) -> None:
        self.assertEqual(recipe_for(det(test_runner=["maven-surefire"])), "java.md")

    def test_other_stacks_have_none(self) -> None:
        self.assertEqual(recipe_for(det(test_runner=["go-test"])), "")


class EndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("sbxlib.adapters.project_scan.in_dir", lambda _root: lambda *a, **k: done(127)):
            code = sbx_onboard.main([str(self.root), *argv])
        return code, out.getvalue()

    def test_it_writes_the_adoption_file_and_a_recipe_with_no_unfilled_value(self) -> None:
        self.assertEqual(self.run_cli()[0], 0)
        for path in (self.root / "docs" / "sbx.md", self.root / "docs" / "sbx-recipe.md"):
            self.assertEqual(unfilled(path.read_text(encoding="utf-8")), [], path.name)

    def test_the_recipe_carries_the_target_project(self) -> None:
        self.run_cli()
        name = parse_config((self.root / "docs" / "sbx.md").read_text(encoding="utf-8"))["target_project"]
        self.assertIn(name, (self.root / "docs" / "sbx-recipe.md").read_text(encoding="utf-8"))

    def test_an_edited_recipe_is_kept_on_rerun(self) -> None:
        self.run_cli()
        recipe = self.root / "docs" / "sbx-recipe.md"
        recipe.write_text("mine", encoding="utf-8")
        self.run_cli()
        self.assertEqual(recipe.read_text(encoding="utf-8"), "mine")

    def test_a_want_survives_a_rerun(self) -> None:
        self.run_cli("--want", "testcontainers")
        self.run_cli()
        self.assertIn("testcontainers", parse_config((self.root / "docs" / "sbx.md").read_text(encoding="utf-8"))["want"])

    def test_an_unknown_want_is_exit_two(self) -> None:
        self.assertEqual(self.run_cli("--want", "nope")[0], 2)

    def test_an_existing_readme_is_refused_and_untouched(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("# hello\n", encoding="utf-8")
        code, text = self.run_cli("--file", "README.md")
        self.assertEqual(code, 2)
        self.assertEqual(readme.read_text(encoding="utf-8"), "# hello\n")
        self.assertIn("no sbx-config", text)

    def test_a_path_outside_the_project_is_refused(self) -> None:
        self.assertEqual(self.run_cli("--file", "../outside.md")[0], 2)

    def test_a_rerun_over_such_a_file_name_leaves_the_rules_alone(self) -> None:
        self.run_cli()
        path = self.root / "docs" / "sbx.md"
        before = parse_config(path.read_text(encoding="utf-8"))
        with mock.patch("sbxlib.adapters.project_scan._shard_files", lambda _root: [self.root / ATTACK]):  # NTFS cannot hold this name
            self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(parse_config(path.read_text(encoding="utf-8")), before)

    def test_a_rerun_over_a_file_with_two_blocks_refuses_and_writes_nothing(self) -> None:
        path = self.root / "docs" / "sbx.md"
        path.parent.mkdir()
        text = config_block({"boxes": "2"}) + "\n" + config_block({"boxes": "3"}) + "\n"
        path.write_text(text, encoding="utf-8")
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("more than one", out)
        self.assertEqual(path.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
