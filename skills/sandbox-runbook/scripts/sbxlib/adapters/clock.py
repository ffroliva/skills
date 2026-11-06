"""Time and run ids."""

from __future__ import annotations

import secrets
import string
import time


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def new_run_id() -> str:
    """Four characters, shared by every box of a run. See domain.fleet.box_name for why a name must not repeat."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(4))
