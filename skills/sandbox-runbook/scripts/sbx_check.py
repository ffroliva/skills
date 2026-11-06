"""Validate a project's adoption file and environment before a run. Every failure names its fix.

Reads only: `sbx version`, `sbx --cloud ls`, `secret ls`, `policy ls`, git, and `gh` reads. Creates nothing, spends nothing.
`ready` means a run of this file with no flags would pass every refusal the fleet can decide before it reads the commit.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sbx_drift import SNAPSHOT, newest_release
from sbx_fleet import planned_refusals
from sbxlib.adapters.gh_cli import GhCli
from sbxlib.adapters.git_cli import GitCli
from sbxlib.adapters.process import in_dir, run_command
from sbxlib.adapters.project_scan import detect
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.app import drift as drift_app
from sbxlib.app.check import Finding, Severity, run_check
from sbxlib.app.trust import doctor
from sbxlib.domain.adoption import ADOPTION_FILE, parse_config, trust_rules, unfilled
from sbxlib.domain.trust import repo_id
from sbxlib.ports import CommandRunner


def _trust(config: Mapping[str, str], det: Mapping[str, Any], gh: CommandRunner, token: str) -> list[Finding]:
    """The token check is a warning: with no token every pull request stays untrusted, which is safe."""
    remote = str(det.get("remote", ""))
    rules = trust_rules(config)
    if not rules and det.get("repo_visibility") == "private":
        return []
    repo = remote.removesuffix(".git").rpartition("github.com")[2].lstrip(":/")
    findings = doctor(GhCli(gh, token), rules, repo, repo.partition("/")[0])
    return [Finding(f"trust-{f.name}", f.ok, f.fix, Severity.WARN) for f in findings]


def _unfilled(root: Path, path: Path) -> list[Finding]:
    paths = [path, root / "docs" / "sbx-recipe.md"]
    left = [f"{item.name}: {name}" for item in paths if item.is_file()
            for name in unfilled(item.read_text(encoding="utf-8"))]
    return [Finding("placeholders", not left, f"unfilled {', '.join(left)}: rerun sbx_onboard.py")]


def main(argv: list[str] | None = None, sbx: CommandRunner = run_command, git: CommandRunner | None = None,
         gh: CommandRunner = run_command, token: str | None = None, det: dict[str, Any] | None = None,
         drift: Callable[[], Mapping[str, Any]] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path, help="the project (default: here)")
    parser.add_argument("--file", default=ADOPTION_FILE, help=f"adoption file, relative to the project ({ADOPTION_FILE})")
    parser.add_argument("--config", type=Path, help="the adoption file at any path, the one the fleet's --config will read")
    parser.add_argument("--command", action="append", default=[], dest="commands",
                        help="a command the run will pass to the fleet, in place of `command`; repeat for one per box")
    parser.add_argument("--sha", help="the commit you will run. It must be HEAD: this check reads the working tree")
    args = parser.parse_args(argv)
    path = args.config or args.root / args.file
    refused = ""
    try:
        config = parse_config(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError as exc:
        config, refused = {}, str(exc)
    cli = SbxCli(sbx)
    commands = tuple(args.commands)
    if not config:
        findings = [Finding("adoption-file", False, f"{path}: {refused or 'run sbx_onboard.py to write it with an sbx-config block'}")]
    else:
        scan = det if det is not None else detect(args.root)
        secret = os.environ.get("GH_TOKEN", "") if token is None else token

        def live_drift() -> Mapping[str, Any]:
            text = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.is_file() else None
            return drift_app.check(cli, lambda: newest_release(gh), text)[1]

        findings = [Finding("adoption-file", True), *_unfilled(args.root, path),
                    *run_check(config, scan, cli, cli, GitCli(git or in_dir(args.root)), args.sha, drift or live_drift,
                               lambda: _trust(config, scan, gh, secret),
                               lambda: planned_refusals(config, f"https://{repo_id(config.get('repo', ''))}.git", commands), commands)]
    failed = [f for f in findings if not f.ok and f.severity is Severity.BLOCK]
    for finding in findings:
        print(f"{'ok  ' if finding.ok else finding.severity.value} {finding.name}" + (f": {finding.fix}" if not finding.ok else ""))
    print("sbx_check: quota_vcpu is the limit you declared; no sbx command reads the quota (none in sbx 0.51.0's --help), "
          "so a refused create is the only signal")
    print(f"sbx_check: {len(failed)} to fix" if failed else "sbx_check: ready")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
