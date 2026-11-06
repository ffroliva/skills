"""Plan shards from measured JUnit, and check a plan and a run against the bounds in docs/reference/sharding.md.

  plan   --junit <dir> --n N   prints the assignment as JSON. Save one file per platform: weights do not transfer.
  check  --plan <file>         the placement and load bounds of any assignment in that JSON, yours or generated
  check  --junit <dir> --expect N   a run: every test ran once and passed, and the count is the whole suite

Reads files only, and calls no sbx. Exit 0 keeps every bound, 1 breaks one, 2 unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sbxlib.adapters.junit_xml import UnreadableJunit, read_dir
from sbxlib.domain import junit, shard


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value}: must be at least 1")
    return value


def _plan_json(found: shard.ShardPlan, ceiling: float | None) -> dict[str, object]:
    return {
        "n": found.n, "weights": dict(sorted(found.weights.items())), "own_job": list(found.own_job),
        "unmeasured": list(found.unmeasured), "advice": shard.advice(found, ceiling),
        "shards": [{"index": i, "load_s": round(load, 3), "units": list(units)}
                   for i, (units, load) in enumerate(zip(found.shards, found.loads(), strict=True), 1)],
    }


def _lines(path: Path | None) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path else []


def _plan_from(path: Path) -> shard.ShardPlan:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    shards = tuple(tuple(entry["units"]) for entry in data["shards"])
    if not shards:
        raise ValueError("the plan has no shards")
    if data.get("n", len(shards)) != len(shards):
        raise ValueError(f"n is {data['n']}, and the plan holds {len(shards)} shards")
    return shard.ShardPlan(len(shards), shards, tuple(data.get("own_job", ())), tuple(data.get("unmeasured", ())),
                           data.get("weights", {}))


def _run_plan(args: argparse.Namespace) -> int:
    cases = read_dir(args.junit)
    if not cases:
        raise ValueError(f"no test cases under {args.junit}")
    weights = junit.weights(cases)
    units = [*weights, *(unit for unit in _lines(args.units) if unit not in weights)]
    found = shard.plan(units, weights, args.n, ceiling=args.ceiling, heavy=_lines(args.heavy),
                       timing=_lines(args.timing), own_job=_lines(args.own_job))
    print(json.dumps(_plan_json(found, args.ceiling), indent=2))
    return 0


def _run_check(args: argparse.Namespace) -> int:
    problems: list[str] = []
    if args.plan:
        problems += shard.check(_plan_from(args.plan), _lines(args.units) or None, ceiling=args.ceiling,
                                max_unmeasured=args.max_unmeasured, heavy=_lines(args.heavy), timing=_lines(args.timing))
    if args.junit:
        cases = read_dir(args.junit)
        print("\n".join(junit.per_box(cases)))
        problems += junit.problems(cases, args.expect)
    print("\n".join(f"sbx_shard: {line}" for line in problems) or "sbx_shard: every bound holds")
    return 1 if problems else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    plan = sub.add_parser("plan", help="print the assignment as JSON")
    plan.add_argument("--junit", type=Path, required=True, help="a green run's JUnit, for this platform")
    plan.add_argument("--n", type=int, required=True, help="shard count")
    plan.add_argument("--own-job", type=Path, help="file of units that leave the shards whatever their weight")
    check = sub.add_parser("check", help="check a plan, a run, or both")
    check.add_argument("--plan", type=Path, help="an assignment, in sbx_shard plan's JSON")
    check.add_argument("--junit", type=Path, help="a run's JUnit: the fleet's --out directory")
    check.add_argument("--expect", type=_positive, help="unique tests that must run, skipped ones not counted; a lost shard fails here")
    check.add_argument("--max-unmeasured", type=float, default=0.05, help="share of units with no weight (default 0.05)")
    for command in (plan, check):
        command.add_argument("--units", type=Path, help="file listing every unit of the suite, one per line")
        command.add_argument("--ceiling", type=float, help="the most seconds of test time one shard may carry")
        command.add_argument("--heavy", type=Path, help="file of CPU-heavy units, kept away from timing units")
        command.add_argument("--timing", type=Path, help="file of units holding timing or budget tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "plan" and args.n < 1:
        print("sbx_shard: --n must be at least 1")
        return 2
    if args.action == "check" and not (args.plan or args.junit):
        print("sbx_shard: check needs --plan, --junit or both")
        return 2
    if args.action == "check" and args.junit and args.expect is None:
        print("sbx_shard: check --junit needs --expect: without the suite's count a lost shard passes")
        return 2
    try:
        return _run_plan(args) if args.action == "plan" else _run_check(args)
    except (OSError, ValueError, KeyError, TypeError, UnreadableJunit) as exc:
        print(f"sbx_shard: cannot read the input: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
