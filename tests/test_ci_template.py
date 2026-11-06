"""The fork pull request recipe: what the privileged workflow may never do, and that it works from a generated adoption file."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fakes import FakeClock, FakeGit, FakeGitHub, FakeSandbox
from helpers import SHA, SKILL, done

from test_fleet import BASH, pull_routes

import sbx_fleet
import sbx_onboard
import sbx_trust

TARGET = SKILL / "templates" / "github-pr-target.yml"
OPEN = SKILL / "templates" / "github-pr.yml"
PIN = re.compile(r"uses: [\w./-]+@[0-9a-f]{40}\b")
URL = "https://github.com/acme/app.git"


def steps(text: str) -> list[dict[str, str]]:
    """Each step as its keys and the raw text of its `run:` body. No YAML parser ships with Python, and a template stays this flat."""
    found: list[dict[str, str]] = []
    lines = text.splitlines()
    for number, line in enumerate(lines):
        match = re.match(r"( +)- (\w[\w-]*):\s*(.*)", line)
        if not match or len(match[1]) != 6:
            continue
        step = {match[2]: match[3]}
        body: list[str] = []
        for following in lines[number + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= 6:
                break
            body.append(following)
        step["text"] = "\n".join(body)
        run = re.search(r"^ +run: (.*)$", step["text"], re.MULTILINE)
        if match[2] == "run":
            step["run"] = match[3]
        elif run:
            step["run"] = run[1]
        if step.get("run") == "|":
            indented = step["text"].split("run: |\n", 1)[1]
            step["run"] = "\n".join(line[10:] for line in indented.splitlines())
        found.append(step)
    return found


class Privileged(unittest.TestCase):
    """GitHub's rule: code a pull request controls is data here, never run, and the job holds the secrets."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = TARGET.read_text(encoding="utf-8")
        cls.steps = steps(cls.text)

    def checkouts(self) -> list[dict[str, str]]:
        return [step for step in self.steps if "actions/checkout" in step.get("name", "") + step.get("uses", "") + step["text"]]

    def named(self, part: str) -> dict[str, str]:
        return next(step for step in self.steps if part in step.get("name", ""))

    def test_the_trigger_is_the_privileged_one_and_nothing_else(self) -> None:
        self.assertIn("pull_request_target:", self.text)
        self.assertIsNone(re.search(r"^  pull_request:", self.text, re.MULTILINE))

    def test_every_checkout_keeps_no_credential(self) -> None:
        for step in self.checkouts():
            self.assertIn("persist-credentials: false", step["text"], step)

    def test_the_rules_come_from_the_default_branch(self) -> None:
        refs = [re.search(r"ref: (.+)", step["text"]) for step in self.checkouts()]
        self.assertEqual({match[1] for match in refs if match}, {"${{ github.event.repository.default_branch }}", "${{ vars.SBX_SKILL_SHA }}"})
        self.assertEqual(len([match for match in refs if match]), len(refs))

    def test_nothing_the_pull_request_controls_is_checked_out_or_fetched(self) -> None:
        for shape in ("head.ref", "head.repo", "refs/pull", "merge_commit_sha", "allow-unsafe-pr-checkout", "git fetch", "gh pr checkout",
                      "git clone", "download-artifact", "actions/cache", "workflow_run"):
            self.assertNotIn(shape, self.text, shape)
        self.assertEqual(self.text.count("github.event.pull_request.head.sha"), 1)  # the one env line: the box clones it, the runner never does

    def test_the_only_other_repository_is_the_pinned_skill(self) -> None:
        self.assertEqual(re.findall(r"repository: (.+)", self.text), ["ffroliva/skills", "ffroliva/skills"])

    def test_no_expression_reaches_a_shell(self) -> None:
        for step in self.steps:
            self.assertNotIn("${{", step.get("run", ""), step)

    def test_the_sha_and_number_are_checked_before_any_use(self) -> None:
        for job in self.text.split("\n  fleet:\n"):
            first = job[job.index("steps:"):]
            self.assertIn('[[ "$SBX_SKILL_SHA" =~ ^[0-9a-f]{40}$ && "$SHA" =~ ^[0-9a-f]{40}$ && "$PR" =~ ^[0-9]+$ ]]',
                          first[:first.index("actions/checkout")])

    def test_the_token_is_read_only_and_jobs_ask_for_no_more(self) -> None:
        self.assertIn("\npermissions: {}\n", self.text)
        self.assertEqual(re.findall(r"^ {6}(\w[\w-]*): (read|write)$", self.text, re.MULTILINE), [("contents", "read"), ("contents", "read")])

    def test_every_action_is_pinned_to_a_commit(self) -> None:
        uses = re.findall(r"uses: .+", self.text)
        self.assertTrue(uses)
        for line in uses:
            self.assertRegex(line, PIN)

    def test_a_token_reaches_only_the_steps_that_read_with_it(self) -> None:
        holders = [step.get("name") for step in self.steps if "GH_TOKEN" in step["text"]]
        self.assertEqual(holders, ["Decide", "Run the commit in a box, at the level found"])

    def test_an_untrusted_run_gets_no_token_whatever_decide_said(self) -> None:
        self.assertIn("needs.decide.outputs.level == 'trusted' && secrets.SBX_TRUST_TOKEN || ''", self.named("Run the commit")["text"])
        self.assertIn("needs.decide.outputs.level == 'trusted' && 'sbx-trusted' || 'sbx-external'", self.text)

    def test_the_docker_token_goes_in_on_stdin_and_only_there(self) -> None:
        holders = [step.get("name") for step in self.steps if "DOCKER_PAT" in step["text"]]
        self.assertEqual(holders, ["Sign in to Docker"])
        self.assertIn('printenv DOCKER_PAT | sbx login --username "$DOCKER_USERNAME" --password-stdin', self.named("Sign in")["run"])

    def test_the_trust_check_parses_with_the_real_flags(self) -> None:
        line = next(line for line in self.named("Decide")["run"].splitlines() if "sbx_trust.py" in line)
        words = shlex.split(line.strip().removeprefix("if ").removesuffix("; then").replace("$PR", "7"))
        args = sbx_trust._parser().parse_args(words[2:])
        self.assertEqual((args.action, args.config.as_posix()), ("check", "docs/sbx.md"))

    def test_the_fleet_parses_with_the_real_flags_and_passes_no_secret(self) -> None:
        line = self.named("Run the commit")["run"].splitlines()[-1]
        args = sbx_fleet._parser().parse_args(shlex.split(line.replace('--pr "$PR"', "--pr 7"))[2:])
        self.assertEqual((args.sha, args.pr, args.secret_service, args.secret_env, args.env), ("$SHA", 7, "", "", []))

    def test_the_sweep_always_runs_for_this_pull_request_alone(self) -> None:
        step = self.named("Sweep")
        self.assertIn("if: always()", step["text"])
        line = step["run"].splitlines()[-1]
        args = sbx_fleet._parser().parse_args(shlex.split(line)[2:])
        self.assertTrue(args.sweep_only)
        self.assertIn("-pr$PR", args.project)

    def test_the_sweep_and_the_run_name_one_project(self) -> None:
        self.assertEqual(re.findall(r'--project "(.+?)"', self.named("Run the commit")["run"]), re.findall(r'--project "(.+?)"', self.named("Sweep")["run"]))

    def test_the_sign_out_always_runs(self) -> None:
        self.assertIn("if: always()", self.named("Sign out")["text"])

    def test_a_new_push_replaces_the_run(self) -> None:
        self.assertIn("cancel-in-progress: true", self.text)

    def test_it_says_what_is_unsafe_and_what_github_enforces(self) -> None:
        self.assertIn("What is unsafe is running pull request code in a privileged job", self.text)
        self.assertIn("2 December 2026", self.text)
        self.assertRegex(self.text, r"github/docs/blob/[0-9a-f]{40}/content/actions/reference/security/securely-using-pull_request_target\.md")

    def test_an_unverified_recipe_says_so(self) -> None:
        self.assertIn("Unverified until a real run", self.text)


class Unprivileged(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = OPEN.read_text(encoding="utf-8")

    def test_it_runs_the_unprivileged_trigger(self) -> None:
        self.assertIsNotNone(re.search(r"^  pull_request:", self.text, re.MULTILINE))
        self.assertNotIn("pull_request_target:", self.text)

    def test_it_holds_nothing(self) -> None:
        for shape in ("secrets.", "environment:", "vars.", "sbx login", "write"):
            self.assertNotIn(shape, self.text.split("\nname:")[1], shape)

    def test_it_stays_on_a_hosted_runner(self) -> None:
        self.assertNotIn("self-hosted", self.text)

    def test_its_action_is_pinned_and_keeps_no_credential(self) -> None:
        self.assertRegex(self.text, PIN)
        self.assertIn("persist-credentials: false", self.text)


@unittest.skipUnless(BASH, "needs bash")
class Decide(unittest.TestCase):
    """The step's own text, in real bash: a failed or crashed check must end `untrusted`, and never stop the job as if it were red."""

    def level(self, exit_code: int) -> str:
        script = next(step for step in steps(TARGET.read_text(encoding="utf-8")) if step.get("name") == "Decide")["run"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            output = Path(folder) / "output"
            body = Path(folder) / "step.sh"
            body.write_text(f"set -e\npython3() {{ return {exit_code}; }}\n{script}\n", encoding="utf-8", newline="\n")
            env = {**os.environ, "GITHUB_OUTPUT": output.as_posix(), "GITHUB_REPOSITORY": "acme/app", "PR": "7", "SHA": SHA}
            done_run = subprocess.run([str(BASH), str(body)], env=env, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(done_run.returncode, 0, done_run.stderr)
            return output.read_text(encoding="utf-8").strip()

    def test_exit_zero_is_trusted(self) -> None:
        self.assertEqual(self.level(0), "level=trusted")

    def test_exit_one_is_untrusted(self) -> None:
        self.assertEqual(self.level(1), "level=untrusted")

    def test_a_crash_is_untrusted(self) -> None:
        self.assertEqual(self.level(127), "level=untrusted")


SKILL_CHECK = "Refuse a skill commit that is not on its default branch or a tag"


class PinnedSkill(unittest.TestCase):
    """Review 4, M2: GitHub serves a fork's commit under the parent's name, so a sha of the right shape is no pin."""

    def test_both_jobs_refuse_a_skill_commit_before_running_it(self) -> None:
        text = TARGET.read_text(encoding="utf-8")
        bodies: set[str] = set()
        for job in text.split("\n  fleet:\n"):
            names = [step.get("name", "") for step in steps(job)]
            self.assertIn(SKILL_CHECK, names, job[:60])
            check = names.index(SKILL_CHECK)
            self.assertEqual(names[check - 1], "Check out the pinned skill")
            self.assertIn("fetch-depth: 0", steps(job)[check - 1]["text"])  # its branches and tags, to check against
            bodies.add(steps(job)[check]["run"])
        self.assertEqual(len(bodies), 1, "both jobs run the check the real-bash test runs")

    def test_the_value_says_where_to_come_from(self) -> None:
        self.assertIn("SBX_SKILL_SHA, a commit on the skill's default branch or a release tag", TARGET.read_text(encoding="utf-8"))

    @unittest.skipUnless(BASH, "needs bash")
    def test_in_real_bash_only_the_default_branch_or_a_tag_passes(self) -> None:
        script = next(step for step in steps(TARGET.read_text(encoding="utf-8")) if step.get("name") == SKILL_CHECK)["run"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            base = Path(folder)
            git = ["git", "-c", "user.name=t", "-c", "user.email=t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

            def run(*argv: str, cwd: Path = base / "skill") -> str:
                return subprocess.run([*git, *argv], cwd=cwd, capture_output=True, text=True, check=True, timeout=30).stdout.strip()

            (base / "skill").mkdir()
            run("init", "-q", "-b", "trunk")
            run("commit", "-q", "--allow-empty", "-m", "on the default branch")
            on_branch = run("rev-parse", "HEAD")
            run("checkout", "-q", "-b", "side")
            run("commit", "-q", "--allow-empty", "-m", "a branch, standing in for a fork's commit")
            off_branch = run("rev-parse", "HEAD")
            run("commit", "-q", "--allow-empty", "-m", "tagged")
            tagged = run("rev-parse", "HEAD")
            run("tag", "v9.9.9")
            run("checkout", "-q", "trunk")
            run("clone", "-q", "--no-checkout", str(base / "skill"), str(base / ".sandbox-runbook"), cwd=base)
            body = base / "step.sh"
            body.write_text(f"set -eo pipefail\n{script}\n", encoding="utf-8", newline="\n")
            for sha, passes in ((on_branch, True), (off_branch, False), (tagged, True), ("f" * 40, False)):
                with self.subTest(sha=sha, passes=passes):
                    done_run = subprocess.run([str(BASH), str(body)], cwd=base / ".sandbox-runbook", env={**os.environ, "SBX_SKILL_SHA": sha},
                                              capture_output=True, text=True, timeout=30, check=False)
                    self.assertEqual(done_run.returncode == 0, passes, done_run.stderr)


GITHUB_ENVIRONMENTS = ("https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/"
                       "workflows-and-actions/deployments-and-environments.md#L50")


def _prose(path: Path) -> str:
    """A file's words on one line, with YAML comment marks and line wrapping gone."""
    return " ".join(re.sub(r"(?m)^\s*#", " ", path.read_text(encoding="utf-8")).split())


class EnvironmentSetup(unittest.TestCase):
    """Review 4, H2: with no deployment-branch rule, anyone with write access takes DOCKER_PAT from any branch they push."""

    PLACES = (TARGET, SKILL / "docs" / "use-cases" / "contributor-prs.md", SKILL / "docs" / "reference" / "github-token.md")

    def test_every_setup_text_restricts_deployment_branches_to_the_default_branch(self) -> None:
        for path in self.PLACES:
            with self.subTest(path=path.name):
                text = _prose(path)
                self.assertIn("Selected branches and tags", text)
                self.assertIn("your default branch only", text)
                self.assertIn(GITHUB_ENVIRONMENTS, text)

    def test_the_template_says_why_and_what_else_the_setup_needs(self) -> None:
        text = _prose(TARGET)
        for part in ("GITHUB_REF", "required reviewers, before DOCKER_PAT", "CODEOWNERS", "machine account"):
            self.assertIn(part, text)


class FromAGeneratedFile(unittest.TestCase):
    """Item 5 of round 5: onboarding, then a stranger's pull request and a member's, with no hand edit but the rule."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / ".git").mkdir()
        (self.root / "uv.lock").write_text("", encoding="utf-8")
        (self.root / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")
        with mock.patch("sbxlib.adapters.project_scan.in_dir", lambda _root: self.scan):
            sbx_onboard.onboard(self.root, "docs/sbx.md", ())
        self.path = self.root / "docs" / "sbx.md"
        self.sbx = FakeSandbox()

    @staticmethod
    def scan(argv: list[str], _stdin: str | None = None, _timeout: int = 60) -> object:
        return done(0, URL + "\n") if argv[:2] == ["git", "remote"] else done(127)  # gh cannot read the visibility: as a fresh runner

    def run_pull(self, gh: FakeGitHub) -> tuple[int, str, dict[str, object]]:
        out = self.root / "out"
        argv = ["--config", str(self.path), "--repo", URL, "--sha", SHA, "--pr", "7", "--out", str(out)]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), mock.patch.dict(os.environ, {"GH_TOKEN": "t"}):
            code = sbx_fleet.main(argv, sbx=self.sbx, git=FakeGit(SHA, [SHA]), gh=gh, clock=FakeClock(), run_id=lambda: "k3f9")
        body = json.loads((out / "verdict.json").read_text(encoding="utf-8")) if (out / "verdict.json").exists() else {}
        return code, stdout.getvalue(), body

    def test_a_strangers_pull_request_runs_untrusted(self) -> None:
        code, text, body = self.run_pull(FakeGitHub(pull_routes()))
        self.assertEqual((code, body.get("level"), body.get("rule")), (0, "untrusted", "no-rules"), text)
        self.assertIn("create", self.sbx.verbs())

    def test_with_a_rule_a_stranger_stays_untrusted_and_a_member_is_trusted(self) -> None:
        self.path.write_text(self.path.read_text(encoding="utf-8").replace("trust_roles: \n", "trust_roles: write\n"), encoding="utf-8", newline="\n")
        code, text, body = self.run_pull(FakeGitHub(pull_routes()))
        self.assertEqual((code, body.get("level"), body.get("rule")), (0, "untrusted", "no-rule-matched"), text)
        (self.root / "out").rename(self.root / "out-stranger")
        code, text, body = self.run_pull(FakeGitHub(pull_routes(role="write")))
        self.assertEqual((code, body.get("level"), body.get("rule")), (0, "trusted", "role:write"), text)

    def test_a_private_projects_generated_file_refuses_it_and_says_why(self) -> None:
        text = self.path.read_text(encoding="utf-8")
        for old, new in (("clone: public", "clone: token"), ("secret_service: none", "secret_service: github")):
            text = text.replace(old, new)
        self.path.write_text(text, encoding="utf-8", newline="\n")
        code, printed, _ = self.run_pull(FakeGitHub(pull_routes()))
        self.assertEqual(code, 2, printed)
        self.assertNotIn("create", self.sbx.verbs())
        self.assertIn("takes no secrets", printed)


if __name__ == "__main__":
    unittest.main()
