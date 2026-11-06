"""Is this exact commit of this pull request trusted? The project's rules decide; this helper applies them.

  check   --repo o/r --pr N --sha S   prints JSON: level, rule, evidence. Exit 0 trusted, 1 untrusted.
  doctor  --repo o/r [--pr N]         checks GH_TOKEN can read what the rules need, and names what is missing.

Anything not proven trusted is untrusted: an error, no network, no `gh`, no token, an unknown value, a repository other
than the file's `repo`. Run this on the host or in CI, never in a box. Rules are `trust_roles`, `trust_team` and
`trust_logins` in the local adoption file (--config): run it from a checkout of your default branch, because nothing here
reads that branch for you. See docs/reference/trust.md and docs/reference/github-token.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sbxlib.adapters.files import protected_paths
from sbxlib.adapters.gh_cli import GhCli
from sbxlib.adapters.process import run_command
from sbxlib.app.trust import GUIDE, PullRequestTrust, doctor
from sbxlib.domain.adoption import ADOPTION_FILE, parse_config, trust_rules
from sbxlib.domain.trust import TrustLevel, TrustRules, untrusted
from sbxlib.ports import CommandRunner

TOKEN_FORM = "https://github.com/settings/personal-access-tokens/new"  # noqa: S105  a page, not a value


def creation_link(repo: str, rules: TrustRules) -> str:
    """The form, prefilled. GitHub's page takes these as query parameters; the person still picks the repository."""
    owner = repo.partition("/")[0]
    query = f"name=sbx-trust-check&target_name={owner}&expires_in=90&pull_requests=read&metadata=read"
    return f"{TOKEN_FORM}?{query}" + ("&members=read" if rules.team else "")


def _config(path: Path) -> dict[str, str]:
    return parse_config(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("check", help="print the verdict for one commit as JSON")
    check.add_argument("--pr", type=int, required=True)
    check.add_argument("--sha", required=True, help="the exact commit; a push after the check needs a new check")
    probe = sub.add_parser("doctor", help="check the token")
    probe.add_argument("--pr", type=int, help="a pull request to read as a probe")
    probe.add_argument("--login", help="a login to probe rules with (default: the repository owner)")
    for command in (check, probe):
        command.add_argument("--repo", required=True, help="owner/name")
        command.add_argument("--config", type=Path, default=Path(ADOPTION_FILE), help=f"adoption file ({ADOPTION_FILE})")
    return parser


def main(argv: list[str] | None = None, gh: CommandRunner = run_command, token: str | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _config(args.config)
    except ValueError as exc:  # the file itself is suspect, so no rule in it counts
        print(json.dumps(untrusted("adoption-file-refused", why=str(exc)).to_json(), indent=2))
        return 1
    rules = trust_rules(config)
    host = GhCli(gh, os.environ.get("GH_TOKEN", "") if token is None else token)
    if args.action == "check":
        protected = protected_paths(args.config, config.get("template", ""))
        verdict = PullRequestTrust(host, rules, protected).check(args.repo, args.pr, args.sha)
        print(json.dumps(verdict.to_json(), indent=2))
        return 0 if verdict.level is TrustLevel.TRUSTED else 1
    findings = doctor(host, rules, args.repo, args.login or args.repo.partition("/")[0], args.pr)
    for finding in findings:
        print(f"{'ok  ' if finding.ok else 'FAIL'} {finding.name}" + (f": {finding.fix}" if finding.fix else ""))
    if not rules:
        print("sbx_trust: no trust rule is set: every pull request stays untrusted")
    if not host.has_token():
        print(f"sbx_trust: guide: {GUIDE}")
        print(f"sbx_trust: create one: {creation_link(args.repo, rules)}")
    return 0 if all(finding.ok for finding in findings) else 1


if __name__ == "__main__":
    sys.exit(main())
