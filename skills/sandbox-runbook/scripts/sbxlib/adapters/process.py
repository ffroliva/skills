"""The one place a process starts."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from ..ports import CommandRunner, CommandTimeout, Done

NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 0 off Windows; a background console tool must open none


def _tool(name: str) -> str | None:
    """The full path, from absolute PATH entries only. A bare name lets Windows try the working directory first, and the
    skill runs in a target project: a `git.exe` planted there would inherit this process's credentials."""
    folders = [""] if os.path.dirname(name) else [item for item in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(item)]
    return next(filter(None, (shutil.which(os.path.join(folder, name)) for folder in folders)), None)


def run_command(argv: Sequence[str], stdin: str | None = None, timeout: int = 60, cwd: Path | None = None,
                env: Mapping[str, str] | None = None) -> Done:
    """A missing executable is rc 127 and any other start failure rc 126: neither raises past here."""
    tool = _tool(argv[0])
    if tool is None:
        return Done(127, "", f"{argv[0]}: not found")
    try:
        # S603: an argv list, no shell, and every process in this skill starts on this one line
        done = subprocess.run([tool, *argv[1:]], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",  # noqa: S603
                              timeout=timeout, cwd=cwd, creationflags=NO_WINDOW, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(f"{argv[0]} did not answer in {timeout} s") from exc
    except OSError as exc:
        return Done(126, "", f"{argv[0]}: {exc}")
    return Done(done.returncode, done.stdout or "", done.stderr or "")


def without_env(names: Collection[str]) -> CommandRunner:
    """A runner whose children never inherit `names`: a child has no business with a credential it was not handed."""
    hidden = {name.upper() for name in names}  # Windows folds variable names to upper case

    def run(argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
        return run_command(argv, stdin, timeout, env={key: value for key, value in os.environ.items() if key.upper() not in hidden})

    return run


def in_dir(root: Path) -> CommandRunner:
    def run(argv: Sequence[str], stdin: str | None = None, timeout: int = 60) -> Done:
        return run_command(argv, stdin, timeout, cwd=root)

    return run
