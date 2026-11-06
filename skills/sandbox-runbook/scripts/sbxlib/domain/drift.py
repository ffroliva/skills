"""Compare the cloud CLI surface this skill relies on with a snapshot of it."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

# every cloud command the adapter calls, and the ones the notes name
VERBS = ("create", "exec", "cp", "rm", "ls", "secret set", "secret rm", "secret ls", "secret set-custom", "policy ls")
_STABLE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_FLAG = re.compile(r"^\s+(?:(-\w), )?(--[\w-]+)(?: (\w+))?(?=\s{2,}|\s*$)")
_COMMAND = re.compile(r"^  (\w[\w-]*)\s{2,}\S")


def parse_help(text: str) -> dict[str, Any]:
    """Flags (name -> `short type`) and sub-commands from one `--help` text."""
    flags: dict[str, str] = {}
    commands: list[str] = []
    in_commands = False
    for line in text.splitlines():
        if line.rstrip().endswith("Commands:"):
            in_commands = True
            continue
        if in_commands and not line.startswith("  "):
            in_commands = False
        if in_commands and (match := _COMMAND.match(line)):
            commands.append(match[1])
        elif match := _FLAG.match(line):
            flags[match[2]] = " ".join(part for part in (match[1], match[3]) if part)
    return {"flags": flags, "commands": sorted(set(commands))}


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(number) for number in re.findall(r"\d+", version))


def newest_stable(tags: list[str]) -> str | None:
    stable = [tag for tag in tags if _STABLE.fullmatch(tag)]
    return max(stable, key=version_tuple, default=None)


def is_valid_snapshot(snapshot: object) -> bool:
    """Non-empty, or a check would compare nothing and read as aligned."""
    if not isinstance(snapshot, dict):
        return False
    typed = cast(dict[str, Any], snapshot)
    verbs = typed.get("verbs")
    if not typed.get("version") or not isinstance(verbs, dict) or not verbs:
        return False
    rows = cast(dict[str, Any], verbs).values()
    return all(isinstance(row, dict) and "flags" in row for row in rows)


def compare(snapshot: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, list[str]]:
    """What the skill relies on and sbx no longer offers. A new flag is not drift: nothing here uses it."""
    removed: list[str] = []
    changed: list[str] = []
    gone = {str(name) for name in snapshot.get("cloud_commands", ())} - {str(name) for name in live["cloud_commands"]}
    missing: list[str] = sorted(gone)
    for verb, before in snapshot["verbs"].items():
        now = live["verbs"].get(verb)
        if verb.split()[0] in gone:
            continue
        if now is None:
            missing.append(verb)
            continue
        old, new = before["flags"], now["flags"]
        removed += [f"{verb} {flag}" for flag in sorted(set(old) - set(new))]
        changed += [f"{verb} {flag}" for flag in sorted(set(old) & set(new)) if old[flag] != new[flag]]
    return {"removed": removed, "changed": changed, "missing_verbs": missing}
