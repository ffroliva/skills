"""Shared test plumbing: import paths and the archive a box returns."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "sandbox-runbook"
SCRIPTS = SKILL / "scripts"
for path in (str(SCRIPTS), str(ROOT / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sbxlib.ports import Done  # noqa: E402

SHA = "a" * 40
REPO = "https://github.com/acme/app.git"
JUNIT = '<testsuite><testcase classname="t" name="a"/><testcase classname="t" name="b"/></testsuite>'


def done(rc: int = 0, out: str = "", err: str = "") -> Done:
    return Done(rc, out, err)


def result_tar(rc: str | None = "0", junit: str | None = JUNIT, fatal: str | None = None,
               extra: dict[str, str] | None = None) -> bytes:
    """The bytes of the out.tgz a box would return."""
    files = dict(extra or {})
    if rc is not None:
        files["out/rc"] = rc + "\n"
    if junit is not None:
        files["out/junit.xml"] = junit
    if fatal is not None:
        files["out/fatal"] = fatal + "\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()
