"""What a set of JUnit test cases says, whichever language produced them."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum


class Outcome(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a test class, for any runner that collects by name
    box: str
    classname: str
    name: str
    unit: str
    seconds: float = 0.0
    outcome: Outcome = Outcome.PASSED


def weights(cases: list[TestCase]) -> dict[str, float]:
    """Measured seconds per unit. One platform's JUnit gives one platform's weights: they do not transfer."""
    table: dict[str, float] = defaultdict(float)
    for case in cases:
        table[case.unit] += case.seconds
    return dict(table)


def _line(label: str, cases: list[TestCase]) -> str:
    count = Counter(case.outcome for case in cases)
    return (f"{label}: {len(cases)} tests, {count[Outcome.FAILED]} failures, {count[Outcome.ERROR]} errors, "
            f"{count[Outcome.SKIPPED]} skipped")


def per_box(cases: list[TestCase]) -> list[str]:
    boxes: dict[str, list[TestCase]] = defaultdict(list)
    for case in cases:
        boxes[case.box].append(case)
    return [*(_line(box, boxes[box]) for box in sorted(boxes)), _line("total", cases)]


def problems(cases: list[TestCase], expect: int | None = None) -> list[str]:
    """Green means each test ran once, in one box, and passed. A lost shard fails on the unique count."""
    if not cases:
        return ["no test cases found"]
    boxes_of: dict[tuple[str, str], set[str]] = defaultdict(set)
    for case in cases:
        boxes_of[(case.classname, case.name)].add(case.box)
    found: list[str] = []
    overlap = sum(1 for boxes in boxes_of.values() if len(boxes) > 1)
    if overlap:
        found.append(f"{overlap} test ran in more than one box: the shards overlap")
    count = Counter(case.outcome for case in cases)
    if count[Outcome.FAILED] or count[Outcome.ERROR]:
        found.append(f"{count[Outcome.FAILED]} failed, {count[Outcome.ERROR]} errors")
    ran = len({(case.classname, case.name) for case in cases if case.outcome is not Outcome.SKIPPED})
    skipped = f", {count[Outcome.SKIPPED]} skipped" if count[Outcome.SKIPPED] else ""
    if expect is not None and ran != expect:
        found.append(f"expected {expect} unique tests, found {ran}{skipped}: a shard was lost"
                     if ran < expect else f"expected {expect} unique tests, found {ran}{skipped}")
    return found
