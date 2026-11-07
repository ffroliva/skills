"""The `sbx` CLI behind the SandboxRuntime and SecretStore ports. Row shapes are those seen on sbx 0.51.0."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, cast

from ..domain.fleet import DEFAULT_ALLOW, RunRequest, custom_name, parse_custom
from ..ports import AccountPolicy, BoxRow, CommandRunner, Done, SecretRow, Unreadable

VERSION = re.compile(r"v(\d+\.\d+\.\d+)")
CREATE_TIMEOUT_S = 900  # a kit's first build took 227-325 s on sbx 0.50.0


def create_flags(request: RunRequest) -> list[str]:
    flags = ["--cpus", str(request.cpus), "--memory", request.memory, "--ttl", f"{request.ttl_minutes}m",
             "--on-timeout", "delete", "--no-progress"]
    flags += [word for host in (*DEFAULT_ALLOW, *request.allow) for word in ("--allow-network", host)]
    return flags + [word for env in request.env_names for word in ("-e", env)]  # bare KEY: the value stays out of argv


class SbxCli:
    def __init__(self, run: CommandRunner) -> None:
        self._run = run

    def _call(self, *args: str, timeout: int = 300, stdin: str | None = None) -> Done:
        return self._run(["sbx", "--no-input", "--cloud", *args], stdin, timeout)

    def create(self, name: str, request: RunRequest) -> Done:
        return self._call("create", request.template, "--name", name, *create_flags(request), timeout=CREATE_TIMEOUT_S)

    def run(self, box: str, *argv: str, timeout: int = 300) -> Done:
        return self._call("exec", box, *argv, timeout=timeout)

    def upload(self, path: str, box: str, target: str) -> Done:
        return self._call("cp", path, f"{box}:{target}")

    def download(self, box: str, source: str, path: str) -> Done:
        return self._call("cp", f"{box}:{source}", path)

    def remove(self, box: str) -> Done:
        return self._call("rm", "-f", box)

    def _json(self, *args: str) -> Any:
        done = self._call(*args, timeout=60)
        if done.rc != 0:
            raise Unreadable(done.err.strip()[-300:] or f"sbx {' '.join(args)} exited {done.rc}")
        try:
            return json.loads(done.out)
        except ValueError as exc:
            raise Unreadable(f"sbx {' '.join(args)} printed something other than JSON") from exc

    def boxes(self) -> list[BoxRow]:
        rows: Any = self._json("ls", "--json")
        if isinstance(rows, dict):
            wrapped = cast(dict[str, Any], rows).get("sandboxes")
            if isinstance(wrapped, list):
                rows = cast(list[Any], wrapped)
        if not isinstance(rows, list):
            raise Unreadable("sbx ls --json has an unknown shape")
        return [_box(row) for row in cast(Sequence[Any], rows)]

    def account_policy(self) -> AccountPolicy:
        """The account's default egress, as `policy ls --json` prints it (seen on 0.51.0, only ever with an empty list)."""
        data = self._json("policy", "ls", "--json")
        typed = cast(dict[str, Any], data) if isinstance(data, dict) else {}
        mode, allow = typed.get("mode"), typed.get("allow_networks")
        if not isinstance(mode, str) or not mode:
            raise Unreadable("sbx policy ls --json has no mode")
        if not isinstance(allow, list) or not all(isinstance(host, str) for host in cast(Sequence[Any], allow)):
            raise Unreadable("sbx policy ls --json has no allow_networks list of hosts")
        return AccountPolicy(mode, tuple(cast(Sequence[str], allow)))

    def set_scoped(self, box: str, service: str, value: str) -> Done:
        """A service name such as `github`, or `custom:<host>:<ENV>`: the box sees ENV as a placeholder, and the proxy
        sets the Authorization header on requests to that exact host (seen on 0.51.0)."""
        custom = parse_custom(service)
        if custom:
            host, env = custom
            return self._call("secret", "set-custom", "--sandbox", box, "--host", host, "--env", env, "--name",
                              custom_name(host), "--value-stdin", stdin=value)
        return self._call("secret", "set", "--sandbox", box, service, stdin=value)

    def remove_scoped(self, box: str, name: str) -> Done:
        custom = parse_custom(name)
        return self._call("secret", "rm", custom_name(custom[0]) if custom else name, "--sandbox", box, "--force")

    def secrets(self) -> list[SecretRow]:
        data = self._json("secret", "ls", "--json")
        typed = cast(dict[str, Any], data) if isinstance(data, dict) else {}
        rows = typed.get("secrets")
        if not isinstance(rows, list):
            raise Unreadable("sbx secret ls --json has no secrets list")
        custom = typed.get("custom_secrets")
        listed = [*cast(Sequence[Any], rows), *(cast(Sequence[Any], custom) if isinstance(custom, list) else ())]
        # sbx 0.51.0 counts these and lists none; what such a value can reach is unknown, so it is shown as a global secret
        unnamed = [SecretRow("env-only", "global")] if typed.get("env_only_count") else []
        return [*(_secret(row) for row in listed), *unnamed]

    def help(self, words: tuple[str, ...]) -> str | None:
        """The cloud surface: local help lists flags `--cloud` refuses."""
        done = self._call(*words, "--help", timeout=60)
        return done.out if done.rc == 0 else None

    def version(self) -> str | None:
        done = self._run(["sbx", "version"], None, 60)
        match = VERSION.search(done.out) if done.rc == 0 else None
        return match[1] if match else None


def _box(row: Any) -> BoxRow:
    if not isinstance(row, dict) or not isinstance(row.get("name"), str):  # pyright: ignore[reportUnknownMemberType]
        raise Unreadable("a row of sbx ls --json has no name")
    typed = cast(dict[str, Any], row)
    cpus = typed.get("cpus")
    if not isinstance(cpus, int):
        raise Unreadable(f"{typed['name']}: sbx ls --json reports no vCPU figure")
    return BoxRow(str(typed["name"]).rpartition("/")[2], cpus)


def _secret(row: Any) -> SecretRow:
    if not isinstance(row, dict):
        raise Unreadable("a row of sbx secret ls --json is not an object")
    typed = cast(dict[str, Any], row)
    hosts = typed.get("hosts")
    return SecretRow(str(typed.get("name") or ""), str(typed.get("scope") or ""),
                     tuple(str(host) for host in cast(Sequence[Any], hosts)) if isinstance(hosts, list) else ())
