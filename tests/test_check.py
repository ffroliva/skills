"""sbx_check: every failure names its fix, and an unknown is never read as fine."""

from __future__ import annotations

import json
import unittest
from typing import Any

from fakes import FakeGit, FakeSandbox
from helpers import SHA

from sbxlib.adapters.git_cli import GitCli
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.app.check import Finding, Severity, run_check
from sbxlib.ports import Done

CONFIG = {
    "target_project": "acme", "repo": "acme/app", "target": "cloud", "template": "shell", "boxes": "1", "cpus": "8", "memory": "16g",
    "quota_vcpu": "40", "ttl": "30m", "minutes": "15", "on_timeout": "delete", "clone": "public",
    "secret_service": "none", "command": "make test", "allow": "pypi.org",
}
DET = {"repo_visibility": "public", "testcontainers": False}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.sbx = FakeSandbox()
        self.git = FakeGit(SHA, [SHA])

    def findings(self, config: dict[str, str] | None = None, det: dict[str, Any] | None = None, **kw: Any) -> dict[str, Finding]:
        cli = SbxCli(self.sbx)
        return {f.name: f for f in run_check(CONFIG if config is None else config, DET if det is None else det, cli, cli, GitCli(self.git), **kw)}

    def failed(self, name: str, **changes: Any) -> Finding:
        found = self.findings({**CONFIG, **changes})[name]
        self.assertFalse(found.ok, name)
        self.assertTrue(found.fix, name)
        return found


class Config(Base):
    def test_a_good_project_is_all_ok(self) -> None:
        self.assertEqual([f.name for f in self.findings().values() if not f.ok], [])

    def test_missing_keys_are_named(self) -> None:
        config = {k: v for k, v in CONFIG.items() if k != "cpus"}
        self.assertIn("cpus", self.findings(config)["config-keys"].fix)

    def test_a_missing_project_repository_is_named(self) -> None:
        self.assertIn("repo", self.findings({k: v for k, v in CONFIG.items() if k != "repo"})["config-keys"].fix)

    def test_what_the_fleet_would_refuse_blocks_ready(self) -> None:
        # review 2, M11: `ready` for a run the fleet refuses
        found = self.findings(plan=lambda: ["a untrusted run needs a deny-all account"])["fleet-plan"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.BLOCK)
        self.assertIn("deny-all", found.fix)

    def test_a_plan_the_fleet_accepts_passes(self) -> None:
        self.assertTrue(self.findings(plan=list)["fleet-plan"].ok)

    def test_a_placeholder_in_the_command_fails(self) -> None:
        self.failed("command", command="<set: x>")

    def test_boxes_over_one_with_no_shard_read_fails(self) -> None:
        self.failed("shards", boxes="5")

    def test_boxes_over_one_reading_shard_pass(self) -> None:
        self.assertTrue(self.findings({**CONFIG, "boxes": "5", "command": "t --shard $SHARD"})["shards"].ok)

    def test_shell_docker_fails_with_the_working_route(self) -> None:
        self.assertIn("shell", self.failed("template", template="shell-docker").fix)

    def test_an_oci_kit_reference_passes(self) -> None:
        self.assertTrue(self.findings({**CONFIG, "template": "docker.io/acme/kit:1"})["template"].ok)

    def test_a_project_name_sbx_refuses_fails(self) -> None:
        self.failed("target-project", target_project="My.Project")

    def test_a_private_repo_with_a_public_clone_fails(self) -> None:
        self.assertFalse(self.findings(det={**DET, "repo_visibility": "private"})["clone"].ok)

    def test_a_token_clone_needs_a_service(self) -> None:
        self.failed("secret-service", clone="token", secret_service="none")

    def test_a_token_clone_needs_a_secret_env(self) -> None:
        self.failed("secret-service", clone="token", secret_service="github")

    def test_a_named_secret_env_passes(self) -> None:
        self.assertTrue(self.findings({**CONFIG, "clone": "token", "secret_service": "github", "secret_env": "T"})["secret-service"].ok)

    def test_a_missing_ttl_fails(self) -> None:
        self.failed("ttl", ttl="")

    def test_an_unreadable_ttl_fails(self) -> None:
        self.failed("ttl", ttl="forever")

    def test_on_timeout_must_delete(self) -> None:
        self.failed("on-timeout", on_timeout="stop")

    def test_a_deadline_past_the_ttl_fails(self) -> None:
        self.failed("deadline", minutes="45")

    def test_a_shape_sbx_does_not_bill_fails(self) -> None:
        self.failed("shape", cpus="4", memory="4g")

    def test_a_local_target_skips_the_bounds(self) -> None:
        self.assertNotIn("ttl", self.findings({**CONFIG, "target": "local", "ttl": ""}))


class Account(Base):
    def test_no_sbx_stops_there(self) -> None:
        self.sbx.version_text = "nope"
        found = self.findings()
        self.assertFalse(found["sbx-installed"].ok)
        self.assertNotIn("account", found)

    def test_an_old_sbx_fails(self) -> None:
        self.sbx.version_text = "sbx version v0.40.0"
        self.assertFalse(self.findings()["sbx-version"].ok)

    def test_a_refused_listing_names_the_troubleshooting_entry(self) -> None:
        self.sbx.fail["ls"] = Done(1, "", "not signed in to Docker")
        found = self.findings()["account"]
        self.assertFalse(found.ok)
        self.assertIn("docs/troubleshooting.md#not-signed-in", found.fix)

    def test_a_listing_that_is_not_json_is_never_free_quota(self) -> None:
        self.sbx.fail["ls"] = Done(0, "oops")
        found = self.findings()
        self.assertFalse(found["account"].ok)
        self.assertNotIn("quota", found)

    def test_an_sbx_timeout_is_a_finding_not_a_crash(self) -> None:
        self.sbx.raises.add("ls")
        self.assertFalse(self.findings()["account"].ok)

    def test_live_boxes_count_against_the_quota(self) -> None:
        self.sbx.boxes["other"] = {"name": "other", "cpus": 36}
        self.assertFalse(self.findings()["quota"].ok)

    def test_a_fleet_within_the_quota_passes(self) -> None:
        self.sbx.boxes["other"] = {"name": "other", "cpus": 32}
        self.assertTrue(self.findings()["quota"].ok)

    def test_a_leftover_secret_gives_its_command(self) -> None:
        self.sbx.secrets.append({"scope": "acme-shards-01-k3f9", "name": "github", "type": "service"})
        found = self.findings()["leftover-secrets"]
        self.assertFalse(found.ok)
        self.assertIn("sbx --cloud secret rm github --sandbox acme-shards-01-k3f9 --force", found.fix)

    def test_a_secret_of_a_live_box_is_not_leftover(self) -> None:
        self.sbx.boxes["acme-shards-01-k3f9"] = {"name": "acme-shards-01-k3f9", "cpus": 8}
        self.sbx.secrets.append({"scope": "acme-shards-01-k3f9", "name": "github", "type": "service"})
        self.assertTrue(self.findings()["leftover-secrets"].ok)

    def test_a_global_secret_is_not_leftover(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "github", "type": "service"})
        self.assertTrue(self.findings()["leftover-secrets"].ok)

    def test_a_failed_secret_listing_is_never_clean(self) -> None:
        self.sbx.fail["secret ls"] = Done(1, "", "boom")
        self.assertFalse(self.findings()["leftover-secrets"].ok)

    def test_a_global_github_secret_blocks_a_project_whose_runs_are_untrusted(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "github", "type": "service"})
        found = self.findings({**CONFIG, "own_work": "untrusted"})["global-secrets"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.BLOCK)
        self.assertIn("github", found.fix)

    def test_a_global_github_secret_only_warns_a_project_whose_own_work_is_trusted(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "github", "type": "service"})
        found = self.findings({**CONFIG, "own_work": "trusted"})["global-secrets"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.WARN)

    def test_a_global_secret_for_a_host_not_allowed_passes(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "anthropic", "type": "service"})
        self.assertTrue(self.findings()["global-secrets"].ok)

    def test_an_allow_listed_service_host_is_counted(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "anthropic", "type": "service"})
        self.assertFalse(self.findings({**CONFIG, "allow": "api.anthropic.com"})["global-secrets"].ok)

    def test_an_account_default_looser_than_declared_blocks_an_untrusted_project(self) -> None:
        self.sbx.policy_mode = "allow-all"
        found = self.findings({**CONFIG, "own_work": "untrusted", "network_policy": "deny-all"})["network-default"]
        self.assertFalse(found.ok)
        self.assertIn("allow-all", found.fix)

    def test_an_unreadable_account_default_is_never_clean(self) -> None:
        self.sbx.fail["policy ls"] = Done(1, "", "boom")
        self.assertFalse(self.findings({**CONFIG, "own_work": "untrusted"})["network-default"].ok)

    def test_a_trusted_project_does_not_read_the_default(self) -> None:
        self.assertNotIn("network-default", self.findings({**CONFIG, "own_work": "trusted"}))

    def test_a_secret_reachable_through_the_accounts_list_is_counted(self) -> None:
        self.sbx.secrets.append({"scope": "global", "name": "anthropic", "type": "service"})
        self.sbx.policy_allow = ["api.anthropic.com"]
        found = self.findings({**CONFIG, "own_work": "untrusted"})["global-secrets"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.BLOCK)

    def test_a_wildcard_on_the_accounts_list_blocks_an_untrusted_project(self) -> None:
        self.sbx.policy_allow = ["**"]
        found = self.findings({**CONFIG, "own_work": "untrusted"})["network-default"]
        self.assertFalse(found.ok)
        self.assertIn("'**'", found.fix)

    def test_an_unreadable_account_list_is_never_clean(self) -> None:
        self.sbx.fail["policy ls"] = Done(0, json.dumps({"mode": "deny-all"}))
        self.assertFalse(self.findings({**CONFIG, "own_work": "untrusted"})["network-default"].ok)


class Git(Base):
    def test_not_a_repository(self) -> None:
        self.git = FakeGit("")
        self.assertFalse(self.findings()["git-repo"].ok)

    def test_an_unpushed_head_fails(self) -> None:
        self.git = FakeGit(SHA, ["b" * 40])
        self.assertFalse(self.findings()["pushed"].ok)

    def test_a_dirty_tree_fails(self) -> None:
        self.git = FakeGit(SHA, [SHA], dirty=True)
        self.assertFalse(self.findings()["working-tree"].ok)

    def test_an_unreadable_remote_fails(self) -> None:
        self.git = FakeGit(SHA, [SHA], readable=False)
        self.assertFalse(self.findings()["remote"].ok)

    def test_a_sha_other_than_head_fails(self) -> None:
        self.assertFalse(self.findings(sha="b" * 40)["sha-is-head"].ok)

    def test_head_itself_passes(self) -> None:
        self.assertTrue(self.findings(sha=SHA)["sha-is-head"].ok)


class Drift(Base):
    def test_drift_is_a_warning(self) -> None:
        found = self.findings(drift=lambda: {"status": "drift", "lines": ["x"], "missing_verbs": []})["drift"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.WARN)

    def test_a_gone_command_refuses(self) -> None:
        found = self.findings(drift=lambda: {"status": "drift", "lines": [], "missing_verbs": ["cp"]})["sbx-commands"]
        self.assertFalse(found.ok)
        self.assertIs(found.severity, Severity.BLOCK)

    def test_aligned_passes(self) -> None:
        self.assertTrue(self.findings(drift=lambda: {"status": "aligned", "lines": [], "missing_verbs": []})["drift"].ok)


class Trust(Base):
    def test_the_doctors_findings_are_included_as_warnings(self) -> None:
        found = self.findings(trust=lambda: [Finding("trust-token", False, "see the guide", Severity.WARN)])["trust-token"]
        self.assertIs(found.severity, Severity.WARN)


if __name__ == "__main__":
    unittest.main()
