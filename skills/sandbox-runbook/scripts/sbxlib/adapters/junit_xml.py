"""Read JUnit XML into domain test cases. The XML may come from an untrusted box, so a document type is refused."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from ..domain.junit import Outcome, TestCase

MAX_XML_BYTES = 100_000_000
MAX_CASES = 500_000  # a run's cases; the largest gate measured had 21,859
_CHUNK = 1 << 20


class UnreadableJunit(Exception):
    pass


def _outcome(case: ET.Element) -> Outcome:
    for tag, outcome in (("failure", Outcome.FAILED), ("error", Outcome.ERROR), ("skipped", Outcome.SKIPPED)):
        if case.find(tag) is not None:
            return outcome
    return Outcome.PASSED


def _seconds(case: ET.Element) -> float:
    try:
        seconds = float(case.get("time") or 0.0)
    except ValueError:
        return 0.0
    return seconds if math.isfinite(seconds) else 0.0  # nan or inf would print as NaN, which is not JSON


def read_file(path: Path, box: str, limit: int = MAX_CASES, counted: int = 0) -> list[TestCase]:
    """The cases in one file. `limit` caps a run's cases, `counted` of them read already, and is checked while parsing:
    `<testcase/>` is 11 bytes, so a few MB of archive once held over a GB of host memory (review 4, M4)."""
    if path.stat().st_size > MAX_XML_BYTES:
        raise UnreadableJunit(f"{path.name}: over {MAX_XML_BYTES} bytes")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "\x00" in text or "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise UnreadableJunit(f"{path.name}: holds a document type")
    data, parser = text.encode("utf-8"), ET.XMLPullParser(events=("end",))  # safe after the check above: see the module note
    cases: list[TestCase] = []

    def collect(events: Iterator[tuple[str, ET.Element]]) -> None:
        for _event, case in events:  # events=("end",) only
            if case.tag != "testcase":
                continue
            if counted + len(cases) >= limit:
                raise UnreadableJunit(f"{path.name}: over {limit} test cases in one run")
            classname, name = case.get("classname") or "", case.get("name") or ""
            cases.append(TestCase(box, classname, name, case.get("file") or classname, _seconds(case), _outcome(case)))
            case.clear()

    try:
        for start in range(0, len(data) or 1, _CHUNK):
            parser.feed(data[start:start + _CHUNK])
            collect(cast(Iterator[tuple[str, ET.Element]], parser.read_events()))
        parser.close()
        collect(cast(Iterator[tuple[str, ET.Element]], parser.read_events()))
    except (ET.ParseError, LookupError) as exc:  # LookupError: an encoding the XML names and Python lacks
        raise UnreadableJunit(f"{path.name}: {exc}") from exc
    return cases


def read_dir(folder: Path) -> list[TestCase]:
    """Every XML under `folder`; the first folder below it names the box, as sbx_fleet.py lays results out."""
    cases: list[TestCase] = []
    for path in sorted(folder.rglob("*.xml")):
        parts = path.relative_to(folder).parts
        cases += read_file(path, parts[0] if len(parts) > 1 else folder.name)
    return cases
