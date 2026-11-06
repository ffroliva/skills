"""Check one pull request at one commit, and whether the token can do that check. Any failure stays untrusted."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..domain.trust import PullFacts, Standing, TrustRules, TrustVerdict, decide, repo_rule, unknown_roles, untrusted
from ..ports import CommandTimeout, HostError, RepoHost

GUIDE = "docs/reference/github-token.md"


def _login(user: object) -> str:
    return str(user.get("login") or "") if isinstance(user, Mapping) else ""  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def _nested(data: Mapping[str, Any], *keys: str) -> str:
    value: Any = data
    for key in keys:
        value = value.get(key) if isinstance(value, Mapping) else None  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    return str(value) if value else ""  # pyright: ignore[reportUnknownArgumentType]


class PullRequestTrust:
    def __init__(self, host: RepoHost, rules: TrustRules, protected: tuple[str, ...]) -> None:
        self._host, self._rules, self._protected = host, rules, protected

    def _standing(self, repo: str, login: str) -> Standing:
        role = self._host.role(repo, login) if self._rules.roles else ""
        team = self._rules.team
        return Standing(role, frozenset({team}) if team and self._host.in_team(team, login) else frozenset())

    def _facts(self, repo: str, number: int) -> PullFacts:
        pull = self._host.pull(repo, number)
        commits = self._host.pull_commits(repo, number)
        files = self._host.pull_files(repo, number)
        authors = tuple(_login(row.get("author")) for row in commits)
        author = _login(pull.get("user"))
        logins = sorted({author, *authors} - {""})
        return PullFacts(number, _nested(pull, "head", "sha"), str(pull.get("state")), author,
                         str(pull.get("author_association") or ""), _nested(pull, "head", "repo", "full_name"),
                         _nested(pull, "base", "repo", "full_name"), int(pull.get("commits") or 0), authors,
                         int(pull.get("changed_files") or 0), tuple(name for name, _ in files),
                         {login: self._standing(repo, login) for login in logins},
                         tuple(previous for _, previous in files if previous))

    def check(self, repo: str, number: int, sha: str) -> TrustVerdict:
        evidence = {"repo": repo, "pull": number, "sha": sha}
        if not self._rules:
            return untrusted("no-rules", **evidence)
        bound = repo_rule(self._rules.repo, repo)
        if bound:
            return untrusted(bound, **evidence)
        if not self._host.has_token():
            return untrusted("no-token", **evidence, guide=GUIDE)
        try:
            return decide(self._rules, self._facts(repo, number), sha, self._protected)
        except HostError as exc:
            return untrusted(f"host-error:{exc.status}", **evidence, guide=GUIDE)
        except CommandTimeout:
            return untrusted("host-timeout", **evidence)
        except (TypeError, ValueError, AttributeError):
            return untrusted("host-answer-unreadable", **evidence)


@dataclass(frozen=True)
class DoctorFinding:
    name: str
    ok: bool
    fix: str = ""


def _section(name: str) -> str:
    return f"{GUIDE}#{name}"


def _probe(name: str, permission: str, section: str, call: Any) -> DoctorFinding:
    """Run one read. 403 and 404 both mean this permission or repository is out of reach for the token."""
    try:
        call()
    except HostError as exc:
        if exc.status == 401:
            return DoctorFinding(name, False, f"the token is expired or revoked: see {_section('expired-token')}")
        if exc.status in (403, 404):
            return DoctorFinding(name, False, f"needs {permission}, or org approval: see {_section(section)}")
        return DoctorFinding(name, False, f"GitHub did not answer ({exc}): see {_section(section)}")
    except CommandTimeout:
        return DoctorFinding(name, False, "gh did not answer in time")
    return DoctorFinding(name, True)


def doctor(host: RepoHost, rules: TrustRules, repo: str, probe_login: str, pull: int | None = None) -> list[DoctorFinding]:
    """Present, works, reaches this repo, and can read what the configured rules need."""
    if not host.has_token():
        return [DoctorFinding("token", False, f"GH_TOKEN is not set, so every verdict stays untrusted: see {GUIDE}")]
    found = [DoctorFinding("token", True), _probe("repository", "Metadata read on this repository", "repository-access",
                                                  lambda: host.repository(repo))]
    if not found[-1].ok:
        return found
    if pull is not None:
        found += [_probe("pull-requests", "Pull requests read", "permissions", lambda: host.pull(repo, pull)),
                  _probe("pull-commits", "Pull requests read", "permissions", lambda: host.pull_commits(repo, pull))]
    if rules.roles:
        found.append(_probe("collaborator-role", "Metadata read", "permissions", lambda: host.role(repo, probe_login)))
    bad = unknown_roles(rules)
    if bad:
        found.append(DoctorFinding("trust-roles", False, f"{', '.join(bad)} prove nothing: use write, maintain or admin"))
    if rules.team:
        found.append(_probe("team-membership", "organization Members read", "permissions",
                            lambda: _team_readable(host, rules.team, probe_login)))
    return found


def _team_readable(host: RepoHost, team: str, login: str) -> None:
    if not host.in_team(team, login):
        raise HostError(404, "the probe login is not an active member: the token may lack organization Members read")
