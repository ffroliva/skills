"""What a target project's adoption file says: which use cases apply, why, and the settings each run reads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from .adoption import PLACEHOLDER, add_missing_keys, config_block, fill, parse_config
from .trust import repo_id

MAVEN_COMMAND = "./mvnw -B verify; rc=$?; cp target/surefire-reports/*.xml $OUT/ 2>/dev/null; exit $rc"
EGRESS = {"uv": ("pypi.org", "files.pythonhosted.org", "astral.sh", "**.astral.sh"),
          "pip": ("pypi.org", "files.pythonhosted.org"),
          "maven": ("repo.maven.apache.org", "repo1.maven.org")}
DOCKER_EGRESS = ("**.docker.com", "**.docker.io")
TRUST_STEP = """## Pull requests from outside

This repository is public, so contributors can open pull requests, and each is untrusted until a rule says otherwise.

1. Create the read-only token: [the guide](https://github.com/ffroliva/skills/blob/master/skills/sandbox-runbook/docs/reference/github-token.md).
2. Set `trust_roles`, `trust_team` or `trust_logins` in the block above. No rule means every pull request is untrusted.
3. Run `sbx_trust.py doctor --repo <owner/name>`. It names any permission the token lacks.
4. For CI, copy the two workflows in the skill's `templates/`: [the recipe](https://github.com/ffroliva/skills/blob/master/skills/sandbox-runbook/docs/use-cases/contributor-prs.md#in-ci).
"""


def _open(det: Mapping[str, Any]) -> bool:
    """A visibility nobody could read is treated as public: a private repo then fails its clone, and no token is ever written."""
    return det["repo_visibility"] != "private"


def _wants_docker(det: Mapping[str, Any], want: tuple[str, ...]) -> bool:
    return bool(det["testcontainers"]) or "testcontainers" in want


def _rules(det: Mapping[str, Any], want: tuple[str, ...]) -> dict[str, tuple[bool, str]]:
    tests = bool(det["test_runner"])
    runner = ", ".join(det["test_runner"]) or "no test runner"
    outside = {"public": "public repo takes outside pull requests", "private": "not a public repo"}.get(
        det["repo_visibility"], "visibility unknown: gh could not read the remote. Applies if the repo is public")
    cache = bool(set(det["build_tool"]) & {"maven", "gradle", "npm", "pip"})
    sharding = (f"the project already shards ({', '.join(det['sharding'])}): reuse it, add no second filter"
                if det.get("sharding") else f"{runner}: plan shards with sbx_shard.py")
    return {
        "targeted-tests": (tests, f"{runner} found" if tests else "no test runner found"),
        "full-suite-offload": (tests, f"{runner} found" if tests else "no test runner found"),
        "parallel-shards": (tests, sharding),
        "testcontainers": (_wants_docker(det, want), "Testcontainers found" if det["testcontainers"]
                           else "requested by the team" if "testcontainers" in want else "no Testcontainers dependency found"),
        "browser-e2e": (bool(det["browser"]), f"browser tests: {', '.join(det['browser']) or 'none found'}"),
        "parallel-agents": (bool(det["language"]), "any repo with git history can fan work out to boxes"),
        "shared-cache": (cache, "fill once, never share a writable one" if cache else "no slow dependency cache found"),
        "isolated-benchmarks": (bool(det["benchmarks"]), "benchmarks found" if det["benchmarks"] else "no benchmark code found"),
        "test-optimisation": (tests, "per-shard load shows what a shard costs" if tests else "no test runner found"),
        "contributor-prs": (_open(det), outside),
        "pr-review": (_open(det), outside),
        "untrusted-code": (True, "on demand, whenever a tool or clone is not trusted"),
        "heavy-gates": (bool(det["heavy_gates"]), f"found: {', '.join(det['heavy_gates']) or 'none'}"),
        "clean-linux": (det["host_os"] != "linux", f"host is {det['host_os']}, a box is Linux"),
    }


def recommend(det: Mapping[str, Any], states: Mapping[str, str], want: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """One row per use case. `states` comes from each note's frontmatter: the notes are the one source."""
    rules = _rules(det, want)
    return [{"slug": slug, "state": states.get(slug, "unknown"), "applies": applies or slug in want, "why": why}
            for slug, (applies, why) in rules.items()]


def _python_command(det: Mapping[str, Any]) -> str:
    uv = "uv" in det["build_tool"]
    sync = " ".join(["uv sync --locked", *det.get("sync_flags", [])]) if uv else f"{PLACEHOLDER} your install step>"
    # xunit1 adds the `file` attribute, which is the unit sbx_shard.py weighs
    pytest = f"{'uv run ' if uv else ''}pytest -q{' -n auto' if det['parallel_runner'] else ''}"
    run = f"{pytest} -o junit_family=xunit1 --junitxml=$OUT/junit.xml"
    sharding = det.get("sharding", [])
    if not sharding:
        return f"{sync} && {run}"
    names = [item[4:] for item in sharding if item.startswith("env:") and item[4:] not in ("SHARD", "SHARDS")]
    # the format of the project's shard value is the project's: never guessed here
    value = f"{names[0]}={PLACEHOLDER} its value from $SHARD and $SHARDS> " if names else \
        f"{PLACEHOLDER} the project's shard option from $SHARD and $SHARDS> "
    return f"{sync} && {value}{run}"


def _command(det: Mapping[str, Any]) -> str:
    if "pytest" in det["test_runner"]:
        return _python_command(det)
    if "maven-surefire" in det["test_runner"]:
        return MAVEN_COMMAND
    return f"{PLACEHOLDER} the command that runs your tests and writes JUnit XML to $OUT>"


def _allow(det: Mapping[str, Any], want: tuple[str, ...]) -> str:
    hosts = [host for tool in det["build_tool"] for host in EGRESS.get(tool, ())]
    return ",".join(dict.fromkeys([*hosts, *(DOCKER_EGRESS if _wants_docker(det, want) else ())]))


def default_config(det: Mapping[str, Any], want: tuple[str, ...] = ()) -> dict[str, str]:
    """Values with a measured reason behind them: docs/reference/sizing.md and docs/pitfalls/. Trust starts closed.

    A project that can take a stranger's pull request gets a file its untrusted run can use as it is: one box, no secret, and
    deny-all, which the fleet checks against the account. More boxes are a flag on a trusted run: `--boxes N`."""
    takes_strangers = _open(det)
    command = _command(det)
    return {
        "target_project": det["target_project"], "repo": repo_id(str(det.get("remote", ""))), "target": "cloud",
        "template": "shell", "want": ",".join(want),
        "boxes": "5" if "$SHARD" in command and not takes_strangers else "1", "cpus": "8", "memory": "16g", "quota_vcpu": "40",
        "ttl": "30m", "minutes": "15", "on_timeout": "delete", "stagger_s": "2", "allow": _allow(det, want), "own_work": "untrusted",
        "trust_roles": "", "trust_team": "", "trust_logins": "", "network_policy": "deny-all" if takes_strangers else "unknown",
        "clone": "public" if takes_strangers else "token", "secret_service": "none" if takes_strangers else "github",
        "secret_env": "" if takes_strangers else "SBX_CLONE_TOKEN", "allowed_secrets": "" if takes_strangers else "github",
        "command": command,
    }


def _cell(value: object) -> str:
    """A value from the project's tree, as data: a file name can hold a newline, a fence or a table's end marker."""
    return "".join(char if char.isprintable() and char not in "`|<>\\{}" else f"\\u{ord(char):04x}" for char in str(value))


def _detection(det: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for key, value in det.items():
        shown = ", ".join(str(item) for item in cast(list[Any], value)) if isinstance(value, list) else value
        rows.append(f"| {key} | {_cell(shown) if shown not in ('', None) else '-'} |")
    return "| Found | Value |\n|---|---|\n" + "\n".join(rows)


def _use_cases(recs: list[dict[str, Any]]) -> str:
    rows = [f"| {r['slug']} | {'yes' if r['applies'] else 'no'} | {r['state']} | {_cell(r['why'])} |" for r in recs]
    return "| Use case | Applies | Evidence state | Why |\n|---|---|---|---|\n" + "\n".join(rows)


def _region(name: str, body: str) -> str:
    return f"<!-- sbx:{name} -->\n{body}\n<!-- sbx:end-{name} -->"


def render_new(template: str, det: Mapping[str, Any], recs: list[dict[str, Any]], config: Mapping[str, str]) -> str:
    return fill(template, {
        "TARGET_PROJECT": config["target_project"], "DETECTION": _region("detection", _detection(det)),
        "USE_CASES": _region("use-cases", _use_cases(recs)), "CONFIG": config_block(config),
        "TRUST_STEP": TRUST_STEP if _open(det) else ""})


def refresh(text: str, det: Mapping[str, Any], recs: list[dict[str, Any]], config: Mapping[str, str]) -> str:
    """Replace only the marked generated regions and add missing keys. Everything a person wrote stays.

    The file's own bytes are parsed, before any tree data joins them: tree data never reaches the parser."""
    if not parse_config(text):
        raise ValueError("this file has no sbx-config block, and onboard never overwrites a file it did not write")
    text = add_missing_keys(text, config)
    for name, body in (("detection", _detection(det)), ("use-cases", _use_cases(recs))):
        pattern = re.compile(rf"<!-- sbx:{name} -->.*?<!-- sbx:end-{name} -->", re.DOTALL)
        region = _region(name, body)
        text = pattern.sub(lambda _match, value=region: value, text)
    return text


def recipe_for(det: Mapping[str, Any]) -> str:
    """The stack recipe under templates/, or ''."""
    if "pytest" in det["test_runner"]:
        return "python.md"
    return "java.md" if "maven-surefire" in det["test_runner"] else ""
