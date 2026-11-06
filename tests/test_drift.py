"""Drift: the installed cloud CLI against the snapshot. An unknown is never read as aligned."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import helpers  # noqa: F401

import sbx_drift
from sbxlib.adapters.gh_cli import release_tags
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.app.drift import check, collect, take_snapshot
from sbxlib.domain.drift import VERBS, compare, is_valid_snapshot, newest_stable, parse_help, version_tuple
from sbxlib.ports import CommandTimeout, Done

HELP = """Description:
  x

Usage:
  sbx create [flags]

Available Commands:
  gemini         Create a sandbox for gemini

Flags:
      --allow-network strings   Network pattern
  -e, --env stringArray         Set a variable
  -h, --help                    help
      --no-progress             Quiet
"""
TOP = """Sandbox Commands:
  cp          Copy
  create      Create
  exec        Execute

Management Commands:
  secret      Manage
"""


def surface_help(verbs: dict[str, str] | None = None, top: str = TOP) -> dict[str, str]:
    return {"": top, **(verbs if verbs is not None else {"rm": HELP})}


class FakeCli:
    def __init__(self, helps: dict[str, str], version: str | None = "0.51.0") -> None:
        self.helps, self._version, self.asked = helps, version, []

    def version(self) -> str | None:
        return self._version

    def help(self, words: tuple[str, ...]) -> str | None:
        self.asked.append(words)  # type: ignore[attr-defined]
        return self.helps.get(" ".join(words))


def snapshot(**changes: Any) -> dict[str, Any]:
    base = {"version": "0.51.0", "cloud_commands": ["cp", "create", "exec", "secret"], "verbs": {"rm": parse_help(HELP)}}
    return {**base, **changes}


def latest() -> str | None:
    return "v0.51.0"


class Parse(unittest.TestCase):
    def test_flags_and_their_short_forms_and_types(self) -> None:
        flags = parse_help(HELP)["flags"]
        self.assertEqual((flags["--allow-network"], flags["--env"], flags["--no-progress"]), ("strings", "-e stringArray", ""))

    def test_commands_are_read_from_any_commands_section(self) -> None:
        self.assertEqual(parse_help(TOP)["commands"], ["cp", "create", "exec", "secret"])

    def test_newest_stable_ignores_nightlies_and_compares_numerically(self) -> None:
        self.assertEqual(newest_stable(["v0.9.0", "v0.51.0", "v0.52.0-rc1", "nightly"]), "v0.51.0")

    def test_no_stable_tag_is_none(self) -> None:
        self.assertIsNone(newest_stable(["nightly"]))

    def test_version_tuple(self) -> None:
        self.assertEqual(version_tuple("v0.51.0"), (0, 51, 0))

    def test_the_verbs_cover_what_the_adapter_calls(self) -> None:
        self.assertLessEqual({"create", "exec", "cp", "rm", "ls", "secret set", "secret rm", "secret ls"}, set(VERBS))


class Compare(unittest.TestCase):
    def live(self, **changes: Any) -> dict[str, Any]:
        return {"cloud_commands": ["cp", "create", "exec", "secret"], "verbs": {"rm": parse_help(HELP)}, **changes}

    def test_equal_surfaces_are_empty(self) -> None:
        self.assertEqual(compare(snapshot(), self.live()), {"removed": [], "changed": [], "missing_verbs": []})

    def test_a_removed_flag(self) -> None:
        gone = parse_help(HELP.replace("      --no-progress             Quiet\n", ""))
        self.assertEqual(compare(snapshot(), self.live(verbs={"rm": gone}))["removed"], ["rm --no-progress"])

    def test_a_changed_flag_type(self) -> None:
        moved = parse_help(HELP.replace("--allow-network strings  ", "--allow-network string   "))
        self.assertEqual(compare(snapshot(), self.live(verbs={"rm": moved}))["changed"], ["rm --allow-network"])

    def test_a_new_flag_is_not_drift(self) -> None:
        more = parse_help(HELP + "      --extra             New\n")
        self.assertEqual(compare(snapshot(), self.live(verbs={"rm": more})), {"removed": [], "changed": [], "missing_verbs": []})

    def test_a_verb_whose_help_failed_is_missing(self) -> None:
        self.assertEqual(compare(snapshot(), self.live(verbs={"rm": None}))["missing_verbs"], ["rm"])

    def test_a_cloud_command_gone_is_missing_even_if_its_help_answers(self) -> None:
        found = compare(snapshot(), self.live(cloud_commands=["create", "exec", "secret"]))
        self.assertEqual(found["missing_verbs"], ["cp"])


class Valid(unittest.TestCase):
    def test_a_good_snapshot(self) -> None:
        self.assertTrue(is_valid_snapshot(snapshot()))

    def test_malformed_snapshots(self) -> None:
        for bad in ({"verbs": {"rm": None}, "version": "1"}, {"verbs": ["rm"], "version": "1"}, {"verbs": {}, "version": "1"},
                    {"verbs": {"rm": parse_help(HELP)}}, [], None, {"verbs": {"rm": {}}, "version": "1"}):
            self.assertFalse(is_valid_snapshot(bad), bad)


class Check(unittest.TestCase):
    TEXT = json.dumps(snapshot())

    def run_check(self, helps: dict[str, str] | None = None, version: str | None = "0.51.0", tag: Any = latest, text: str | None = None) -> tuple[int, dict[str, Any]]:
        return check(FakeCli(surface_help() if helps is None else helps, version), tag, self.TEXT if text is None else text)

    def test_aligned(self) -> None:
        code, report = self.run_check()
        self.assertEqual((code, report["status"]), (0, "aligned"))

    def test_no_network_is_never_aligned(self) -> None:
        code, report = self.run_check(tag=lambda: None)
        self.assertEqual(code, 3)
        self.assertNotEqual(report["status"], "aligned")

    def test_a_missing_sbx_is_exit_three(self) -> None:
        self.assertEqual(self.run_check(version=None)[0], 3)

    def test_an_unreadable_snapshot_is_exit_three(self) -> None:
        self.assertEqual(self.run_check(text="not json")[0], 3)

    def test_an_absent_snapshot_is_exit_three(self) -> None:
        self.assertEqual(check(FakeCli(surface_help()), latest, None)[0], 3)

    def test_an_empty_verbs_snapshot_compares_nothing_and_is_exit_three(self) -> None:
        self.assertEqual(self.run_check(text=json.dumps(snapshot(verbs={})))[0], 3)

    def test_a_hung_cli_is_exit_three(self) -> None:
        class Hung(FakeCli):
            def help(self, words: tuple[str, ...]) -> str | None:
                raise CommandTimeout("sbx")

        self.assertEqual(check(Hung({}), latest, self.TEXT)[0], 3)

    def test_a_hung_release_read_is_exit_three(self) -> None:
        def hung() -> str | None:
            raise CommandTimeout("gh")

        self.assertEqual(self.run_check(tag=hung)[0], 3)

    def test_losing_cloud_commands_is_drift(self) -> None:
        code, report = self.run_check(surface_help(top=TOP.replace("  cp          Copy\n", "")))
        self.assertEqual((code, report["missing_verbs"]), (4, ["cp"]))

    def test_an_installed_older_than_the_snapshot_is_drift(self) -> None:
        self.assertEqual(self.run_check(version="0.50.1")[0], 4)

    def test_a_newer_release_than_the_snapshot_is_drift(self) -> None:
        code, report = self.run_check(tag=lambda: "v0.52.0")
        self.assertEqual(code, 4)
        self.assertTrue(report["version_behind"])

    def test_drift_found_wins_over_no_network(self) -> None:
        self.assertEqual(self.run_check(version="0.50.1", tag=lambda: None)[0], 4)

    def test_the_cloud_surface_is_what_is_walked(self) -> None:
        cli = FakeCli(surface_help())
        check(cli, latest, self.TEXT)
        self.assertIn((), cli.asked)  # type: ignore[attr-defined]
        self.assertIn(("rm",), cli.asked)  # type: ignore[attr-defined]


class Snapshot(unittest.TestCase):
    def test_a_snapshot_holds_version_and_cloud_surface(self) -> None:
        data = take_snapshot(FakeCli(surface_help()), ("rm",))
        self.assertEqual((data["version"], data["cloud_commands"], sorted(data["verbs"])), ("0.51.0", ["cp", "create", "exec", "secret"], ["rm"]))

    def test_a_failed_help_walk_writes_nothing(self) -> None:
        with self.assertRaises(RuntimeError):
            take_snapshot(FakeCli(surface_help({})), ("rm",))

    def test_no_version_writes_nothing(self) -> None:
        with self.assertRaises(RuntimeError):
            take_snapshot(FakeCli(surface_help(), None), ("rm",))

    def test_collect_records_a_failed_verb_as_none(self) -> None:
        self.assertEqual(collect(FakeCli(surface_help({})), ("rm",))["verbs"], {"rm": None})

    def test_the_real_adapter_asks_the_cloud_help(self) -> None:
        asked: list[Sequence[str]] = []

        def run(argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
            asked.append(list(argv))
            return Done(0, "x")

        SbxCli(run).help(("rm",))
        self.assertEqual(asked, [["sbx", "--cloud", "rm", "--help"]])


class Latest(unittest.TestCase):
    """`drift.yml` trusts these exit codes: review 2, M6, an uncaught error exited 1 and the job passed with no issue."""

    def run_latest(self, text: str, gh: Any) -> int:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text(text, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                return sbx_drift.main(["latest", "--snapshot", str(path)], gh=gh)

    GOOD = staticmethod(lambda *_a, **_k: Done(0, '[{"tagName": "v0.51.0"}]'))

    def test_an_unreadable_snapshot_is_exit_three(self) -> None:
        self.assertEqual(self.run_latest("not json", self.GOOD), 3)

    def test_a_snapshot_with_no_version_is_exit_three(self) -> None:
        self.assertEqual(self.run_latest("{}", self.GOOD), 3)

    def test_a_snapshot_with_an_odd_version_is_exit_three(self) -> None:
        self.assertEqual(self.run_latest('{"version": 7}', self.GOOD), 3)

    def test_a_hung_gh_is_exit_three(self) -> None:
        def hung(*_a: Any, **_k: Any) -> Done:
            raise CommandTimeout("gh did not answer")

        self.assertEqual(self.run_latest(self.snapshot("0.51.0"), hung), 3)

    @staticmethod
    def snapshot(version: str) -> str:
        return json.dumps({**json.loads(sbx_drift.SNAPSHOT.read_text(encoding="utf-8")), "version": version})

    def test_aligned_and_behind_stay_zero_and_four(self) -> None:
        self.assertEqual(self.run_latest(self.snapshot("0.51.0"), self.GOOD), 0)
        self.assertEqual(self.run_latest(self.snapshot("0.50.0"), self.GOOD), 4)

    def test_a_snapshot_with_no_commands_is_exit_three(self) -> None:
        self.assertEqual(self.run_latest('{"version": "9.9.9"}', self.GOOD), 3)

    def test_a_snapshot_ahead_of_every_release_is_no_alignment(self) -> None:
        self.assertEqual(self.run_latest(self.snapshot("9.9.9"), self.GOOD), 4)


class Releases(unittest.TestCase):
    def test_tags_are_read(self) -> None:
        self.assertEqual(release_tags(lambda *a, **k: Done(0, '[{"tagName": "v1.0.0"}]')), ["v1.0.0"])

    def test_no_gh_is_none(self) -> None:
        self.assertIsNone(release_tags(lambda *a, **k: Done(127)))

    def test_garbage_is_none(self) -> None:
        self.assertIsNone(release_tags(lambda *a, **k: Done(0, "x")))



if __name__ == "__main__":
    unittest.main()
