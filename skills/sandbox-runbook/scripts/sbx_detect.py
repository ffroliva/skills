"""Inspect a project and print what a sandbox plan needs to know, as JSON. Reads no secret file and calls no sbx."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sbxlib.adapters.project_scan import detect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path, help="the project to inspect (default: here)")
    args = parser.parse_args(argv)
    print(json.dumps(detect(args.root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
