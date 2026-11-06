"""Score a manual agent-command transcript against evals/scenarios.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast


def score(scenario: dict[str, Any], transcript: list[str]) -> list[str]:
    problems: list[str] = []
    cursor = 0
    for expected in scenario["expected"]:
        found = next((index for index in range(cursor, len(transcript)) if expected in transcript[index]), None)
        if found is None:
            problems.append(f"missing or out of order: {expected}")
        else:
            cursor = found + 1
    joined = "\n".join(transcript).lower()
    problems.extend(f"forbidden: {item}" for item in scenario["forbid"] if item.lower() in joined)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario")
    parser.add_argument("transcript", type=Path, help="UTF-8 JSON array of command strings")
    args = parser.parse_args(argv)
    scenarios = json.loads(Path(__file__).resolve().parents[3].joinpath("evals", "scenarios.json").read_text(encoding="utf-8"))
    scenario = next((item for item in scenarios if item["id"] == args.scenario), None)
    if scenario is None:
        parser.error(f"unknown scenario: {args.scenario}")
    raw_transcript: Any = json.loads(args.transcript.read_text(encoding="utf-8"))
    if not isinstance(raw_transcript, list) or not all(isinstance(line, str) for line in cast(list[Any], raw_transcript)):
        parser.error("transcript must be a JSON array of command strings")
    transcript = cast(list[str], raw_transcript)
    problems = score(scenario, transcript)
    print("PASS" if not problems else "FAIL: " + "; ".join(problems))
    return bool(problems)


if __name__ == "__main__":
    sys.exit(main())
