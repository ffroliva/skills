"""Adapters over fake processes and real files."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from fakes import FakeGit, FakeGitHub, FakeSandbox
from helpers import REPO, SHA, result_tar

from sbxlib.adapters import process
from sbxlib.adapters.clock import new_run_id
from sbxlib.adapters.files import RunDirectory, protected_paths
from sbxlib.adapters.gh_cli import GhCli
from sbxlib.adapters.git_cli import GitCli
from sbxlib.adapters.junit_xml import UnreadableJunit, read_dir
from sbxlib.adapters.sbx_cli import CREATE_TIMEOUT_S, SbxCli, create_flags
from sbxlib.domain.fleet import RunRequest
from sbxlib.domain.junit import Outcome
from sbxlib.domain.profile import OutputPolicy
from sbxlib.ports import CommandTimeout, Done, HostError, Unreadable


class Process(unittest.TestCase):
    def test_a_missing_executable_is_rc_127(self) -> None:
        self.assertEqual(process.run_command(["no-such-tool-here"]).rc, 127)

    def test_another_start_failure_is_rc_126(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=PermissionError("denied")):
            self.assertEqual(process.run_command([sys.executable]).rc, 126)

    def test_a_timeout_is_the_port_exception(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)), self.assertRaises(CommandTimeout):
            process.run_command([sys.executable])

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_every_process_starts_with_no_window(self) -> None:
        done = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            process.run_command([sys.executable])
        self.assertEqual(run.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_no_argv_passes_through_a_shell(self) -> None:
        done = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            process.run_command([sys.executable])
        self.assertNotIn("shell", run.call_args.kwargs)


class ToolLookup(unittest.TestCase):
    """review-3, M4: on Windows the working directory comes before PATH, and `gh` and `sbx` inherit credentials."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        hidden = mock.patch.dict(os.environ)  # an operator's shell does not set the variable that would hide this: review-3 M4
        hidden.start()
        self.addCleanup(hidden.stop)
        os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)

    def plant(self, name: str) -> None:
        if sys.platform == "win32":
            shutil.copy(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe", self.root / f"{name}.exe")
        else:
            path = self.root / name
            path.write_text("#!/bin/sh\necho planted\n", encoding="utf-8")
            path.chmod(0o755)

    def test_a_tool_in_the_working_directory_never_runs(self) -> None:
        self.plant("git")
        found = process.run_command(["git", "--version"])
        self.assertEqual(found.rc, 0, found)
        self.assertIn("git version", found.out)

    def test_a_tool_only_in_the_working_directory_is_not_found(self) -> None:
        self.plant("sbx-planted-tool")
        self.assertEqual(process.run_command(["sbx-planted-tool"]).rc, 127)

    def test_a_relative_entry_on_path_does_not_count(self) -> None:
        self.plant("sbx-planted-tool")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join((".", "", os.environ["PATH"]))}):
            self.assertEqual(process.run_command(["sbx-planted-tool"]).rc, 127)

    def test_an_absolute_path_still_runs(self) -> None:
        self.assertEqual(process.run_command([sys.executable, "--version"]).rc, 0)


class ProtectedPaths(unittest.TestCase):
    """review-3, M8: `docs/reference/trust.md` promises the file at its real path, and no test made a link."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "real").mkdir()
        (self.root / "real" / "sbx.md").write_text("x", encoding="utf-8")
        link = self.root / "docs"
        if sys.platform == "win32":  # a junction needs no privilege, where a symlink does
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.root / "real")], check=True, capture_output=True)
            self.addCleanup(os.rmdir, link)
        else:
            link.symlink_to(self.root / "real")

    def test_a_file_behind_a_link_is_protected_at_its_real_path(self) -> None:
        self.assertIn("real/sbx.md", protected_paths(self.root / "docs" / "sbx.md"))

    def test_it_is_protected_as_written_too(self) -> None:
        other = self.root / "docs" / "other.md"
        other.write_text("x", encoding="utf-8")
        self.assertIn("docs/other.md", protected_paths(other))
        self.assertIn("real/other.md", protected_paths(other))


class Environment(unittest.TestCase):
    def test_a_named_variable_never_reaches_the_child(self) -> None:
        # review 2, low 5: `sbx` inherited GH_TOKEN and the clone secret from the fleet
        code = "import os; print(os.environ.get('SBX_T1', 'absent'), os.environ.get('SBX_T2', 'absent'))"
        with mock.patch.dict(os.environ, {"SBX_T1": "one", "SBX_T2": "two"}):
            done = process.without_env(("SBX_T1",))([sys.executable, "-c", code])
        self.assertEqual(done.out.split(), ["absent", "two"])

    def test_a_name_in_lower_case_still_goes(self) -> None:
        code = "import os; print(os.environ.get('SBX_T3', 'absent'))"
        with mock.patch.dict(os.environ, {"SBX_T3": "three"}):
            self.assertEqual(process.without_env(("sbx_t3",))([sys.executable, "-c", code]).out.strip(), "absent")


class Sbx(unittest.TestCase):
    def setUp(self) -> None:
        self.request = RunRequest(REPO, SHA, ("x",), "acme", "k3f9", allow=("pypi.org",), env_names=("TOKEN",))
        self.fake = FakeSandbox()
        self.cli = SbxCli(self.fake)

    def test_every_box_gets_a_ttl_and_delete_on_timeout(self) -> None:
        flags = create_flags(self.request)
        self.assertEqual(flags[flags.index("--ttl") + 1], "30m")
        self.assertEqual(flags[flags.index("--on-timeout") + 1], "delete")

    def test_egress_is_the_default_plus_the_named_hosts(self) -> None:
        flags = create_flags(self.request)
        self.assertEqual([flags[i + 1] for i, word in enumerate(flags) if word == "--allow-network"],
                         ["github.com", "**.githubusercontent.com", "pypi.org"])

    def test_an_env_is_passed_by_bare_name_only(self) -> None:
        flags = create_flags(self.request)
        self.assertEqual(flags[flags.index("-e") + 1], "TOKEN")

    def test_a_real_create_passes_the_snapshot(self) -> None:
        self.assertEqual(self.cli.create("acme-shards-01-k3f9", self.request).rc, 0)

    def test_create_runs_with_no_input_allowlist_and_timeout(self) -> None:
        runner = mock.Mock(return_value=Done(0))
        SbxCli(runner).create("acme-shards-01-k3f9", self.request)
        argv, stdin, timeout = runner.call_args_list[0].args
        self.assertEqual(argv[:4], ["sbx", "--no-input", "--cloud", "create"])
        self.assertEqual([argv[i + 1] for i, word in enumerate(argv) if word == "--allow-network"],
                         ["github.com", "**.githubusercontent.com", "pypi.org"])
        self.assertIsNone(stdin)
        self.assertEqual(timeout, CREATE_TIMEOUT_S)

    def test_the_fake_refuses_a_flag_sbx_does_not_have(self) -> None:
        self.assertIn("unknown flag", self.fake(["sbx", "--cloud", "rm", "--purge", "x"]).err)
        self.assertIn("unknown flag", self.fake(["sbx", "--bogus", "--cloud", "ls", "--json"]).err)

    def test_the_fake_dispatches_every_verb_with_no_input_and_preserves_calls(self) -> None:
        box = "acme-shards-01-k3f9"
        self.assertEqual(self.cli.create(box, self.request).rc, 0)
        self.assertEqual([(row.name, row.cpus) for row in self.cli.boxes()], [(box, 8)])
        self.assertEqual(self.cli.run(box, "true").rc, 0)
        self.assertEqual(self.cli.upload("local.sh", box, "/home/agent/run.sh").rc, 0)
        self.assertEqual(self.cli.download(box, "/home/agent/out.txt", "local.txt").rc, 0)
        self.assertEqual(self.cli.account_policy().mode, "deny-all")
        self.assertEqual(self.cli.set_scoped(box, "github", "v1").rc, 0)
        self.assertEqual(self.cli.set_scoped(box, "custom:api.example.com:KEY", "v2").rc, 0)
        self.assertEqual(len(self.cli.secrets()), 2)
        self.assertEqual(self.cli.remove_scoped(box, "github").rc, 0)
        self.assertEqual(self.cli.remove_scoped(box, "custom:api.example.com:KEY").rc, 0)
        self.assertEqual(self.cli.remove(box).rc, 0)
        self.assertTrue(all(call[:2] == ["--no-input", "--cloud"] for call in self.fake.calls))
        self.assertEqual(self.fake.verbs(), ["create", "ls", "exec", "cp", "cp", "policy ls",
                                             "secret set", "secret set-custom", "secret ls", "secret rm", "secret rm", "rm"])

    def test_a_secret_value_goes_on_stdin(self) -> None:
        self.cli.set_scoped("box", "github", "VALUE")
        self.assertEqual(self.fake.stdins[-1], "VALUE")
        self.assertNotIn("VALUE", " ".join(self.fake.calls[-1]))

    def test_box_rows_are_read(self) -> None:
        self.cli.create("acme-shards-01-k3f9", self.request)
        self.assertEqual([(row.name, row.cpus) for row in self.cli.boxes()], [("acme-shards-01-k3f9", 8)])

    def test_gate3_recorded_cloud_shape_is_read(self) -> None:
        # Sanitized row shape observed in gate3/g7/bad-repo.log; volatile IDs and image digest are removed.
        fixture = Path(__file__).parent / "fixtures" / "sbx" / "gate3-cloud-list.json"
        self._listing("ls", Done(0, fixture.read_text(encoding="utf-8")))
        self.assertEqual([(row.name, row.cpus) for row in self.cli.boxes()], [("recorded-box", 4)])

    def test_local_sandboxes_object_shape_is_read(self) -> None:
        self._listing("ls", Done(0, json.dumps({"sandboxes": [{"name": "local-box", "cpus": 2}]})))
        self.assertEqual([(row.name, row.cpus) for row in self.cli.boxes()], [("local-box", 2)])

    def test_unknown_box_shape_is_unreadable(self) -> None:
        self._listing("ls", Done(0, json.dumps({"items": []})))
        with self.assertRaises(Unreadable):
            self.cli.boxes()

    def _listing(self, verb: str, answer: Done) -> None:
        self.fake.fail[verb] = answer

    def test_a_failed_listing_is_unreadable_not_empty(self) -> None:
        self._listing("ls", Done(1, "", "boom"))
        with self.assertRaises(Unreadable):
            self.cli.boxes()

    def test_non_json_is_unreadable(self) -> None:
        self._listing("ls", Done(0, "NAME STATUS"))
        with self.assertRaises(Unreadable):
            self.cli.boxes()

    def test_a_null_is_unreadable(self) -> None:
        self._listing("ls", Done(0, "null"))
        with self.assertRaises(Unreadable):
            self.cli.boxes()

    def test_a_row_with_no_vcpu_figure_is_unreadable_not_free(self) -> None:
        self._listing("ls", Done(0, json.dumps([{"name": "x"}])))
        with self.assertRaises(Unreadable):
            self.cli.boxes()

    def test_a_failed_secret_listing_is_unreadable(self) -> None:
        self._listing("secret ls", Done(1, "", "boom"))
        with self.assertRaises(Unreadable):
            self.cli.secrets()

    def test_secret_rows_use_scope_as_the_box(self) -> None:
        self._listing("secret ls", Done(0, json.dumps({"secrets": [{"scope": "b", "name": "httpbin-org", "type": "service"}]})))
        self.assertEqual([(row.name, row.scope) for row in self.cli.secrets()], [("httpbin-org", "b")])

    def test_a_custom_rows_hosts_are_kept(self) -> None:
        # gate 8, real: {"scope": ..., "name": "httpbin-org", "secret_type": "custom", "hosts": ["httpbin.org"], ...}
        row = {"scope": "global", "name": "httpbin-org", "type": "service", "secret_type": "custom", "hosts": ["httpbin.org"]}
        self._listing("secret ls", Done(0, json.dumps({"secrets": [row]})))
        self.assertEqual(self.cli.secrets()[0].hosts, ("httpbin.org",))

    def test_the_custom_secrets_list_is_read_as_well(self) -> None:
        self._listing("secret ls", Done(0, json.dumps({"secrets": [], "custom_secrets": [{"scope": "global", "name": "x", "hosts": ["a.b"]}]})))
        self.assertEqual([row.name for row in self.cli.secrets()], ["x"])

    def test_an_environment_only_secret_is_never_read_as_none(self) -> None:
        self._listing("secret ls", Done(0, json.dumps({"secrets": [], "custom_secrets": [], "env_only_count": 2})))
        self.assertEqual([(row.name, row.scope) for row in self.cli.secrets()], [("env-only", "global")])

    def test_the_live_shape_of_an_account_lists_one_global(self) -> None:
        # sbx 0.51.0, `secret ls --json` with no --cloud; `--cloud secret ls --json` has only ever printed {"secrets": []}
        live ={"secrets": [{"scope": "global", "type": "service", "name": "anthropic", "secret": "(oauth configured)"}],
                "custom_secrets": [], "shadowed_services": [], "env_only_count": 0}
        self._listing("secret ls", Done(0, json.dumps(live)))
        self.assertEqual([(row.name, row.scope, row.hosts) for row in self.cli.secrets()], [("anthropic", "global", ())])

    def test_a_version_is_parsed(self) -> None:
        self.assertEqual(self.cli.version(), "0.51.0")

    def test_no_version_is_none(self) -> None:
        self.fake.version_text = "garbage"
        self.assertIsNone(self.cli.version())


class Git(unittest.TestCase):
    def test_a_tip_is_on_the_remote(self) -> None:
        self.assertTrue(GitCli(FakeGit(SHA, [SHA])).on_remote(SHA, "origin"))

    def test_a_commit_below_a_tip_is_on_the_remote(self) -> None:
        self.assertTrue(GitCli(FakeGit(SHA, ["b" * 40], below=["b" * 40])).on_remote(SHA, "origin"))

    def test_an_unpushed_commit_is_not(self) -> None:
        self.assertFalse(GitCli(FakeGit(SHA, ["b" * 40], below=["c" * 40])).on_remote(SHA, "origin"))

    def test_an_unreadable_remote_is_not_pushed(self) -> None:
        self.assertFalse(GitCli(FakeGit(SHA, [SHA], readable=False)).on_remote(SHA, "origin"))

    def test_an_empty_sha_is_not_pushed(self) -> None:
        self.assertFalse(GitCli(FakeGit("", [""])).on_remote("", "origin"))

    def test_pull_refs_are_not_counted_a_clone_cannot_see_them(self) -> None:
        fake = mock.Mock(side_effect=FakeGit(SHA, [SHA]))
        GitCli(fake).on_remote(SHA, "origin")
        self.assertEqual(fake.call_args_list[0].args[0], ["git", "ls-remote", "--heads", "--tags", "origin"])


class GitHub(unittest.TestCase):
    def test_with_no_token_nothing_is_called(self) -> None:
        fake = FakeGitHub({"repos/a/b": {}})
        with self.assertRaises(HostError):
            GhCli(fake, "").repository("a/b")
        self.assertEqual(fake.calls, [])

    def test_the_token_is_never_in_argv_or_stdin(self) -> None:
        fake = FakeGitHub({"repos/a/b": {}})
        GhCli(fake, "SECRET").repository("a/b")
        self.assertNotIn("SECRET", " ".join(fake.calls[0]))
        self.assertIsNone(fake.stdins[0])

    def test_an_http_status_is_kept(self) -> None:
        with self.assertRaises(HostError) as caught:
            GhCli(FakeGitHub({"repos/a/b": 403}), "t").repository("a/b")
        self.assertEqual(caught.exception.status, 403)

    def test_the_token_is_scrubbed_from_an_error(self) -> None:
        def echo(argv: Any, stdin: str | None = None, timeout: int = 60) -> Done:
            return Done(1, "", "bad token SECRET (HTTP 401)")

        with self.assertRaises(HostError) as caught:
            GhCli(echo, "SECRET").repository("a/b")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_a_team_404_is_not_a_member(self) -> None:
        self.assertFalse(GhCli(FakeGitHub({}), "t").in_team("acme/core", "bob"))

    def test_a_pending_team_invite_is_not_a_member(self) -> None:
        fake = FakeGitHub({"orgs/acme/teams/core/memberships/bob": {"state": "pending"}})
        self.assertFalse(GhCli(fake, "t").in_team("acme/core", "bob"))

    def test_an_active_member_is(self) -> None:
        fake = FakeGitHub({"orgs/acme/teams/core/memberships/bob": {"state": "active"}})
        self.assertTrue(GhCli(fake, "t").in_team("acme/core", "bob"))

    def test_a_login_is_quoted_into_the_path(self) -> None:
        fake = FakeGitHub({"repos/a/b/collaborators/dependabot%5Bbot%5D/permission": {"role_name": "write"}})
        self.assertEqual(GhCli(fake, "t").role("a/b", "dependabot[bot]"), "write")


class Results(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "run"
        self.files = RunDirectory(self.root)

    def _read(self, tar: bytes, policy: OutputPolicy = OutputPolicy.EVERYTHING) -> Any:
        Path(self.files.archive("b")).write_bytes(tar)
        return self.files.read_result(1, "b", 1.0, policy)

    def test_a_good_archive_is_read(self) -> None:
        result = self._read(result_tar())
        self.assertEqual((result.rc, result.tests, result.fatal), (0, 2, ""))

    def test_large_junit_token_does_not_hide_later_failures(self) -> None:
        junit = ('<testsuite><testcase classname="c" name="first"/>'
                 '<testcase classname="c" name="large"><failure message="' + "x" * 6_000_000 + '"/></testcase>'
                 '<testcase classname="c" name="last"><failure message="boom"/></testcase></testsuite>')
        result = self._read(result_tar(junit=junit))
        self.assertEqual((result.rc, result.tests, result.failed), (0, 3, 2), result.fatal)

    def test_rc_comes_from_the_box(self) -> None:
        self.assertEqual(self._read(result_tar(rc="7")).rc, 7)

    def test_a_broken_archive_is_a_fatal_not_a_crash(self) -> None:
        self.assertIn("invalid result archive", self._read(b"not a tar").fatal)

    def test_a_path_escape_is_refused(self) -> None:
        result = self._read(result_tar(extra={"../../escaped.txt": "x"}))
        self.assertIn("invalid result archive", result.fatal)
        self.assertFalse((self.root.parent / "escaped.txt").exists())

    def test_results_only_leaves_logs_behind(self) -> None:
        self._read(result_tar(extra={"out/run.log": "secret-looking", "out/tool.sh": "x"}), OutputPolicy.RESULTS_ONLY)
        self.assertEqual(sorted(p.name for p in (self.root / "b" / "out").iterdir()), ["junit.xml", "rc"])

    def test_a_trusted_run_keeps_its_logs(self) -> None:
        self._read(result_tar(extra={"out/run.log": "x"}))
        self.assertTrue((self.root / "b" / "out" / "run.log").exists())

    def test_a_document_type_in_junit_is_refused(self) -> None:
        bomb = '<!DOCTYPE x [<!ENTITY a "b">]><testsuite><testcase name="&a;"/></testsuite>'
        self.assertIn("invalid result archive", self._read(result_tar(junit=bomb)).fatal)

    def test_utf16_document_type_in_untrusted_results_is_refused(self) -> None:
        xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE t [<!ENTITY a "x">]>'
               '<testsuite><testcase name="&a;"/></testsuite>').encode("utf-16-le")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for name, data in (("out/rc", b"0\n"), ("out/junit.xml", xml)):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        result = self._read(buffer.getvalue(), OutputPolicy.RESULTS_ONLY)
        self.assertIn("invalid result archive", result.fatal)

    def test_a_folder_with_results_is_reported(self) -> None:
        self.assertFalse(self.files.has_results())
        (self.root / "old").mkdir()
        self.assertTrue(self.files.has_results())

    def _gzip_tar(self, build: Any) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
            build(tar)
        return buffer.getvalue()

    def test_a_pax_header_cannot_take_more_than_the_limit(self) -> None:
        # review 2, M1: a 0.87 MB archive took the heap to 800 MB, because getmembers() read it before any limit
        def build(tar: tarfile.TarFile) -> None:
            info = tarfile.TarInfo("out/rc")
            info.size = 1
            info.pax_headers = {"comment": "x" * 500_000}
            tar.addfile(info, io.BytesIO(b"0"))

        with mock.patch("sbxlib.adapters.files.MAX_UNPACKED_BYTES", 100_000):
            self.assertIn("invalid result archive", self._read(self._gzip_tar(build)).fatal)

    def test_an_ignored_member_counts_against_the_limit(self) -> None:
        # review 2, M3: `archive size off` survived, and the old sum looked only at members it kept
        def build(tar: tarfile.TarFile) -> None:
            info = tarfile.TarInfo("out/huge.bin")
            info.size = 500_000
            tar.addfile(info, io.BytesIO(b"\0" * 500_000))

        with mock.patch("sbxlib.adapters.files.MAX_UNPACKED_BYTES", 100_000):
            self.assertIn("over 100000 bytes", self._read(self._gzip_tar(build), OutputPolicy.RESULTS_ONLY).fatal)

    def test_a_kept_member_counts_against_the_limit(self) -> None:
        with mock.patch("sbxlib.adapters.files.MAX_UNPACKED_BYTES", 2_000):
            self.assertIn("over 2000 bytes", self._read(result_tar(extra={"out/big.log": "x" * 5_000})).fatal)

    def test_a_corrupt_compressed_stream_is_a_fatal_not_a_crash(self) -> None:
        good = bytearray(result_tar())
        good[20:40] = b"\xff" * 20
        self.assertIn("invalid result archive", self._read(bytes(good)).fatal)

    def test_running_out_of_memory_on_a_result_is_a_fatal_not_a_crash(self) -> None:
        with mock.patch("sbxlib.adapters.files.read_file", side_effect=MemoryError("out")):
            self.assertIn("invalid result archive", self._read(result_tar()).fatal)

    def test_too_many_members_are_refused(self) -> None:
        with mock.patch("sbxlib.adapters.files.MAX_MEMBERS", 2):
            result = self._read(result_tar(extra={"out/a.log": "x", "out/b.log": "x", "out/c.log": "x"}))
        self.assertIn("over 2 files", result.fatal)

    def test_an_archive_too_large_on_disk_is_refused_before_reading(self) -> None:
        with mock.patch("sbxlib.adapters.files.MAX_ARCHIVE_BYTES", 10):
            self.assertIn("invalid result archive", self._read(result_tar()).fatal)

    def test_failed_and_errored_tests_are_counted(self) -> None:
        junit = ('<testsuite><testcase name="a"><failure/></testcase><testcase name="b"><error/></testcase>'
                 '<testcase name="c"><skipped/></testcase><testcase name="d"/></testsuite>')
        result = self._read(result_tar(junit=junit))
        self.assertEqual((result.tests, result.failed, result.skipped), (4, 2, 1))

    def test_test_cases_are_capped_per_run_across_files(self) -> None:
        # review 4, M4: 11 bytes a case, so a few MB of archive held over a GB of host memory
        two = '<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'
        with mock.patch("sbxlib.adapters.files.MAX_CASES", 3):
            result = self._read(result_tar(junit=two, extra={"out/more.xml": two}), OutputPolicy.RESULTS_ONLY)
        self.assertIn("over 3 test cases", result.fatal)

    def test_the_cap_holds_inside_one_file(self) -> None:
        many = "<testsuite>" + '<testcase name="a"/>' * 50 + "</testsuite>"
        with mock.patch("sbxlib.adapters.files.MAX_CASES", 10):
            self.assertIn("over 10 test cases", self._read(result_tar(junit=many)).fatal)

    def test_an_unknown_encoding_is_a_fatal_not_a_crash(self) -> None:
        # review 4, Low 1: a LookupError escaped to the box's catch-all, past `as_data`
        junit = '<?xml version="1.0" encoding="no-such"?><testsuite><testcase name="a"/></testsuite>'
        self.assertIn("invalid result archive", self._read(result_tar(junit=junit)).fatal)

    def test_the_tar_filter_refuses_a_link_out_of_the_folder(self) -> None:
        archive = self.root / "link.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("out/rc")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../../outside"
            tar.addfile(info)
        Path(self.files.archive("b")).write_bytes(archive.read_bytes())
        self.assertIn("invalid result archive", self.files.read_result(1, "b", 1.0, OutputPolicy.RESULTS_ONLY).fatal)


def _member_tar(*members: tuple[str, bytes, int, str]) -> bytes:
    """(name, data, tar type, link name) per member, in order, gzipped."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for name, data, kind, link in members:
            info = tarfile.TarInfo(name)
            info.type, info.linkname, info.size = bytes([kind]), link, len(data) if kind == tarfile.REGTYPE[0] else 0
            tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE[0] else None)
    return buffer.getvalue()


REG, LNK, SYM, CHR, FIFO, DIR = (t[0] for t in (tarfile.REGTYPE, tarfile.LNKTYPE, tarfile.SYMTYPE, tarfile.CHRTYPE,
                                                 tarfile.FIFOTYPE, tarfile.DIRTYPE))


class ArchiveOnAnyPython(unittest.TestCase):
    """Review 4, H1: on Python 3.13.1 a box's archive overwrote a host file through a hard link. The reader must not lean on
    `tarfile`'s filter, so every test here also runs with that filter switched off, which is what an unpatched Python does."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.outside = self.base / "bashrc"
        self.outside.write_text("original", encoding="utf-8")
        self.files = RunDirectory(self.base / "run")
        no_filter = mock.patch.dict(tarfile._NAMED_FILTERS, {"data": tarfile.fully_trusted_filter})  # type: ignore[attr-defined]
        no_filter.start()
        self.addCleanup(no_filter.stop)

    def _read(self, archive: bytes, policy: OutputPolicy = OutputPolicy.RESULTS_ONLY) -> Any:
        Path(self.files.archive("b")).write_bytes(archive)
        return self.files.read_result(1, "b", 1.0, policy)

    def _assert_refused(self, *members: tuple[str, bytes, int, str]) -> None:
        for policy in OutputPolicy:
            with self.subTest(policy=policy.value):
                shutil.rmtree(self.base / "run" / "b", ignore_errors=True)
                self.assertIn("invalid result archive", self._read(_member_tar(*members), policy).fatal)
                self.assertEqual(self.outside.read_text(encoding="utf-8"), "original")
                self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["bashrc", "run"])

    def test_a_hard_link_to_a_host_file_is_refused(self) -> None:
        self._assert_refused(("out/h.xml", b"", LNK, str(self.outside)), ("out/h.xml", b"overwritten by the box", REG, ""))

    def test_a_relative_hard_link_is_refused(self) -> None:
        self._assert_refused(("out/h.xml", b"", LNK, "../../bashrc"), ("out/h.xml", b"overwritten", REG, ""))

    def test_a_symlink_is_refused(self) -> None:
        self._assert_refused(("out/s.xml", b"", SYM, "../../.."), ("out/s.xml/pwned.xml", b"pwned", REG, ""))

    def test_a_device_and_a_fifo_are_refused(self) -> None:
        self._assert_refused(("out/c.xml", b"", CHR, ""))
        self._assert_refused(("out/f.xml", b"", FIFO, ""))

    def test_an_absolute_name_is_refused(self) -> None:
        self._assert_refused((self.outside.as_posix() + ".xml", b"x", REG, ""), ("/out/x.xml", b"x", REG, ""))

    def test_a_parent_step_is_refused(self) -> None:
        self._assert_refused(("out/../../pwned.xml", b"x", REG, ""))
        self._assert_refused(("out/./../../pwned.xml", b"x", REG, ""))

    def test_a_windows_separator_or_drive_is_refused(self) -> None:
        self._assert_refused(("out/..\\..\\pwned.xml", b"x", REG, ""))
        self._assert_refused(("out/C:pwned.xml", b"x", REG, ""))

    def test_the_review_probe_shape_is_refused(self) -> None:
        # r4p/probe_d2.py, the published realpath bypass, cut short: a symlink chain, then a write through it
        self._assert_refused(("out/d.xml", b"", DIR, ""), ("out/a.xml", b"", SYM, "d.xml"),
                             ("out/escape.xml", b"", SYM, "a.xml/../../.."), ("out/escape.xml/pwned.xml", b"pwned", REG, ""))

    def test_a_link_or_parent_step_the_reader_would_not_keep_still_refuses_the_archive(self) -> None:
        # a member results-only never writes reaches only the check: a link anywhere is a hostile box, not a log to skip
        run = self.base / "run"
        for hostile in (("out/log", b"", SYM, "../../bashrc"), ("out/log", b"", LNK, str(self.outside)),
                        ("out/../../log", b"x", REG, "")):
            with self.subTest(member=hostile[0], kind=hostile[2]):
                self._assert_refused(("out/rc", b"0\n", REG, ""), hostile)
                self.assertFalse(os.path.lexists(run / "b" / "out" / "log"))
                self.assertFalse(os.path.lexists(run / "log"))
                self.assertEqual(sorted(p.name for p in run.iterdir()), ["b", "b.tgz"])

    def test_a_box_folder_that_is_a_link_out_is_refused(self) -> None:
        elsewhere, link = self.base / "elsewhere", self.base / "run" / "b" / "out"
        elsewhere.mkdir()
        link.parent.mkdir(parents=True)
        if sys.platform == "win32":  # a junction needs no privilege, where a symlink does
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(elsewhere)], check=True, capture_output=True)
            self.addCleanup(os.rmdir, link)
        else:
            link.symlink_to(elsewhere)
        self.assertIn("outside the run folder", self._read(result_tar()).fatal)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_regular_files_still_come_back(self) -> None:
        result = self._read(_member_tar(("out", b"", DIR, ""), ("out/rc", b"0\n", REG, ""),
                                        ("out/sub/junit.xml", b'<testsuite><testcase name="a"/></testsuite>', REG, "")))
        self.assertEqual((result.rc, result.tests, result.fatal), (0, 1, ""))


class Junit(unittest.TestCase):
    def test_results_are_read_per_box_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "box-01" / "out").mkdir(parents=True)
            (root / "box-01" / "out" / "junit.xml").write_text(
                '<testsuite><testcase classname="t.A" file="t/a.py" name="x" time="1.5"><failure/></testcase></testsuite>', encoding="utf-8")
            cases = read_dir(root)
        self.assertEqual([(c.box, c.classname, c.unit, c.seconds, c.outcome) for c in cases],
                         [("box-01", "t.A", "t/a.py", 1.5, Outcome.FAILED)])

    def test_broken_xml_is_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "a.xml").write_text("<testsuite>", encoding="utf-8")
            with self.assertRaises(UnreadableJunit):
                read_dir(Path(folder))


class RunIds(unittest.TestCase):
    def test_a_run_id_has_the_shape_the_sweep_matches(self) -> None:
        self.assertRegex(new_run_id(), r"^[a-z0-9]{4}$")



if __name__ == "__main__":
    unittest.main()
