"""`sbx_trust.py check` and `doctor`: fails closed, and never prints the token."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fakes import FakeGitHub
from helpers import SHA

import sbx_trust
from sbxlib.ports import CommandTimeout, Done

TOKEN = "fake-read-only-value"
PULL = {"state": "open", "head": {"sha": SHA, "repo": {"full_name": "acme/app"}}, "base": {"repo": {"full_name": "acme/app"}},
        "user": {"login": "alice"}, "author_association": "CONTRIBUTOR", "commits": 1, "changed_files": 1}
ROUTES: dict[str, Any] = {
    "repos/acme/app": {"full_name": "acme/app"},
    "repos/acme/app/pulls/7": PULL,
    "repos/acme/app/pulls/7/commits?per_page=100": [{"sha": SHA, "author": {"login": "alice"}}],
    "repos/acme/app/pulls/7/files?per_page=100": [{"filename": "src/a.py"}],
    "repos/acme/app/collaborators/alice/permission": {"role_name": "write"},
    "repos/acme/app/collaborators/acme/permission": {"role_name": "admin"},
}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / ".git").mkdir()
        (Path(folder.name) / "docs").mkdir()
        self.config = Path(folder.name) / "docs" / "sbx.md"
        self.write("trust_roles: write,admin\n")
        self.gh = FakeGitHub(ROUTES)

    def write(self, keys: str) -> None:
        self.config.write_text("```sbx-config\nrepo: acme/app\n" + keys + "```\n", encoding="utf-8")

    def run_cli(self, *argv: str, token: str = TOKEN) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sbx_trust.main([*argv, "--config", str(self.config)], gh=self.gh, token=token)
        return code, out.getvalue()

    def check(self, *extra: str, token: str = TOKEN) -> tuple[int, dict[str, Any]]:
        code, text = self.run_cli("check", "--repo", "acme/app", "--pr", "7", "--sha", SHA, *extra, token=token)
        return code, json.loads(text)


class Check(Base):
    def test_a_member_is_trusted_with_exit_zero(self) -> None:
        code, body = self.check()
        self.assertEqual((code, body["level"], body["rule"]), (0, "trusted", "role:write"))

    def test_the_json_has_level_rule_and_evidence(self) -> None:
        self.assertEqual(sorted(self.check()[1]), ["evidence", "level", "rule"])

    def test_no_rules_is_untrusted_exit_one(self) -> None:
        self.write("target_project: acme\n")
        code, body = self.check()
        self.assertEqual((code, body["rule"]), (1, "no-rules"))

    def test_a_fork_stays_untrusted_even_when_a_member_opens_it(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = {**PULL, "head": {"sha": SHA, "repo": {"full_name": "eve/app"}}}
        code, body = self.check()
        self.assertEqual((code, body["rule"]), (1, "fork-head"))

    def test_a_head_repository_gone_from_github_stays_untrusted(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = {**PULL, "head": {"sha": SHA, "repo": None}}
        self.assertEqual(self.check()[1]["rule"], "fork-head")

    def test_the_same_repository_in_another_case_is_no_fork(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = {**PULL, "head": {"sha": SHA, "repo": {"full_name": "Acme/App"}}}
        self.assertEqual(self.check()[1]["level"], "trusted")

    def test_a_file_with_two_blocks_is_untrusted_and_names_why(self) -> None:
        self.config.write_text("```sbx-config\nrepo: acme/app\ntrust_roles: write\n```\n```sbx-config\ntrust_logins: alice\n```\n",
                               encoding="utf-8")
        code, body = self.check()
        self.assertEqual((code, body["level"], body["rule"]), (1, "untrusted", "adoption-file-refused"))
        self.assertIn("more than one", body["evidence"]["why"])
        self.assertEqual(self.gh.calls, [])

    def test_doctor_on_a_file_with_two_blocks_says_why(self) -> None:
        self.config.write_text("```sbx-config\nrepo: acme/app\n```\n```sbx-config\ntrust_logins: alice\n```\n", encoding="utf-8")
        code, text = self.run_cli("doctor", "--repo", "acme/app")
        self.assertEqual(code, 1)
        self.assertIn("more than one", text)

    def test_a_missing_adoption_file_is_untrusted(self) -> None:
        self.config.unlink()
        code, body = self.check()
        self.assertEqual((code, body["level"]), (1, "untrusted"))

    def test_no_token_is_untrusted_and_names_the_guide(self) -> None:
        code, body = self.check(token="")
        self.assertEqual((code, body["rule"]), (1, "no-token"))
        self.assertIn("github-token.md", body["evidence"]["guide"])
        self.assertEqual(self.gh.calls, [])

    def test_a_403_is_untrusted(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = 403
        code, body = self.check()
        self.assertEqual((code, body["rule"]), (1, "host-error:403"))

    def test_no_gh_is_untrusted(self) -> None:
        self.gh = lambda argv, stdin=None, timeout=60: Done(127, "", "gh: not found")  # type: ignore[assignment]
        self.assertEqual(self.check()[1]["level"], "untrusted")

    def test_a_hung_gh_is_untrusted(self) -> None:
        def hung(argv: Any, stdin: Any = None, timeout: int = 60) -> Done:
            raise CommandTimeout("gh")

        self.gh = hung  # type: ignore[assignment]
        self.assertEqual(self.check()[1]["rule"], "host-timeout")

    def test_garbage_from_gh_is_untrusted(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = ["not", "an", "object"]
        self.assertEqual(self.check()[1]["level"], "untrusted")

    def test_the_token_is_nowhere_in_the_output_or_argv(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = 403
        _, text = self.run_cli("check", "--repo", "acme/app", "--pr", "7", "--sha", SHA)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(TOKEN, " ".join(word for call in self.gh.calls for word in call))

    def test_a_pull_request_changing_the_adoption_file_stays_untrusted(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7/files?per_page=100"] = [{"filename": "docs/sbx.md"}]
        self.assertEqual(self.check()[1]["rule"], "adoption-file-changed")

    def test_a_config_at_another_path_is_guarded_at_that_path(self) -> None:
        moved = self.config.parent / "fleet.md"
        moved.write_text(self.config.read_text(encoding="utf-8"), encoding="utf-8")
        self.config = moved
        self.gh.routes["repos/acme/app/pulls/7/files?per_page=100"] = [{"filename": "docs/fleet.md"}]
        self.assertEqual(self.check()[1]["rule"], "adoption-file-changed")

    def test_a_foreign_repository_is_untrusted_before_any_read(self) -> None:
        code, text = self.run_cli("check", "--repo", "stranger/fork", "--pr", "7", "--sha", SHA)
        self.assertEqual((code, json.loads(text)["rule"]), (1, "repo-mismatch"))
        self.assertEqual(self.gh.calls, [])


class Doctor(Base):
    def doctor(self, *extra: str, token: str = TOKEN) -> tuple[int, str]:
        return self.run_cli("doctor", "--repo", "acme/app", "--pr", "7", *extra, token=token)

    def test_a_working_token_passes(self) -> None:
        code, text = self.doctor()
        self.assertEqual(code, 0, text)
        self.assertIn("ok   token", text)

    def test_no_token_fails_and_prints_the_guide_and_the_creation_link(self) -> None:
        code, text = self.doctor(token="")
        self.assertEqual(code, 1)
        self.assertIn("github-token.md", text)
        self.assertIn("https://github.com/settings/personal-access-tokens/new?", text)
        self.assertIn("pull_requests=read", text)

    def test_the_creation_link_asks_for_members_only_with_a_team_rule(self) -> None:
        self.assertNotIn("members=read", self.doctor(token="")[1])
        self.write("trust_team: acme/core\n")
        self.assertIn("members=read", self.doctor(token="")[1])

    def test_an_expired_token_is_named(self) -> None:
        self.gh.routes["repos/acme/app"] = 401
        code, text = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("expired or revoked", text)

    def test_a_repo_out_of_reach_stops_there(self) -> None:
        self.gh.routes["repos/acme/app"] = 404
        code, text = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("github-token.md#repository-access", text)
        self.assertNotIn("pull-requests", text)

    def test_a_missing_pull_request_permission_is_named(self) -> None:
        self.gh.routes["repos/acme/app/pulls/7"] = 403
        code, text = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("Pull requests read", text)

    def test_a_missing_members_permission_is_named(self) -> None:
        self.write("trust_team: acme/core\n")
        code, text = self.doctor("--login", "bob")
        self.assertEqual(code, 1)
        self.assertIn("organization Members read", text)

    def test_a_read_role_rule_is_called_out(self) -> None:
        self.write("trust_roles: read\n")
        code, text = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("read prove nothing", text)

    def test_no_rules_is_a_warning_in_words(self) -> None:
        self.write("target_project: acme\n")
        self.assertIn("no trust rule is set: every pull request stays untrusted", self.doctor()[1])


if __name__ == "__main__":
    unittest.main()
