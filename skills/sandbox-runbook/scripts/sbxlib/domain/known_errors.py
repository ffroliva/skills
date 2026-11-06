"""Error text sbx or GitHub really prints, mapped to its entry in docs/troubleshooting.md."""

from __future__ import annotations

GUIDE = "docs/troubleshooting.md"
KNOWN: tuple[tuple[str, str], ...] = (
    ('unknown agent "shell-docker"', "shell-docker-unknown-agent"),
    ("unknown template: shell-docker", "shell-docker-unknown-template"),
    ("byte pull limit", "kit-pull-limit"),
    ("CONNECT tunnel failed, response 403", "deny-all-403"),
    ("not signed in to Docker", "not-signed-in"),
    ("status code: 429", "concurrent-create-429"),
    ("HTTP 429", "concurrent-create-429"),
    ("Maximum running vCPU quota", "vcpu-quota"),
    ("settings platform construction failed", "settings-platform"),
    ("Bad credentials", "token-expired"),
    ("Resource not accessible by personal access token", "token-missing-permission"),
)


def anchor_for(text: str) -> str:
    """`docs/troubleshooting.md#anchor` for the first known error in `text`, or ''."""
    return next((f"{GUIDE}#{anchor}" for needle, anchor in KNOWN if needle in text), "")
