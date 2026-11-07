"""Fakes at the process edge. The real adapters run on top of them, so every test drives the real argv-building code."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from helpers import SKILL, result_tar

from sbxlib.ports import CommandTimeout, Done

SNAPSHOT: dict[str, Any] = json.loads((SKILL / "references" / "cli-snapshot.json").read_text(encoding="utf-8"))
GLOBAL_FLAGS = ("--cloud", "--no-input")
VERBS_WITH_SUB = ("secret set-custom", "secret set", "secret rm", "secret ls", "policy ls")


class FakeSandbox:
    """Stub sbx: flags follow the 0.51.0 snapshot; its cloud row shape is recorded in tests/fixtures/sbx from gate3."""

    def __init__(self, tars: Mapping[int, bytes] | None = None, version: str = "0.51.0") -> None:
        self.calls: list[list[str]] = []
        self.stdins: list[str | None] = []
        self.tars = dict(tars or {})
        self.boxes: dict[str, dict[str, Any]] = {}
        self.secrets: list[dict[str, Any]] = []
        self.create_errors: list[str] = []  # stderr for the next creates, one each
        self.fail_rm = 0  # the next `rm` calls fail
        self.late_box = ""  # a create that never answers 0, and whose box appears after `late_after_ls` listings
        self.late_after_ls = 1
        self.late_rc: int | None = None  # that create's exit; None times out
        self.late_created = False
        self.never_done: set[str] = set()
        self.gone_after_create: set[str] = set()
        self.fail: dict[str, Done] = {}  # verb -> a forced answer
        self.raises: set[str] = set()  # verbs that time out
        self.policy_mode = "deny-all"  # the account default `policy ls --json` reports
        self.policy_allow: Any = []  # its allow_networks, the documented shape; only an empty list has been seen live
        self.version_text = f"sbx version v{version} abcdef"
        self.on_call: Callable[[list[str]], None] | None = None
        self._lock = threading.Lock()

    def __call__(self, argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
        raw = list(argv)[1:]
        with self._lock:
            self.calls.append(raw)
            self.stdins.append(stdin)
        if self.on_call:
            self.on_call(raw)
        bad_global = _unknown_global(raw)
        if bad_global:
            return Done(1, "", f"unknown flag: {bad_global}")
        args = _strip_global(raw)
        if args == ["version"]:
            return Done(0, self.version_text)
        verb = _verb(args)
        if verb in self.raises:
            raise CommandTimeout(f"sbx {verb} timed out")
        if verb in self.fail:
            return self.fail[verb]
        unknown = _unknown_flag(args, verb)
        if unknown:
            return Done(1, "", f"unknown flag: {unknown}")
        return getattr(self, "_" + verb.replace(" ", "_").replace("-", "_"))(args, stdin)

    def _create(self, args: list[str], _stdin: str | None) -> Done:
        name = args[args.index("--name") + 1]
        if name in self.boxes:
            return Done(1, "", f"sandbox {name} already exists")
        if self.create_errors:
            return Done(1, "", self.create_errors.pop(0))
        if self.late_box == name:
            self.late_created = True
            if self.late_rc is not None:
                return Done(self.late_rc)
            raise CommandTimeout("create timed out")
        self.boxes[name] = {"name": name, "id": f"sbx_{name}", "agent": "shell", "status": "running",
                            "cpus": int(args[args.index("--cpus") + 1]), "memory_mib": 4096, "image": "sbx/shell",
                            "created_at": "2026-11-05T00:00:00Z", "expires_at": "2026-11-05T01:00:00Z"}
        return Done(0)

    def _exec(self, args: list[str], _stdin: str | None) -> Done:
        box = args[1]
        polling = args[2:4] == ["test", "-f"]
        if (polling and box in self.gone_after_create) or box not in self.boxes:
            return Done(125, "", f"sandbox {box} not found")
        if polling and box in self.never_done:
            return Done(1)
        return Done(0)

    def _cp(self, args: list[str], _stdin: str | None) -> Done:
        source, target = args[1:3]
        box = (source if ":" in source and not re.match(r"[A-Za-z]:", source) else target).split(":")[0]
        if box not in self.boxes:
            return Done(1, "", f"{box}: not found")
        if target.endswith(".tgz"):
            match = re.search(r"-(\d+)-[a-z0-9]{4}$", box)
            Path(target).write_bytes(self.tars.get(int(match[1]) if match else 1, result_tar()))
        return Done(0)

    def _rm(self, args: list[str], _stdin: str | None) -> Done:
        if self.fail_rm:
            self.fail_rm -= 1
            return Done(1, "", "status code: 429")
        self.boxes.pop(args[-1], None)
        return Done(0)

    def _ls(self, _args: list[str], _stdin: str | None) -> Done:
        rows = list(self.boxes.values())
        if self.late_created:
            self.late_after_ls -= 1
            if self.late_after_ls == 0:
                self.boxes[self.late_box] = {"name": self.late_box, "cpus": 8}  # appears after the listing that missed it
                self.late_box, self.late_created = "", False
        return Done(0, json.dumps(rows))

    def _secret_set(self, args: list[str], stdin: str | None) -> Done:
        if not stdin:
            return Done(1, "", "no value")
        self.secrets.append({"scope": args[args.index("--sandbox") + 1], "type": "service", "name": args[-1]})
        return Done(0)

    def _secret_set_custom(self, args: list[str], stdin: str | None) -> Done:
        if not stdin:
            return Done(1, "", "no value")
        host = args[args.index("--host") + 1]
        name = args[args.index("--name") + 1] if "--name" in args else host.replace(".", "-")
        self.secrets.append({"scope": args[args.index("--sandbox") + 1], "type": "service", "name": name,
                             "secret_type": "custom", "hosts": [host], "env": args[args.index("--env") + 1]})
        return Done(0)

    def _secret_rm(self, args: list[str], _stdin: str | None) -> Done:
        scope, name = args[args.index("--sandbox") + 1], args[2]
        kept = [row for row in self.secrets if (row["scope"], row["name"]) != (scope, name)]
        if len(kept) == len(self.secrets):
            return Done(1, "", "not found")
        self.secrets = kept
        return Done(0)

    def _secret_ls(self, _args: list[str], _stdin: str | None) -> Done:
        return Done(0, json.dumps({"secrets": self.secrets}))

    def _policy_ls(self, _args: list[str], _stdin: str | None) -> Done:
        return Done(0, json.dumps({"mode": self.policy_mode, "allow_networks": self.policy_allow, "deny_networks": []}))

    def verbs(self) -> list[str]:
        return [_verb(call) for call in self.calls if _strip_global(call) != ["version"]]

    def stdin_of(self, verb: str) -> str | None:
        return next(stdin for call, stdin in zip(self.calls, self.stdins, strict=True) if _verb(call) == verb)


def _strip_global(args: Sequence[str]) -> list[str]:
    index = 0
    while index < len(args) and args[index] in GLOBAL_FLAGS:
        index += 1
    return list(args[index:])


def _unknown_global(args: Sequence[str]) -> str:
    for word in args:
        if not word.startswith("-"):
            return ""
        if word not in GLOBAL_FLAGS:
            return word
    return ""


def _verb(args: Sequence[str]) -> str:
    words = _strip_global(args)
    two = " ".join(words[:2])
    return two if two in VERBS_WITH_SUB else words[0]


def _unknown_flag(args: Sequence[str], verb: str) -> str:
    known = SNAPSHOT["verbs"][verb]["flags"]
    allowed = set(known) | {value.split()[0] for value in known.values() if value.startswith("-")} | set(GLOBAL_FLAGS)
    if verb == "exec":  # everything after the box name belongs to the command
        return ""
    return next((word for word in args[len(verb.split()):] if word.startswith("-") and word not in allowed), "")


class FakeGit:
    """Answers git the way a clone whose remote holds `tips` does."""

    def __init__(self, sha: str, tips: Sequence[str] = (), below: Sequence[str] = (), readable: bool = True,
                 dirty: bool = False, local: bool = True) -> None:
        self.sha, self.tips, self.below, self.readable, self.is_dirty = sha, list(tips), list(below), readable, dirty
        self.local = local  # False: the host clone does not hold the commit, as for a fork's pull request head

    def __call__(self, argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
        args = list(argv)[1:]
        if args[0] == "rev-parse":
            return Done(0, self.sha + "\n") if self.sha and self.local else Done(128, "", "fatal: not a git repository")
        if args[0] == "ls-remote":
            lines = "".join(f"{tip}\trefs/heads/x\n" for tip in self.tips)
            return Done(0, lines) if self.readable else Done(128, "", "fatal: could not read")
        if args[0] == "for-each-ref":
            return Done(0, "\n".join(self.below))
        if args[0] == "status":
            return Done(0, " M a.py\n" if self.is_dirty else "")
        raise AssertionError(args)


class FakeGitHub:
    """`gh api` over a routing table: path -> JSON value, or an int for an HTTP error status."""

    MESSAGES: ClassVar[dict[int, str]] = {401: "Bad credentials", 403: "Resource not accessible by personal access token", 404: "Not Found"}

    def __init__(self, routes: Mapping[str, Any] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[list[str]] = []
        self.stdins: list[str | None] = []

    def __call__(self, argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
        args = list(argv)
        self.calls.append(args)
        self.stdins.append(stdin)
        path = args[2]
        if path not in self.routes:
            return Done(1, "", f"gh: Not Found (HTTP 404) {path}")
        value = self.routes[path]
        if isinstance(value, int):
            return Done(1, "", f"gh: {self.MESSAGES.get(value, 'error')} (HTTP {value})")
        return Done(0, json.dumps(value))


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        self.time += 1.0
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds
