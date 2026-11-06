"""What the first real user hit: each test names its entry in the field log of 2026-11-05."""

from __future__ import annotations

import ast
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fakes import FakeGit, FakeGitHub, FakeSandbox
from helpers import SHA, done, result_tar

from test_fleet import UNTRUSTED_CONFIG, Base, with_keys

import sbx_check
import sbx_fleet
import sbx_onboard
from sbxlib.adapters.project_scan import detect
from sbxlib.domain.adoption import parse_config
from sbxlib.domain.fleet import worst_case_usd
from sbxlib.domain.onboard import recommend

BOX1 = "acme-targeted-01-k3f9"
TWO = ("--cpus", "4", "--memory", "8g")
SKIPPED_CASE = '<testcase classname="t" name="{}"><skipped/></testcase>'
PARTLY_SKIPPED = ('<testsuite><testcase classname="t" name="a"/>' + "".join(SKIPPED_CASE.format(name) for name in "bcd") + "</testsuite>")


class Output(Base):
    def test_f18_each_box_prints_its_name_and_a_live_read_when_it_is_created(self) -> None:
        _, text = self.run_cli("--command", "run")
        line = next(line for line in text.splitlines() if BOX1 in line and "exec" in line)
        self.assertIn(f"sbx --cloud exec {BOX1} bash -c", line)
        self.assertIn("run.log", line)
        self.assertLess(text.index(line), text.index("fleet: GREEN"))

    def test_f18_an_untrusted_box_prints_its_name_and_no_live_read(self) -> None:
        self.config.write_text(UNTRUSTED_CONFIG, encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 0, text)
        self.assertIn("box 1/1: acme-targeted-01-k3f9", text)
        self.assertNotIn("sbx --cloud exec", text)

    def test_f10_the_end_of_a_run_names_the_command_that_sees_cloud_boxes(self) -> None:
        _, text = self.run_cli("--command", "run")
        self.assertIn("sbx --cloud ls", text)
        self.assertIn("sbx --cloud secret ls", text)
        self.assertIn("`sbx ls` shows no cloud box", text)

    def test_f22_no_junit_prints_no_test_count(self) -> None:
        _, text = self.run_cli("--command", "run", "--no-junit")
        self.assertIn(f"{BOX1}: ", text)
        self.assertIn("tests n/a", text)
        self.assertNotIn(" 2 tests", text)

    def test_f21_a_label_names_each_box_at_create_at_the_end_and_in_the_verdict(self) -> None:
        _, text = self.run_cli("--command", "a", "--command", "b", "--label", "postgres", "--label", "mysql", *TWO)
        self.assertIn("box 2/2 (mysql): acme-shards-02-k3f9", text)
        self.assertIn("mysql, acme-shards-02-k3f9: ", text)
        self.assertEqual([row["label"] for row in self.verdict_json()["boxes"]], ["postgres", "mysql"])

    def test_f21_a_label_count_that_does_not_match_is_refused(self) -> None:
        code, text = self.run_cli("--command", "a", "--command", "b", "--label", "postgres", *TWO)
        self.assertEqual(code, 2)
        self.assertNotIn("create", self.sbx.verbs())
        self.assertIn("--label", text)


class Cost(Base):
    def test_f9_the_final_lines_and_the_verdict_carry_an_estimate(self) -> None:
        _, text = self.run_cli("--command", "run")
        seconds = self.verdict_json()["box_seconds"]
        self.assertEqual(self.verdict_json()["estimated_usd"], round(seconds * 8 * 0.07 / 3600, 3))
        self.assertIn("box-seconds, about $", text)

    def test_f9_the_worst_case_is_every_box_billing_to_its_ttl(self) -> None:
        self.assertEqual(worst_case_usd(5, 8, 30), 1.4)

    def test_f9_a_fleet_whose_worst_case_is_over_the_ceiling_is_refused(self) -> None:
        code, text = self.run_cli("--command", "run $SHARD", "--boxes", "5", "--max-usd", "1")
        self.assertEqual(code, 2)
        self.assertNotIn("create", self.sbx.verbs())
        self.assertIn("$1.40", text)

    def test_f9_a_fleet_at_the_ceiling_runs(self) -> None:
        self.assertEqual(self.run_cli("--command", "run $SHARD", "--boxes", "5", "--max-usd", "1.4")[0], 0)

    def test_f9_the_ceiling_can_come_from_the_adoption_file(self) -> None:
        self.config.write_text(with_keys("max_usd: 0.1" + chr(10)), encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 2, text)
        self.assertNotIn("create", self.sbx.verbs())

    def test_f9_a_ceiling_that_is_no_number_refuses(self) -> None:
        self.config.write_text(with_keys("max_usd: nan" + chr(10)), encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 2, text)
        self.assertIn("max_usd", text)


class Complete(Base):
    def test_f7_a_red_gate_that_ran_every_test_says_complete(self) -> None:
        self.sbx.tars[1] = result_tar(rc="1")
        code, text = self.run_cli("--command", "run", "--expect-tests", "2")
        self.assertEqual(code, 1)
        self.assertIn("complete: every box finished, 2 of 2 expected tests", text)
        self.assertIn("fleet: RED", text)
        self.assertIs(self.verdict_json()["complete"], True)

    def test_f7_a_red_gate_that_died_part_way_is_not_complete(self) -> None:
        self.sbx.tars[1] = result_tar(rc="137")
        code, text = self.run_cli("--command", "run", "--expect-tests", "21859")
        self.assertEqual(code, 1)
        self.assertIn("INCOMPLETE", text)
        self.assertIn("2 of 21859 expected tests", text)
        self.assertIs(self.verdict_json()["complete"], False)

    def test_f7_a_green_run_short_of_the_expected_count_is_red(self) -> None:
        code, text = self.run_cli("--command", "run", "--expect-tests", "3")
        self.assertEqual(code, 1)
        self.assertIn("fleet: RED", text)
        self.assertEqual(self.verdict_json()["exit"], 1)

    def test_f7_a_box_that_never_finished_is_not_complete(self) -> None:
        self.sbx.never_done.add(BOX1)
        code, text = self.run_cli("--command", "run", "--minutes", "1", "--expect-tests", "2")
        self.assertEqual(code, 1)
        self.assertIn("INCOMPLETE", text)
        self.assertIs(self.verdict_json()["complete"], False)

    def test_f7_with_no_expected_count_finishing_is_said_for_what_it_is(self) -> None:
        _, text = self.run_cli("--command", "run")
        self.assertIn("every box finished; no expected count was given", text)

    def test_f7_the_verdict_holds_each_box_and_the_count_it_was_held_to(self) -> None:
        self.run_cli("--command", "run", "--expect-tests", "2")
        body = self.verdict_json()
        self.assertEqual((body["tests"], body["expect_tests"]), (2, 2))
        self.assertEqual((body["boxes"][0]["name"], body["boxes"][0]["rc"], body["boxes"][0]["tests"]), (BOX1, 0, 2))

    def test_the_same_tests_on_two_boxes_count_once(self) -> None:
        # review-3, M2: two boxes ignoring $SHARD, each reporting the same cases
        code, text = self.run_cli("--command", "run # $SHARD", "--boxes", "2", "--expect-tests", "4")
        self.assertEqual(code, 1, text)
        self.assertIn("2 of 4 expected tests", text)
        self.assertIs(self.verdict_json()["complete"], False)

    def test_boxes_with_their_own_commands_add_up(self) -> None:
        # one gate on two servers reports one test twice, and both ran
        code, text = self.run_cli("--command", "run a", "--command", "run b", "--expect-tests", "4")
        self.assertEqual(code, 0, text)
        self.assertIs(self.verdict_json()["complete"], True)

    def test_a_skipped_test_is_not_a_test_that_ran(self) -> None:
        # review-3, M3: 1 passed, 3 skipped, and a fixture that skips without Docker reads exactly like this
        self.sbx.tars[1] = result_tar(junit=PARTLY_SKIPPED)
        code, text = self.run_cli("--command", "run", "--expect-tests", "4")
        self.assertEqual(code, 1, text)
        self.assertIn("1 of 4 expected tests ran, 3 skipped, 0 lost", text)
        self.assertIs(self.verdict_json()["complete"], False)

    def test_skips_are_not_called_lost(self) -> None:
        # gate 3, g4: `--expect-tests 455` on 451 run and 4 skipped printed "found 451: tests were lost"
        self.sbx.tars[1] = result_tar(junit=PARTLY_SKIPPED)
        code, text = self.run_cli("--command", "run", "--expect-tests", "4")
        self.assertEqual(code, 1, text)
        self.assertIn("expected 4 tests to run: 1 ran, 3 skipped, 0 lost; none was lost", text)
        self.assertIn("--expect-tests 1 if the skips are meant", text)
        self.assertNotIn("were lost", text)
        self.assertEqual(self.verdict_json()["lost"], 0)

    def test_a_test_that_neither_ran_nor_was_skipped_is_lost(self) -> None:
        self.sbx.tars[1] = result_tar(junit=PARTLY_SKIPPED)
        code, text = self.run_cli("--command", "run", "--expect-tests", "10")
        self.assertEqual(code, 1, text)
        self.assertIn("1 ran, 3 skipped, 6 lost; 6 tests were lost", text)
        self.assertIn("INCOMPLETE: 1 of 10 expected tests ran, 3 skipped, 6 lost", text)
        self.assertEqual(self.verdict_json()["lost"], 6)

    def test_skipped_tests_are_printed_and_stored(self) -> None:
        self.sbx.tars[1] = result_tar(junit=PARTLY_SKIPPED)
        _, text = self.run_cli("--command", "run")
        self.assertIn("4 tests, 3 skipped, rc 0", text)
        body = self.verdict_json()
        self.assertEqual((body["skipped"], body["ran"], body["boxes"][0]["skipped"]), (3, 1, 3))

    def test_more_tests_than_expected_is_red(self) -> None:
        code, text = self.run_cli("--command", "run", "--expect-tests", "1")
        self.assertEqual(code, 1, text)
        self.assertIn("expected 1 tests to run, 2 ran: more ran than the suite holds", text)
        self.assertNotIn("were lost", text)
        self.assertIs(self.verdict_json()["complete"], False)

    def test_f7_an_expected_count_needs_junit(self) -> None:
        code, text = self.run_cli("--command", "run", "--no-junit", "--expect-tests", "2")
        self.assertEqual(code, 2)
        self.assertNotIn("create", self.sbx.verbs())
        self.assertIn("--expect-tests", text)

    def test_f20_a_plant_says_what_green_means_beside_the_verdict(self) -> None:
        _, text = self.run_cli("--command", "run", "--means", "each plant was caught")
        self.assertIn("fleet: GREEN, which here means: each plant was caught", text)
        self.assertEqual(self.verdict_json()["means"], "each plant was caught")

    def test_f20_a_red_run_says_what_it_did_not_show(self) -> None:
        self.sbx.tars[1] = result_tar(rc="1")
        _, text = self.run_cli("--command", "run", "--means", "each plant was caught")
        self.assertIn("fleet: RED; green would have meant: each plant was caught", text)


def environment_in_output(source: str) -> list[int]:
    """Lines where a test asserts on, or prints, an expression holding the environment: a failing assert prints the whole of
    it, and a CI log keeps what it printed (speed run, G9: a local token reached a log this way)."""
    def holds_environment(node: ast.AST) -> bool:
        return any((isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv")) or (isinstance(n, ast.Name) and n.id in ("environ", "getenv"))
                   for n in ast.walk(node))

    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assert) and holds_environment(node.test):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
            if (name.startswith("assert") or name == "print") and any(holds_environment(arg) for arg in [*node.args, *node.keywords]):
                lines.append(node.lineno)
    return lines


class SpeedRun(Base):
    """The speed run of 2026-11-06: findings G1 to G10 in the field log, those that are behaviour."""

    def test_g5_one_command_repeated_on_every_box_runs(self) -> None:
        code, text = self.run_cli(*["--command", "run"] * 3)
        self.assertEqual(code, 0, text)
        self.assertNotIn("whole suite", text)
        self.assertEqual(len([verb for verb in self.sbx.verbs() if verb == "create"]), 3)

    def test_g5_repeats_each_count_their_own_tests(self) -> None:
        # a repeat is a run of its own, so three repeats of a 2-test command ran 6, where three shards of it ran 2
        code, text = self.run_cli(*["--command", "run"] * 3, "--expect-tests", "6")
        self.assertEqual(code, 0, text)
        self.assertIs(self.verdict_json()["complete"], True)

    def test_g5_one_command_fanned_out_without_shard_is_still_refused(self) -> None:
        code, text = self.run_cli("--command", "run", "--boxes", "3")
        self.assertEqual(code, 2, text)
        self.assertIn("whole suite: read $SHARD of $SHARDS in the command, or pass --command once per box to repeat it", text)

    def test_g9_no_test_here_asserts_on_or_prints_the_environment(self) -> None:
        found = {path.name: lines for path in sorted(Path(__file__).parent.glob("*.py"))
                 if (lines := environment_in_output(path.read_text(encoding="utf-8")))}
        self.assertEqual(found, {})

    def test_g9_the_scan_catches_each_shape(self) -> None:
        planted = ("import os\nassert os.environ.get('X') == '1'\nself.assertEqual(os.getenv('X'), '1')\n"
                   "print(dict(os.environ))\nvalue = os.environ.get('X')\nassert value == '1'\n")
        self.assertEqual(environment_in_output(planted), [2, 3, 4])


class OwnWork(Base):
    NO_REPO = with_keys("").replace("repo: acme/app" + chr(10), "")

    def test_sbx_check_sees_a_secret_variable_the_shell_does_not_hold(self) -> None:
        # review-3, Low 3: sbx_check said ready for a run the fleet refuses
        config = parse_config(with_keys("secret_service: github" + chr(10) + "secret_env: SBX_NOT_SET_HERE" + chr(10)))
        found = sbx_fleet.planned_refusals({**config, "command": "run"}, "https://github.com/acme/app.git")
        self.assertTrue(any("--secret-env" in line for line in found), found)

    def test_f11_a_trusted_file_with_no_repository_is_refused_before_any_box(self) -> None:
        self.config.write_text(self.NO_REPO, encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 2, text)
        self.assertNotIn("create", self.sbx.verbs())
        self.assertIn("own_work: trusted needs `repo: <owner/name>`", text)

    def test_f11_a_repository_that_cannot_be_read_is_no_repository(self) -> None:
        self.config.write_text(with_keys("").replace("repo: acme/app", "repo: not a repository"), encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 2, text)
        self.assertNotIn("create", self.sbx.verbs())

    def test_f11_the_refusal_names_the_one_fix_and_no_other(self) -> None:
        # seen reading the output: the untrusted profile's own lines came first, and sent the reader to `policy init deny-all`
        self.config.write_text("```sbx-config\ntarget_project: acme\nown_work: trusted\n```\n", encoding="utf-8")
        code, text = self.run_cli("--command", "run")
        self.assertEqual(code, 2, text)
        self.assertNotIn("deny-all", text)

    def test_f11_sbx_check_says_so_as_well(self) -> None:
        refused = sbx_fleet.planned_refusals({**parse_config(self.NO_REPO), "command": "run"}, "https://github.com/acme/app.git")
        self.assertTrue(any("needs `repo: <owner/name>`" in line for line in refused), refused)

    def test_f11_an_untrusted_file_with_no_repository_is_not_a_contradiction(self) -> None:
        self.config.write_text(UNTRUSTED_CONFIG.replace("repo: acme/app" + chr(10), ""), encoding="utf-8")
        self.assertEqual(self.run_cli("--command", "run")[0], 0)


class Check(unittest.TestCase):
    CONFIG = """```sbx-config
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
```
"""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "project").mkdir()
        self.file = self.root / "elsewhere.md"
        self.file.write_text(self.CONFIG, encoding="utf-8")

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sbx_check.main([str(self.root / "project"), *argv], sbx=FakeSandbox(), git=FakeGit(SHA, [SHA]),
                                  gh=FakeGitHub(), token="",
                                  det={"repo_visibility": "public", "remote": "https://github.com/acme/app.git"},
                                  drift=lambda: {"status": "aligned", "lines": [], "missing_verbs": []})
        return code, out.getvalue()

    def test_f2_it_checks_the_file_the_fleet_will_use_wherever_it_is(self) -> None:
        code, text = self.run_cli("--config", str(self.file), "--command", "make test")
        self.assertEqual(code, 0, text)
        self.assertIn("sbx_check: ready", text)

    def test_f2_with_no_command_anywhere_the_file_is_not_ready(self) -> None:
        code, text = self.run_cli("--config", str(self.file))
        self.assertEqual(code, 1, text)
        self.assertIn("command", text)

    def test_f2_a_missing_file_says_which(self) -> None:
        code, text = self.run_cli("--config", str(self.root / "nope.md"))
        self.assertEqual(code, 1)
        self.assertIn("nope.md", text)

    def test_f2_one_command_per_box_needs_no_shard_read_and_counts_every_box(self) -> None:
        code, text = self.run_cli("--config", str(self.file), "--command", "a", "--command", "b")
        self.assertEqual(code, 0, text)

    def test_f2_commands_that_exceed_the_quota_are_seen_before_a_run(self) -> None:
        code, text = self.run_cli("--config", str(self.file), *[word for n in "abcdef" for word in ("--command", n)])
        self.assertEqual(code, 1, text)
        self.assertIn("exceed the quota", text)
        self.assertIn("FAIL quota: 0 vCPU running + 48 planned", text)  # the live count too, not only the plan

    def test_f2_a_placeholder_in_a_passed_command_fails(self) -> None:
        self.assertEqual(self.run_cli("--config", str(self.file), "--command", "<set: x>")[0], 1)

    def test_g5_one_command_repeated_per_box_is_ready(self) -> None:
        # speed run, G5: three repeats of one A/B are what a benchmark needs, not a shard request gone wrong
        code, text = self.run_cli("--config", str(self.file), *["--command", "make bench"] * 3)
        self.assertEqual(code, 0, text)
        self.assertNotIn("whole suite", text)

    def test_g6_an_older_file_is_told_the_rerun_that_adds_its_missing_keys(self) -> None:
        older = "\n".join(line for line in self.CONFIG.splitlines() if not line.startswith(("target:", "boxes:", "clone:")))
        self.file.write_text(older + "\n", encoding="utf-8")
        code, text = self.run_cli("--config", str(self.file), "--command", "make test")
        self.assertEqual(code, 1, text)
        self.assertIn("FAIL config-keys: add target, boxes, clone to the sbx-config block, or rerun sbx_onboard.py", text)


class Onboard(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("sbxlib.adapters.project_scan.in_dir", lambda _root: lambda *a, **k: done(127)):
            code = sbx_onboard.main([str(self.project), *argv])
        return code, out.getvalue()

    def test_f1_the_adoption_file_can_live_outside_a_project_that_must_stay_untouched(self) -> None:
        target = self.root / "mine" / "sbx.md"
        code, text = self.run_cli("--config", str(target))
        self.assertEqual(code, 0, text)
        self.assertIn("own_work", parse_config(target.read_text(encoding="utf-8")))
        self.assertEqual([path.name for path in self.project.iterdir()], ["pyproject.toml"])

    def test_g6_a_rerun_on_an_older_file_adds_what_sbx_check_asks_for_and_keeps_the_rest(self) -> None:
        older = self.root / "older.md"
        older.write_text("\n".join(line for line in Check.CONFIG.splitlines()
                                   if not line.startswith(("target:", "boxes:", "clone:", "on_timeout:"))) + "\n", encoding="utf-8")
        code, text = self.run_cli("--config", str(older))
        self.assertEqual(code, 0, text)
        config = parse_config(older.read_text(encoding="utf-8"))
        self.assertEqual([config.get(key) for key in ("target", "on_timeout", "own_work", "repo")], ["cloud", "delete", "trusted", "acme/app"])
        self.assertTrue(config.get("boxes") and config.get("clone"))

    def test_f1_the_recipe_lands_beside_it(self) -> None:
        self.run_cli("--config", str(self.root / "mine" / "sbx.md"))
        self.assertTrue((self.root / "mine" / "sbx-recipe.md").is_file())

    def test_f5_the_generated_table_carries_the_version_qualified_state(self) -> None:
        with mock.patch("sbxlib.adapters.project_scan.in_dir", lambda _root: lambda *a, **k: done(127)):
            rows = recommend(detect(self.project), sbx_onboard.use_case_states())
        row = next(row for row in rows if row["slug"] == "testcontainers")
        self.assertIn("0.51.0", row["state"])

    def test_f5_a_note_with_no_qualifier_keeps_its_plain_state(self) -> None:
        self.assertEqual(sbx_onboard.use_case_states()["browser-e2e"], "tried-once")  # targeted-tests ran twice since


if __name__ == "__main__":
    unittest.main()
