"""Validate an adoption file and the environment before a run. Every failure names its fix; an unknown is never fine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..domain.adoption import PLACEHOLDER, duration_minutes, words
from ..domain.drift import version_tuple
from ..domain.fleet import SHAPES, is_fleet_box, open_account_hosts, sanitize_project, shape_problem, template_problem
from ..domain.known_errors import anchor_for
from ..ports import BoxRow, CommandTimeout, SandboxRuntime, SecretRow, SecretStore, SourceControl, Unreadable
from .fleet import exposure

MIN_VERSION = (0, 50, 0)  # the findings this skill cites were measured from here on
REQUIRED = ("target_project", "repo", "target", "template", "boxes", "cpus", "memory", "quota_vcpu", "clone", "secret_service",
            "command")


class Severity(Enum):
    BLOCK = "FAIL"
    WARN = "WARN"


@dataclass(frozen=True)
class Finding:
    name: str
    ok: bool
    fix: str = ""
    severity: Severity = Severity.BLOCK


def _int(config: Mapping[str, str], key: str) -> int | None:
    try:
        return int(config.get(key, ""))
    except ValueError:
        return None


def _config(config: Mapping[str, str], det: Mapping[str, Any], per_box: bool) -> list[Finding]:
    missing = [key for key in REQUIRED if not config.get(key)]
    project, command = config.get("target_project", ""), config.get("command", "")
    template = template_problem(config.get("template", ""))
    clone, service = config.get("clone"), config.get("secret_service")
    no_secret = clone == "token" and (service in ("", "none", None) or not config.get("secret_env"))
    boxes, cpus = _int(config, "boxes") or 1, _int(config, "cpus") or 0
    return [
        Finding("config-keys", not missing, f"add {', '.join(missing)} to the sbx-config block, or rerun sbx_onboard.py on this "
                "file (with its --config), which adds every missing setting and keeps yours"),
        Finding("template", not template, template),
        Finding("command", PLACEHOLDER not in command, f"write the real command: it still holds `{PLACEHOLDER} ...>`"),
        Finding("shards", boxes == 1 or per_box or "SHARD" in command, f"{boxes} boxes would each run the whole suite: "
                "read $SHARD of $SHARDS in the command, set boxes: 1, or pass --command once per box to repeat it"),
        Finding("shape", not shape_problem(cpus, config.get("memory", "")), shape_problem(cpus, config.get("memory", ""))
                or f"use one of {sorted(SHAPES)}"),
        Finding("target-project", sanitize_project(project) == project, f"use {sanitize_project(project)}: sbx refuses others"),
        Finding("clone", not (clone == "public" and det.get("repo_visibility") == "private"),
                "the repo is private: set clone: token, secret_service: github and secret_env"),
        Finding("secret-service", not no_secret, "a token clone needs secret_service: github and secret_env: <variable>"),
    ]


def _deadline_ok(config: Mapping[str, str]) -> bool:
    try:
        return not config.get("minutes") or duration_minutes(config["minutes"]) < duration_minutes(config["ttl"])
    except (KeyError, ValueError):
        return True  # a missing or malformed ttl is the ttl finding's to report


def _ttl_ok(config: Mapping[str, str]) -> bool:
    try:
        return duration_minutes(config.get("ttl", "")) > 0
    except ValueError:
        return False


def _bounds(config: Mapping[str, str]) -> list[Finding]:
    return [Finding("ttl", _ttl_ok(config), "set ttl: 30m. Without one a lost client bills until the server stops it"),
            Finding("on-timeout", config.get("on_timeout") == "delete",
                    "set on_timeout: delete, passed as --on-timeout delete; the default keeps the box"),
            Finding("deadline", _deadline_ok(config),
                    f"set minutes below ttl ({config.get('ttl')}): a box past its TTL takes its partial results with it")]


def _version(runtime: SandboxRuntime) -> list[Finding]:
    version = runtime.version()
    if not version:
        return [Finding("sbx-installed", False, "install Docker Sandboxes (see the skill's docs/resources.md), then rerun")]
    return [Finding("sbx-installed", True), Finding("sbx-version", version_tuple(version) >= MIN_VERSION,
                                                    "update sbx: the cited findings start at 0.50.0")]


def _account(config: Mapping[str, str], runtime: SandboxRuntime, secrets: SecretStore) -> list[Finding]:
    try:
        boxes = runtime.boxes()
    except (Unreadable, CommandTimeout) as exc:
        anchor = anchor_for(str(exc)) or "docs/troubleshooting.md#not-signed-in"
        return [Finding("account", False, f"cannot read the account ({exc}): see {anchor}")]
    found = [Finding("account", True)]
    planned, quota = (_int(config, "boxes") or 0) * (_int(config, "cpus") or 0), _int(config, "quota_vcpu")
    used = sum(row.cpus for row in boxes)
    found.append(Finding("quota", quota is not None and used + planned <= quota,
                         f"{used} vCPU running + {planned} planned > {quota}: lower boxes, or wait for the live boxes"))
    try:
        rows = secrets.secrets()
    except (Unreadable, CommandTimeout) as exc:
        return [*found, Finding("leftover-secrets", False, f"cannot read the secrets: {exc}")]
    live = {row.name for row in boxes}
    project = config.get("target_project", "")
    left = [row for row in rows if is_fleet_box(row.scope, project) and row.scope not in live]
    fixes = "; ".join(f"sbx --cloud secret rm {row.name} --sandbox {row.scope} --force" for row in left)
    return [*found, Finding("leftover-secrets", not left, fixes), *_untrusted_ready(config, runtime, rows, boxes)]


def _untrusted_ready(config: Mapping[str, str], runtime: SandboxRuntime, rows: list[SecretRow],
                     boxes: list[BoxRow]) -> list[Finding]:
    """What the fleet reads from the account before an untrusted run. A project trusting its own work may still take one."""
    trusted = config.get("own_work") == "trusted"
    allow = words(config.get("allow", ""))
    if trusted:
        exposed = exposure(rows, allow, boxes)
        return [Finding("global-secrets", not exposed, "; ".join(exposed), Severity.WARN)]
    try:
        policy = runtime.account_policy()
    except (Unreadable, CommandTimeout) as exc:
        exposed = exposure(rows, allow, boxes)
        return [Finding("global-secrets", not exposed, "; ".join(exposed)),
                Finding("network-default", False, f"cannot read the account's default: {exc}")]
    exposed, open_hosts = exposure(rows, (*allow, *policy.allow), boxes), open_account_hosts(policy.allow)
    fix = f"the account's default is {policy.mode}, and an untrusted run needs deny-all: `sbx --cloud policy init deny-all`"
    return [Finding("global-secrets", not exposed, "; ".join(exposed)),
            Finding("network-default", policy.mode == "deny-all" and not open_hosts, "; ".join(open_hosts) or fix)]


def _git(source: SourceControl, sha: str | None) -> list[Finding]:
    head = source.resolve("HEAD")
    if not head:
        return [Finding("git-repo", False, "no commit here: run from the project root, or `git init`, commit and "
                                           "`git remote add origin <https url>`")]
    found: list[Finding] = []
    if sha is not None:
        found.append(Finding("sha-is-head", sha in (head, "HEAD"), f"--sha {sha} is not HEAD ({head[:9]}): this check reads "
                             "the working tree at HEAD. Check out that commit, or pass --sha HEAD"))
    if not source.remote_readable("origin"):
        return [*found, Finding("remote", False, "cannot read `origin`: add it, or check your access to it")]
    return [*found, Finding("pushed", source.on_remote(head, "origin"),
                            f"run `git push`: boxes clone from the remote and {head[:9]} is not on it"),
            Finding("working-tree", not source.dirty(), "commit or stash: a box sees only the pushed commit")]


def _drift(report: Mapping[str, Any]) -> list[Finding]:
    """Drift warns; a command the scripts call being gone is the one thing that refuses a run."""
    found: list[Finding] = []
    if report.get("missing_verbs"):
        found.append(Finding("sbx-commands", False, f"this sbx no longer has {', '.join(report['missing_verbs'])}, which the "
                             "scripts call: run `sbx_drift.py check`, then see SKILL.md, when this skill goes stale"))
    detail = "; ".join(report.get("lines", [])[:6]) or report.get("status", "unknown")
    found.append(Finding("drift", report.get("status") == "aligned", f"{detail}. Run `sbx_drift.py check`", Severity.WARN))
    return found


def run_check(config: Mapping[str, str], det: Mapping[str, Any], runtime: SandboxRuntime, secrets: SecretStore,
              source: SourceControl, sha: str | None = None, drift: Callable[[], Mapping[str, Any]] | None = None,
              trust: Callable[[], list[Finding]] | None = None, plan: Callable[[], list[str]] | None = None,
              commands: tuple[str, ...] = ()) -> list[Finding]:
    """`commands` are the `--command` flags a run will pass: they stand in for `command`, and several set the box count."""
    if commands:
        config = {**config, "command": "\n".join(commands), **({"boxes": str(len(commands))} if len(commands) > 1 else {})}
    found = _config(config, det, len(commands) > 1)
    cloud = config.get("target") != "local"
    if cloud:
        found += _bounds(config)
    if cloud and plan:
        refused = plan()
        found.append(Finding("fleet-plan", not refused, "; ".join(refused)))
    try:
        version = _version(runtime)
    except CommandTimeout:
        version = [Finding("sbx-installed", False, "sbx did not answer: rerun, or run `sbx diagnose`")]
    found += version
    if cloud and version[0].ok:
        found += _account(config, runtime, secrets)
    found += _drift(drift()) if drift else []
    found += trust() if trust else []
    return found + (_git(source, sha) if config.get("clone") in ("public", "token") else [])
