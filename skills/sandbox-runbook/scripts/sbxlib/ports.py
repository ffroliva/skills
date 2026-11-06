"""The interfaces the application needs from the outside world."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .domain.fleet import BoxResult, RunRequest
from .domain.profile import OutputPolicy


class CommandTimeout(Exception):
    """A command outlived its timeout."""


class Unreadable(Exception):
    """A listing could not be read. Never read an unknown as empty or free."""


class HostError(Exception):
    """The repository host refused or could not answer. `status` is 0 when no request was made."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Done:
    """A finished command: the only process result the application sees."""

    rc: int
    out: str = ""
    err: str = ""


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done: ...


@dataclass(frozen=True)
class BoxRow:
    name: str
    cpus: int


@dataclass(frozen=True)
class SecretRow:
    name: str
    scope: str  # a box name, or "global"
    hosts: tuple[str, ...] = ()  # a custom secret's destinations


@dataclass(frozen=True)
class AccountPolicy:
    mode: str  # deny-all, balanced or allow-all
    allow: tuple[str, ...] = ()  # hosts the account itself allows, for every box


class SandboxRuntime(Protocol):
    def create(self, name: str, request: RunRequest) -> Done: ...
    def run(self, box: str, *argv: str, timeout: int = 300) -> Done: ...
    def upload(self, path: str, box: str, target: str) -> Done: ...
    def download(self, box: str, source: str, path: str) -> Done: ...
    def remove(self, box: str) -> Done: ...
    def boxes(self) -> list[BoxRow]: ...
    def account_policy(self) -> AccountPolicy: ...
    def version(self) -> str | None: ...


class CliSurface(Protocol):
    def version(self) -> str | None: ...
    def help(self, words: tuple[str, ...]) -> str | None: ...


class SecretStore(Protocol):
    def set_scoped(self, box: str, service: str, value: str) -> Done: ...
    def remove_scoped(self, box: str, name: str) -> Done: ...
    def secrets(self) -> list[SecretRow]: ...


class RepoHost(Protocol):
    def pull(self, repo: str, number: int) -> Mapping[str, Any]: ...
    def pull_commits(self, repo: str, number: int) -> list[Mapping[str, Any]]: ...
    def pull_files(self, repo: str, number: int) -> list[tuple[str, str]]: ...  # (path, the path it was renamed from, or '')
    def role(self, repo: str, login: str) -> str: ...
    def in_team(self, team: str, login: str) -> bool: ...
    def repository(self, repo: str) -> Mapping[str, Any]: ...
    def has_token(self) -> bool: ...


class SourceControl(Protocol):
    def resolve(self, ref: str) -> str: ...
    def on_remote(self, sha: str, remote: str) -> bool: ...
    def remote_readable(self, remote: str) -> bool: ...
    def dirty(self) -> bool: ...


class RunFiles(Protocol):
    def has_results(self) -> bool: ...
    def write_script(self, box: str, text: str) -> str: ...
    def archive(self, box: str) -> str: ...
    def read_result(self, index: int, box: str, seconds: float, policy: OutputPolicy) -> BoxResult: ...
    def write_verdict(self, body: Mapping[str, object]) -> None: ...


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class RunIdSource(Protocol):
    def __call__(self) -> str: ...
