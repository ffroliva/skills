"""A run's folder on the host: scripts going up, archives coming back. An archive is untrusted input."""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import tarfile
import zlib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import IO, cast

from ..domain.adoption import ADOPTION_FILE
from ..domain.fleet import BoxResult
from ..domain.junit import Outcome, TestCase
from ..domain.profile import OutputPolicy
from .junit_xml import MAX_CASES, UnreadableJunit, read_file

MAX_ARCHIVE_BYTES = 500_000_000  # on disk: `sbx cp` itself has no limit, so this is the first look at what came back
MAX_UNPACKED_BYTES = 500_000_000  # what a box may unpack on the host, counting what is thrown away
MAX_MEMBERS = 50_000


def _repo_paths(path: Path) -> tuple[str, ...]:
    """`path` as its repository names it, as written and with links followed: GitHub lists `docs/sbx.md` on every host."""
    found: list[str] = []
    for candidate in (Path(os.path.abspath(path)), path.resolve()):
        root = next((parent for parent in candidate.parents if (parent / ".git").exists()), None)
        if root:
            found.append(candidate.relative_to(root).as_posix())
    return tuple(dict.fromkeys(found))


def protected_paths(config: Path, template: str = "") -> tuple[str, ...]:
    """Every repository path a trust decision reads: the adoption file and a local kit. () when the file is in no repository."""
    paths = _repo_paths(config)
    kit = _repo_paths(Path(template)) if template.startswith((".", "/")) else ()
    return (ADOPTION_FILE, *paths, *kit) if paths else ()


def _allowed(member: tarfile.TarInfo) -> bool:
    """Results only: the exit code, the fatal note and JUnit. Logs stay in the box."""
    return member.name in ("out/rc", "out/fatal") or (member.name.startswith("out/") and member.name.endswith(".xml"))


# A part that is empty, `.` or `..`, holds a Windows separator, drive or NUL, or is a Windows device name.
_BAD_PART = re.compile(r"[\\:\x00]|^\.{0,2}$|^(?:con|prn|aux|nul|com\d|lpt\d)(?:\..*)?$", re.IGNORECASE)


def _check(member: tarfile.TarInfo) -> None:
    """Every member, kept or not: a regular file or a folder at a plain relative path, or a ValueError. Checked here rather
    than by `tarfile`'s `data` filter, whose link checks a published bypass beat before the 2025 fixes: on Python 3.13.1 a
    hard link overwrote a host file (review 4, H1). So a link, device or fifo is never made, whatever the Python."""
    if not (member.isreg() or member.isdir()) or any(_BAD_PART.search(part) for part in member.name.split("/")):
        raise ValueError(f"member {member.name!r}: only regular files at plain relative paths come back")


def _write(tar: tarfile.TarFile, member: tarfile.TarInfo, root: Path) -> None:
    """One checked member, as a new regular file under `root`. Folders come from the files below them."""
    if member.isdir():
        return
    path = root.joinpath(*member.name.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.resolve().is_relative_to(root):
        raise ValueError(f"member {member.name!r}: outside the run folder")
    source = tar.extractfile(member)
    if source is None:
        raise ValueError(f"member {member.name!r}: no data")
    with source, path.open("xb") as sink:  # x: never written through a name that already exists
        shutil.copyfileobj(source, sink)


class _Capped:
    """A decompressed stream that stops at a limit. tarfile reads a pax header whole, before any member can be looked at."""

    def __init__(self, raw: gzip.GzipFile, limit: int) -> None:
        self._raw, self._limit, self._read = raw, limit, 0

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self._read += len(data)
        if self._read > self._limit:
            raise ValueError(f"over {self._limit} bytes")
        return data


class RunDirectory:
    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def has_results(self) -> bool:
        """A reused folder would count an earlier run's JUnit as this run's."""
        return any(self._root.iterdir())

    def write_script(self, box: str, text: str) -> str:
        path = self._root / f"{box}.sh"
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)

    def archive(self, box: str) -> str:
        return str(self._root / f"{box}.tgz")

    def _extract(self, box: str, policy: OutputPolicy) -> Path:
        target = self._root / box
        path = Path(self.archive(box))
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError(f"over {MAX_ARCHIVE_BYTES} bytes on disk")
        target.mkdir(parents=True, exist_ok=True)
        root = target.resolve()
        with gzip.GzipFile(path) as raw, tarfile.open(fileobj=cast(IO[bytes], _Capped(raw, MAX_UNPACKED_BYTES)), mode="r|") as tar:
            for count, member in enumerate(tar, 1):
                if count > MAX_MEMBERS:
                    raise ValueError(f"over {MAX_MEMBERS} files")
                _check(member)
                if policy is OutputPolicy.EVERYTHING or _allowed(member):
                    _write(tar, member, root)
        return target / "out"

    def read_result(self, index: int, box: str, seconds: float, policy: OutputPolicy) -> BoxResult:
        try:
            files = self._extract(box, policy)
            rc_file, fatal_file = files / "rc", files / "fatal"
            rc = int(rc_file.read_text(encoding="utf-8").strip() or "-1") if rc_file.exists() else None
            cases: list[TestCase] = []
            for xml in files.rglob("*.xml"):
                cases += read_file(xml, box, MAX_CASES, len(cases))
            outcomes = Counter(case.outcome for case in cases)
            fatal = fatal_file.read_text(encoding="utf-8", errors="replace").strip() if fatal_file.exists() else ""
            return BoxResult(index, rc, outcomes.total(), fatal, seconds, outcomes[Outcome.FAILED] + outcomes[Outcome.ERROR],
                             outcomes[Outcome.SKIPPED],
                             frozenset(f"{case.classname}::{case.name}" for case in cases if case.outcome is not Outcome.SKIPPED))
        except (OSError, tarfile.TarError, EOFError, ValueError, UnreadableJunit, MemoryError, zlib.error) as exc:
            return BoxResult(index, fatal=f"invalid result archive: {exc}", seconds=seconds)

    def write_verdict(self, body: Mapping[str, object]) -> None:
        (self._root / "verdict.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
