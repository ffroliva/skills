"""Has the installed sbx moved away from the snapshot? Exit 0 aligned, 4 drift, 3 could not check: never read as aligned."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..domain.drift import compare, is_valid_snapshot, parse_help, version_tuple
from ..ports import CliSurface, CommandTimeout


def collect(surface: CliSurface, verbs: tuple[str, ...]) -> dict[str, Any]:
    top = surface.help(())
    helps = {verb: surface.help(tuple(verb.split())) for verb in verbs}
    return {"cloud_commands": parse_help(top or "")["commands"],
            "verbs": {verb: parse_help(text) if text is not None else None for verb, text in helps.items()}}


def take_snapshot(surface: CliSurface, verbs: tuple[str, ...]) -> dict[str, Any]:
    version = surface.version()
    if not version:
        raise RuntimeError("sbx is not installed, or `sbx version` printed no version")
    live = collect(surface, verbs)
    broken = [verb for verb, parsed in live["verbs"].items() if parsed is None]
    if broken:
        raise RuntimeError(f"`sbx --cloud <command> --help` failed for: {', '.join(broken)}")
    return {"version": version, **live}


def _read(snapshot_text: str | None) -> dict[str, Any] | None:
    try:
        data = json.loads(snapshot_text or "")
    except ValueError:
        return None
    return data if is_valid_snapshot(data) else None


def _compare(surface: CliSurface, latest: Callable[[], str | None], snapshot: dict[str, Any], version: str,
             report: dict[str, Any]) -> int:
    lines: list[str] = report["lines"]
    newest = latest()
    diff = compare(snapshot, collect(surface, tuple(snapshot["verbs"])))
    report.update(diff, installed_version=version, latest_release=newest)
    report["version_behind"] = version_tuple(snapshot["version"]) < max(version_tuple(version), version_tuple(newest or ""))
    lines.append(f"snapshot sbx {snapshot['version']}, installed {version}, newest release {newest or 'unknown'}")
    if report["version_behind"] or version != snapshot["version"]:
        lines.append("version: the snapshot and sbx differ; read the release notes between the versions")
    lines += [f"{label.replace('_verbs', '')}: {item}" for label, items in diff.items() for item in items]
    if any(diff.values()) or report["version_behind"] or version != snapshot["version"]:
        report["status"] = "drift"
        return 4
    if newest is None:
        lines.append("could not read the newest release (no network or no gh): not reported as aligned")
        return 3
    report["status"] = "aligned"
    lines.append("aligned")
    return 0


def check(surface: CliSurface, latest: Callable[[], str | None], snapshot_text: str | None) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {"status": "unknown", "lines": [], "missing_verbs": [], "removed": [], "changed": [],
                              "version_behind": False}
    snapshot = _read(snapshot_text)
    if snapshot is None:
        report["lines"].append("cannot read the snapshot, or it is empty. Run `sbx_drift.py snapshot`")
        return 3, report
    report["snapshot_version"] = snapshot["version"]
    try:
        version = surface.version()
        if not version:
            report["lines"].append("sbx is not installed, or `sbx version` printed no version: cannot compare")
            return 3, report
        return _compare(surface, latest, snapshot, version, report), report
    except CommandTimeout as exc:
        report["lines"].append(f"{exc}: cannot compare")
        return 3, report
