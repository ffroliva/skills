"""Run one command per cloud box, or one command across shards, on one commit, and print one verdict.

Each box clones the commit, runs its command with $SHARD, $SHARDS and $OUT set, and returns what the command wrote to
$OUT. Nothing from the working tree reaches a box. What a run may do follows its trust level (docs/reference/trust.md):
a run is untrusted unless a pull request's check says otherwise, or the adoption file says `own_work: trusted` and names
its `repo`. Each box's name is printed when it is created, with a live read on a trusted run.

Exit 0 green, 1 red, 2 not runnable (nothing created), 3 no verdict (a box never ran and none failed: credit, quota,
outage), 130 stopped. A box that dies, times out or returns nothing is red, and is never rerun, and a box or credential
left behind is never green. Stop a run with Ctrl+C or SIGTERM: a hard kill leaves its boxes billing until their TTL, then
run --sweep-only.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sbxlib.adapters.clock import SystemClock, new_run_id
from sbxlib.adapters.files import RunDirectory, protected_paths
from sbxlib.adapters.gh_cli import GhCli
from sbxlib.adapters.git_cli import GitCli
from sbxlib.adapters.process import run_command, without_env
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.app.fleet import Edge, ScopedSecret, run_fleet, sweep
from sbxlib.app.trust import PullRequestTrust
from sbxlib.domain.adoption import ADOPTION_FILE, duration_minutes, own_work_problem, own_work_verdict, parse_config, trust_rules, words
from sbxlib.domain.fleet import Mode, RunRequest, parse_custom, refusals, sanitize_project
from sbxlib.domain.profile import PROFILES, RunProfile
from sbxlib.domain.trust import TrustVerdict, untrusted
from sbxlib.ports import Clock, CommandRunner, CommandTimeout, RunIdSource

BUILTIN: dict[str, Any] = {"template": "shell", "cpus": 8, "memory": "16g", "quota": 40, "ttl_minutes": 30, "minutes": 15,
                           "stagger": 2.0}
SLUG = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?$")


def _usd(text: str) -> float:
    value = float(text)
    if not 0 < value < float("inf"):  # nan fails too: a ceiling that compares false with everything is no ceiling
        raise ValueError(f"{text}: must be a positive amount")
    return value


CONFIG_KEYS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "boxes": ("boxes", int), "template": ("template", str), "cpus": ("cpus", int), "memory": ("memory", str),
    "quota_vcpu": ("quota", int), "ttl": ("ttl_minutes", duration_minutes), "minutes": ("minutes", duration_minutes),
    "stagger_s": ("stagger", float), "command": ("commands", lambda value: [value]), "max_usd": ("max_usd", _usd),
}


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value}: must be at least 1")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="https clone URL, with no credentials in it")
    parser.add_argument("--sha", default="HEAD", help="the commit (default: HEAD)")
    parser.add_argument("--pr", type=_positive, help="the pull request this commit belongs to: its level comes from the "
                        "trust check, and the box fetches its head")
    parser.add_argument("--config", type=Path, help=f"adoption file ({ADOPTION_FILE}); a flag wins over it")
    parser.add_argument("--command", action="append", dest="commands",
                        help="once with --boxes for shards; repeat for one command per box (or `command` in --config)")
    parser.add_argument("--boxes", type=_positive, help="boxes for one command, which reads $SHARD of $SHARDS (default: 1)")
    parser.add_argument("--template", help="shell, which runs Docker on sbx 0.51.0, or a kit reference such as ./kit. "
                        "shell-docker was the 0.50 route and is refused on 0.51.0")
    parser.add_argument("--cpus", type=_positive, help="vCPU per box (default: 8)")
    parser.add_argument("--memory", help="memory per box (default: 16g)")
    parser.add_argument("--quota", type=_positive, help="your account's vCPU limit; a larger fleet is refused (default: 40)")
    parser.add_argument("--ttl-minutes", type=_positive, help="box time-to-live; the box is deleted at it (default: 30)")
    parser.add_argument("--minutes", type=_positive, help="wall-clock limit, below the TTL; a box past it is red (default: 15)")
    parser.add_argument("--allow", action="append", default=[], help="an extra egress host; repeat")
    parser.add_argument("--env", action="append", default=[], metavar="NAME",
                        help="pass the host variable NAME to every box. The value is read from this shell, never from "
                        "argv. It sits in the box's environment in plain text; trusted runs only; repeat")
    parser.add_argument("--secret-service", default="", help="sbx secret service for a private clone, such as github; "
                        "or custom:<exact host>:<ENV> for a header secret")
    parser.add_argument("--secret-env", default="", help="environment variable holding that secret's value")
    parser.add_argument("--stagger", type=float, help="seconds between creates (default: 2)")
    parser.add_argument("--no-junit", action="store_true", help="judge by exit code alone")
    parser.add_argument("--expect-tests", type=_positive, help="the JUnit cases the whole run must run, skips not counted: fewer is "
                        "red, said as ran, skipped and lost, and on a gate that is red by design it tells a complete run from one "
                        "that died")
    parser.add_argument("--means", default="", help="what green means here, printed with the verdict: on a planted fault, green "
                        "means the fault was caught")
    parser.add_argument("--label", action="append", default=[], help="a name for a box in this run's output, once per box "
                        "in order, such as the server it holds")
    parser.add_argument("--max-usd", type=_usd, help="refuse a run whose worst case, every box billing to its TTL, costs more "
                        "(or `max_usd` in --config)")
    parser.add_argument("--sweep-only", action="store_true", help="remove this project's fleet boxes and their scoped "
                        "secrets, then exit. Never while another of this project's runs is live")
    parser.add_argument("--project", help="the target project's name in box names (default: target_project, then the repo)")
    parser.add_argument("--out", type=Path, help="an empty folder for results (default: a new temp folder)")
    return parser


def _settings(args: argparse.Namespace, config: dict[str, str]) -> None:
    """Fill every setting a flag left unset from the adoption file, then from the built-in default."""
    if config.get("target", "cloud") != "cloud":
        raise ValueError(f"target: {config['target']}: this fleet only runs cloud boxes")
    values: dict[str, Any] = {}
    for key, (setting, convert) in CONFIG_KEYS.items():
        if config.get(key):
            try:
                values[setting] = convert(config[key])
            except ValueError as exc:
                raise ValueError(f"{key}: {exc}") from exc
    if len(args.commands or []) > 1:
        values.pop("boxes", None)  # several --command flags fix the box count
    service = config.get("secret_service", "")
    args.secret_service = args.secret_service or ("" if service == "none" else service)
    args.secret_env = args.secret_env or config.get("secret_env", "")
    for setting in (*BUILTIN, "boxes", "commands", "max_usd"):
        if getattr(args, setting, None) is None:
            setattr(args, setting, values.get(setting, BUILTIN.get(setting)))


def _config(args: argparse.Namespace) -> dict[str, str]:
    if not args.config:
        return {}
    if not args.config.is_file():
        raise ValueError(f"--config {args.config}: no such file; run sbx_onboard.py")
    return parse_config(args.config.read_text(encoding="utf-8"))


def _project(args: argparse.Namespace, config: dict[str, str]) -> str:
    name = args.project or config.get("target_project") or (args.repo or "").rstrip("/").rpartition("/")[2].removesuffix(".git")
    return sanitize_project(name)


def _commands(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.commands * (args.boxes or 1)) if len(args.commands) == 1 else tuple(args.commands)


def _level(args: argparse.Namespace, config: dict[str, str], sha: str, gh: CommandRunner) -> TrustVerdict:
    """Fails closed: a level comes from a check or from the project's file, never from a flag."""
    if args.pr is None:
        return own_work_verdict(config, args.repo or "", sha)
    slug = SLUG.fullmatch(args.repo or "")
    if not slug:
        return untrusted("repo-not-on-github", sha=sha)
    host = GhCli(gh, os.environ.get("GH_TOKEN", ""))
    source = PullRequestTrust(host, trust_rules(config), protected_paths(args.config or Path(ADOPTION_FILE), args.template))
    return source.check(slug[1], args.pr, sha)


def _request(args: argparse.Namespace, config: dict[str, str], sha: str, run_id: RunIdSource) -> RunRequest:
    commands = _commands(args)
    mode = Mode.PULL if args.pr is not None else Mode.SHARDS if len(commands) > 1 else Mode.TARGETED
    custom = parse_custom(args.secret_service)
    allow = (*words(config.get("allow", "")), *args.allow, *([custom[0]] if custom else []))
    return RunRequest(
        args.repo or "", sha, commands, _project(args, config), run_id(), mode, args.template, args.cpus, args.memory,
        args.quota, args.ttl_minutes, args.minutes, allow, args.secret_service, tuple(dict.fromkeys(args.env)),
        frozenset(words(config.get("allowed_secrets", ""))), config.get("network_policy", ""),
        config.get("clone", "public"), args.pr, args.stagger, not args.no_junit, tuple(args.label), args.expect_tests, args.means,
        args.max_usd, len(args.commands) > 1)


def _env_refusal(args: argparse.Namespace) -> str:
    if args.secret_service and not os.environ.get(args.secret_env or "\0"):
        return "--secret-service needs --secret-env naming a set environment variable"
    missing = [name for name in args.env if "=" not in name and not os.environ.get(name)]
    return f"--env {missing[0]}: not set in this shell, or empty" if missing else ""


def _say(line: str) -> None:
    with contextlib.suppress(OSError):  # a closed terminal must not skip the final proof and the verdict
        print(line, flush=True)


def _edge(sbx: CommandRunner, out_dir: Path, clock: Clock) -> Edge:
    cli = SbxCli(sbx)
    return Edge(cli, cli, RunDirectory(out_dir), clock, _say)


def _hidden(args: argparse.Namespace) -> set[str]:
    """Variables `sbx` must not inherit: only a bare --env NAME is meant for it, and it reads that one from its environment."""
    return {"GH_TOKEN", args.secret_env} - set(args.env)


def _refused(config: dict[str, str], request: RunRequest, profile: RunProfile) -> list[str]:
    """A file that contradicts itself has one fix: the untrusted profile's own lines would send the reader elsewhere."""
    problem = own_work_problem(config)
    return [problem] if problem else refusals(request, profile)


def planned_refusals(config: dict[str, str], repo: str, commands: tuple[str, ...] = ()) -> list[str]:
    """Why a run of this file, with these `--command`s and no other flag, would be refused: what `sbx_check.py` must see."""
    args = _parser().parse_args(["--repo", repo, *(f"--command={command}" for command in commands)])
    try:
        _settings(args, config)
    except ValueError as exc:
        return [str(exc)]
    if not args.commands:
        return ["no command: set `command`, or pass --command"]
    trust = own_work_verdict(config, repo, "0" * 40)
    request = _request(args, config, "0" * 40, lambda: "0000")
    return [f"level {trust.level.value} ({trust.rule}): {line}"
            for line in (*_refused(config, request, PROFILES[trust.level]), *filter(None, [_env_refusal(args)]))]


def main(argv: list[str] | None = None, sbx: CommandRunner | None = None, git: CommandRunner = run_command,
         gh: CommandRunner = run_command, clock: Clock | None = None, run_id: RunIdSource = new_run_id) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(errors="replace")  # a cp1252 pipe must not crash on a non-Latin error
    clock = clock or SystemClock()
    args = _parser().parse_args(argv)
    try:
        config = _config(args)
        if not args.sweep_only:
            _settings(args, config)
    except ValueError as exc:
        print(f"fleet: {exc}")
        return 2
    runner = sbx or without_env(_hidden(args))
    if args.sweep_only:
        return sweep(_project(args, config), _edge(runner, Path(tempfile.gettempdir()), clock))
    if not args.commands:
        print("fleet: no command: pass --command, or set `command` in the file given to --config")
        return 2
    source = GitCli(git)
    try:
        # A pull request's head may be absent from the host clone (a fork's): the trust check names it, so a full sha is kept.
        sha = args.sha if args.pr is not None and re.fullmatch(r"[0-9a-f]{40}", args.sha) else source.resolve(args.sha)
        trust = _level(args, config, sha, gh)
        profile = PROFILES[trust.level]
        request = _request(args, config, sha, run_id)
        found = [*_refused(config, request, profile), *filter(None, [_env_refusal(args)])]
        if found:
            print(f"fleet: level {trust.level.value} ({trust.rule}): refused before any box was created")
            print("\n".join(f"fleet: {line}" for line in found))
            return 2
        if args.pr is None and not source.on_remote(sha, args.repo):
            print(f"fleet: {sha or args.sha} is not on the remote, at a branch or tag or below one: push it first; boxes clone from there.")
            return 2
    except CommandTimeout as exc:  # a credential prompt on ls-remote hangs here: nothing was created, so this is not red
        print(f"fleet: {exc}: nothing was created")
        return 2
    out_dir = args.out or Path(tempfile.mkdtemp(prefix=f"fleet-{sha[:9]}-"))
    edge = _edge(runner, out_dir, clock)
    if edge.files.has_results():
        print(f"fleet: --out {out_dir} already holds files: an earlier run's JUnit would count as this run's. Use an empty folder.")
        return 2
    secret = ScopedSecret(args.secret_service, os.environ[args.secret_env]) if args.secret_service else None

    def on_sigterm(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    # SIGBREAK (Windows CTRL_BREAK, how a console or process group is stopped) ends a Python process with no clean-up unless handled.
    # SIGHUP does the same on Linux and macOS when a terminal closes or an SSH session drops.
    names = [name for name in ("SIGTERM", "SIGBREAK", "SIGHUP") if hasattr(signal, name)]
    previous = {name: signal.signal(getattr(signal, name), on_sigterm) for name in names}
    try:
        return run_fleet(request, profile, trust, edge, secret, tuple(os.environ.get(name, "") for name in args.env))
    finally:
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)


if __name__ == "__main__":
    sys.exit(main())
