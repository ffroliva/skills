"""One suite for the fake and for the real tool, so the fake cannot drift from sbx.

With SBX_LIVE=1 it runs against the real `sbx`: that creates a billable box, so it is off by default and CI never sets it.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fakes import FakeSandbox
from helpers import REPO, SHA

from sbxlib.adapters.clock import new_run_id
from sbxlib.adapters.process import run_command
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.domain.fleet import RunRequest, box_name


def runner():  # type: ignore[no-untyped-def]
    if os.environ.get("SBX_LIVE") != "1":
        return FakeSandbox()
    return lambda argv, stdin=None, timeout=60: run_command([argv[0], "--app-name", "sbx-skill-contract", *argv[1:]], stdin, timeout)


class LiveRunner(unittest.TestCase):
    def test_live_runner_passes_a_dedicated_app_name(self) -> None:
        calls = []
        with mock.patch.dict(os.environ, {"SBX_LIVE": "1"}), mock.patch(
            "test_contract.run_command", side_effect=lambda argv, *_args: calls.append(argv)
        ):
            runner()(["sbx", "--cloud", "version"])
        self.assertEqual(calls[0][1:3], ["--app-name", "sbx-skill-contract"])


class RuntimeContract(unittest.TestCase):
    def setUp(self) -> None:
        self.request = RunRequest(REPO, SHA, ("true",), "contract", new_run_id(), cpus=2, memory="4g", ttl_minutes=10, minutes=5)
        self.box = box_name(self.request, 1)
        self.runtime = SbxCli(runner())
        self.addCleanup(self._clean)

    def _clean(self) -> None:
        self.runtime.remove(self.box)
        for row in self.runtime.secrets():
            if row.scope == self.box:
                self.runtime.remove_scoped(self.box, row.name)

    def test_a_version_is_readable(self) -> None:
        self.assertRegex(self.runtime.version() or "", r"^\d+\.\d+\.\d+$")

    def test_a_box_lives_runs_and_goes(self) -> None:
        self.assertEqual(self.runtime.create(self.box, self.request).rc, 0)
        rows = {row.name: row for row in self.runtime.boxes()}
        self.assertEqual(rows[self.box].cpus, 2)
        self.assertEqual(self.runtime.run(self.box, "true").rc, 0)
        self.assertEqual(self.runtime.remove(self.box).rc, 0)
        self.assertNotIn(self.box, [row.name for row in self.runtime.boxes()])

    def test_exec_on_a_missing_box_exits_125(self) -> None:
        self.assertEqual(self.runtime.run(self.box, "true").rc, 125)

    def test_a_scoped_secret_outlives_rm_until_removed(self) -> None:
        self.assertEqual(self.runtime.set_scoped(self.box, "github", "fake-value").rc, 0)
        self.assertEqual(self.runtime.create(self.box, self.request).rc, 0)
        self.runtime.remove(self.box)
        self.assertIn(self.box, [row.scope for row in self.runtime.secrets()])
        self.assertEqual(self.runtime.remove_scoped(self.box, "github").rc, 0)
        self.assertNotIn(self.box, [row.scope for row in self.runtime.secrets()])


if __name__ == "__main__":
    unittest.main()
