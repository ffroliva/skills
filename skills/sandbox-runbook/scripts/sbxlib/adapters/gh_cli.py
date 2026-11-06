"""GitHub through `gh api`, behind the RepoHost port.

Reads only. gh takes the token from GH_TOKEN in its own environment: the token is never in argv, and with no GH_TOKEN
nothing is called, so a person's own `gh auth login` cannot stand in for the read-only token.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import quote

from ..domain.fleet import scrub
from ..domain.trust import PAGE
from ..ports import CommandRunner, CommandTimeout, HostError

_STATUS = re.compile(r"HTTP (\d{3})")


def release_tags(run: CommandRunner) -> list[str] | None:
    """Tags of docker/sbx-releases, read with whatever `gh` is logged in as: this is public. None when unreadable."""
    try:
        done = run(["gh", "release", "list", "--repo", "docker/sbx-releases", "--limit", "100", "--json", "tagName"], None, 60)
    except CommandTimeout:
        return None
    if done.rc != 0:
        return None
    try:
        return [str(row["tagName"]) for row in json.loads(done.out)]
    except (ValueError, KeyError, TypeError):
        return None


class GhCli:
    def __init__(self, run: CommandRunner, token: str) -> None:
        self._run = run
        self._token = token

    def has_token(self) -> bool:
        return bool(self._token)

    def _api(self, path: str) -> Any:
        if not self._token:
            raise HostError(0, "GH_TOKEN is not set")
        done = self._run(["gh", "api", path], None, 30)
        if done.rc != 0:
            status = _STATUS.search(done.err)
            raise HostError(int(status[1]) if status else 0, scrub(done.err.strip(), (self._token,))[-300:])
        try:
            return json.loads(done.out)
        except ValueError as exc:
            raise HostError(0, f"{path}: not JSON") from exc

    def pull(self, repo: str, number: int) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self._api(f"repos/{repo}/pulls/{number}"))

    def pull_commits(self, repo: str, number: int) -> list[Mapping[str, Any]]:
        return cast(list[Mapping[str, Any]], self._api(f"repos/{repo}/pulls/{number}/commits?per_page={PAGE}"))

    def pull_files(self, repo: str, number: int) -> list[tuple[str, str]]:
        rows = cast(list[Mapping[str, Any]], self._api(f"repos/{repo}/pulls/{number}/files?per_page={PAGE}"))
        return [(str(row.get("filename")), str(row.get("previous_filename") or "")) for row in rows]

    def role(self, repo: str, login: str) -> str:
        data = cast(Mapping[str, Any], self._api(f"repos/{repo}/collaborators/{quote(login)}/permission"))
        return str(data.get("role_name") or "")

    def in_team(self, team: str, login: str) -> bool:
        org, _, slug = team.partition("/")
        try:
            data = cast(Mapping[str, Any], self._api(f"orgs/{org}/teams/{slug}/memberships/{quote(login)}"))
        except HostError as exc:
            if exc.status == 404:  # also what a token with no Members permission gets: both stay untrusted
                return False
            raise
        return data.get("state") == "active"

    def repository(self, repo: str) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self._api(f"repos/{repo}"))
