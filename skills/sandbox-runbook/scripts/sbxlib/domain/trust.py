"""Who a project trusts is the project's configuration; this module only applies it, to one exact commit.

Fails closed: anything not proven trusted is untrusted. `author_association` is shown as evidence and never decides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

_CLONE_URL = re.compile(r"(?:https://|ssh://git@|git@)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)[/:]([\w.-]+(?:/[\w.-]+)+?)(?:\.git)?/?")
_SLUG = re.compile(r"[\w.-]+/[\w.-]+")


class TrustLevel(Enum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


# `read` and `triage` prove nothing: GitHub answers `read` for anyone on a public repository.
TRUSTABLE_ROLES = frozenset({"admin", "maintain", "write"})
PAGE = 100  # one page per listing; a longer pull request stays untrusted


@dataclass(frozen=True)
class TrustRules:
    roles: frozenset[str] = frozenset()
    team: str = ""  # org/team-slug
    logins: frozenset[str] = frozenset()
    repo: str = ""  # the project's repository, from the adoption file: the only one these rules speak for

    def __bool__(self) -> bool:
        return bool(self.roles or self.team or self.logins)


@dataclass(frozen=True)
class Standing:
    """What the host says about one login."""

    role: str = ""
    teams: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PullFacts:
    number: int
    head_sha: str
    state: str
    author: str
    author_association: str
    head_repo: str
    base_repo: str
    commit_count: int
    commit_authors: tuple[str, ...]  # one per commit, in order; "" when GitHub maps it to no account
    file_count: int
    files: tuple[str, ...]
    standings: dict[str, Standing] = field(default_factory=dict[str, Standing])
    renamed_from: tuple[str, ...] = ()  # a rename lists only its new path in `files`


@dataclass(frozen=True)
class TrustVerdict:
    level: TrustLevel
    rule: str
    evidence: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {"level": self.level.value, "rule": self.rule, "evidence": self.evidence}


def untrusted(rule: str, **evidence: object) -> TrustVerdict:
    return TrustVerdict(TrustLevel.UNTRUSTED, rule, evidence)


def unknown_roles(rules: TrustRules) -> list[str]:
    return sorted(rules.roles - TRUSTABLE_ROLES)


def repo_id(text: str) -> str:
    """`host/owner/name` in lower case for any spelling of a repository; '' for anything else. `owner/name` means GitHub."""
    clean = text.strip().lower()
    url = _CLONE_URL.fullmatch(clean)
    if url:
        return f"{url[1]}/{url[2].removesuffix('.git')}"
    return f"github.com/{clean.removesuffix('.git')}" if _SLUG.fullmatch(clean) else ""


def repo_rule(project: str, repo: str) -> str:
    """'' only when `repo` is the repository the adoption file names: rules say nothing about any other."""
    if not repo_id(project):
        return "repo-not-declared"
    return "" if repo_id(project) == repo_id(repo) else "repo-mismatch"


def _path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").strip("/").casefold()  # a case-blind host reads DOCS/SBX.md as the same file


def touches(files: Iterable[str], protected: Iterable[str]) -> bool:
    """A listed path is a protected one, sits inside one (a kit folder), or replaces a folder holding one."""
    guarded = {_path(path) for path in protected}
    return any(name == path or path.startswith(f"{name}/") or name.startswith(f"{path}/")
               for name in map(_path, files) for path in guarded)


def _grant(rules: TrustRules, login: str, standings: dict[str, Standing]) -> str:
    """The rule that trusts `login`, or ''. An allow list wins over a role, a role over a team: the most specific first."""
    if login.lower() in {name.lower() for name in rules.logins}:
        return f"login:{login}"
    standing = standings.get(login, Standing())
    if standing.role in rules.roles & TRUSTABLE_ROLES:
        return f"role:{standing.role}"
    return f"team:{rules.team}" if rules.team and rules.team in standing.teams else ""


def decide(rules: TrustRules, facts: PullFacts, sha: str, protected: tuple[str, ...]) -> TrustVerdict:
    """`protected` holds every repository path a decision reads; empty when the rules' own file is in no repository."""
    evidence: dict[str, object] = {
        "sha": sha, "head_sha": facts.head_sha, "pull": facts.number, "author": facts.author,
        "author_association": facts.author_association, "head_repo": facts.head_repo, "base_repo": facts.base_repo}
    rule = _refusal(rules, facts, sha, protected)
    if rule:
        return untrusted(rule, **evidence)
    granted = _grant(rules, facts.author, facts.standings)
    if not granted:
        return untrusted("no-rule-matched", **evidence)
    foreign = sorted({name or "unknown" for name in facts.commit_authors if not _grant(rules, name, facts.standings)})
    if foreign:
        return untrusted("foreign-commit", **evidence, foreign_commit_authors=foreign)
    return TrustVerdict(TrustLevel.TRUSTED, granted, evidence)


def _refusal(rules: TrustRules, facts: PullFacts, sha: str, protected: tuple[str, ...]) -> str:
    if not rules:
        return "no-rules"
    bound = repo_rule(rules.repo, facts.base_repo)
    if bound:
        return bound
    if repo_id(facts.head_repo) != repo_id(facts.base_repo):
        return "fork-head"  # GitHub maps a commit's author from a free-form email: only this repository's own branches are vouched for
    if facts.head_sha != sha:
        return "sha-changed"
    if facts.state != "open":
        return "pull-not-open"
    complete = facts.commit_count == len(facts.commit_authors) and facts.file_count == len(facts.files)
    if not complete or facts.commit_count > PAGE or facts.file_count > PAGE:
        return "listing-incomplete"
    if not protected:
        return "adoption-file-not-in-repo"
    return "adoption-file-changed" if touches((*facts.files, *facts.renamed_from), protected) else ""
