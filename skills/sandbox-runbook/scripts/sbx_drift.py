"""Detect that the installed sbx has moved away from the one this skill was written against. Reads only.

  snapshot   walk `--cloud --help` for every command the skill uses and write references/cli-snapshot.json
  check      compare the installed version and live help with that snapshot and with the newest docker/sbx-releases tag
  latest     compare only the snapshot's version with the newest release: needs no sbx, for a scheduled job

Prints a plain list, and for check one JSON document. Exit 0 aligned, 4 drift, 3 could not check. Missing network,
missing `gh`, a missing sbx or an unreadable snapshot are exit 3: never read as aligned.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sbxlib.adapters.gh_cli import release_tags
from sbxlib.adapters.process import run_command
from sbxlib.adapters.sbx_cli import SbxCli
from sbxlib.app.drift import check, take_snapshot
from sbxlib.domain.drift import VERBS, is_valid_snapshot, newest_stable, version_tuple
from sbxlib.ports import CommandRunner

SNAPSHOT = Path(__file__).resolve().parent.parent / "references" / "cli-snapshot.json"


def _text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def newest_release(gh: CommandRunner) -> str | None:
    tags = release_tags(gh)
    return newest_stable(tags) if tags is not None else None


def _snapshot_version(snapshot: str | None) -> str | None:
    try:
        data = json.loads(snapshot or "")
        version = data["version"]
    except (ValueError, KeyError, TypeError):
        return None
    return version if isinstance(version, str) and version and is_valid_snapshot(data) else None


def _latest_only(snapshot: str | None, gh: CommandRunner) -> int:
    newest, version = newest_release(gh), _snapshot_version(snapshot)
    if newest is None or version is None:
        print("could not read the newest release or the snapshot: not reported as aligned")
        return 3
    apart = version_tuple(version) != version_tuple(newest)  # a snapshot ahead of every release is a typo, and silences the weekly job
    print(f"snapshot sbx {version}, newest release {newest}: {'apart' if apart else 'aligned'}")
    return 4 if apart else 0


def main(argv: list[str] | None = None, sbx: CommandRunner = run_command, gh: CommandRunner = run_command) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("snapshot", "check", "latest"))
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT, help="the snapshot file (default: references/)")
    args = parser.parse_args(argv)
    cli = SbxCli(sbx)
    if args.action == "latest":
        return _latest_only(_text(args.snapshot), gh)
    if args.action == "snapshot":
        try:
            data = take_snapshot(cli, VERBS)
        except RuntimeError as exc:
            print(f"sbx_drift: {exc}")
            return 3
        args.snapshot.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"sbx_drift: wrote {args.snapshot} for sbx {data['version']} ({len(data['verbs'])} commands)")
        return 0
    code, report = check(cli, lambda: newest_release(gh), _text(args.snapshot))
    print("\n".join(report["lines"]))
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
