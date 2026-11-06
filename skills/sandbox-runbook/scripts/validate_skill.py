"""Validate this repository: skill frontmatter, OKF docs, links, evidence URLs, use cases, troubleshooting, and a leak scan.

The leak scan runs generic checks on every file. SBX_SKILL_DENYLIST may name a plain word list kept outside the repo:
such a list is never committed, in any form. Prints every finding and exits 1 if there are any.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from sbxlib.adapters.process import in_dir
from sbxlib.domain.adoption import TEMPLATE_VALUE
from sbxlib.domain.drift import VERBS, is_valid_snapshot
from sbxlib.domain.known_errors import KNOWN

MAX_BODY_WORDS = 1500
MAX_DESCRIPTION = 1024
KEYWORDS = ("sandbox", "sbx", "fleet", "testcontainers", "parallel agents", "cloud box", "kit", "offload tests")
WORKFLOW_WORDS = re.compile(r"\b(first|then|next|step|steps|after that|writes?|generates?)\b", re.IGNORECASE)
OKF_FIELDS = ("title", "description", "tags", "status", "date")
STATES = ("measured", "tried-once", "untested-idea")
TRUST_LEVELS = ("trusted", "untrusted")
UNPUBLISHED_LABEL = "target project"
ENTRY_FIELDS = ("Symptom", "Error", "Cause", "Fix", "Confirm", "Seen on")
TEMPLATE_VALUES = {"TARGET_PROJECT", "DETECTION", "USE_CASES", "CONFIG", "TRUST_STEP"}
ALLOWED_REPOS = {
    "ajeetraina/awesome-docker-sbx", "docker/docs", "docker/sandbox-kit-spec", "docker/sbx-kits-contrib",
    "docker/sbx-releases", "dockersamples/sbx-quickstart", "dvdksn/kits-cookbook", "ffroliva/skills",
    "ffroliva/sbx-team-kit", "ffroliva/sharpit", "geut/sbx-shell-pi", "github/docs", "maxkrivich/sbx-toolkit",
    "docker/skills", "shelajev/sbx-skill", "karanverma/sbx-ai-eval-kit",
    "mattjohnson/orca-sbx-recipes", "dirien/herdr-sbx-plugin", "restuhaqza/deepagents-sbx",
}
ALLOWED_HOSTS = ("docs.docker.com", "hub.docker.com", "docs.github.com")
ALLOWED_PAGES = ("settings/personal-access-tokens", "settings/tokens")
ROOT_LINK_FILES = ("README.md", "resources.md")
SKIPPED_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache"}
BINARY_SUFFIXES = (".png", ".jpg", ".gif", ".pyc")
LOCAL_PATHS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])[\w.\\/-]*", r"/c/(?:users|development)\b", r"/home/(?!agent\b)\w+", r"/users/\w+",
    r"/mnt/\w+", r"(?<![\w.])/root/\w+", r"(?<![\w\"'\\])\\\\[a-z][\w.-]+\\\w+"))
SECRET_SHAPES = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|AKIA[0-9A-Z]{16}|dckr_pat_[\w-]{16,}"
                           r"|sk-ant-[\w-]{20,})")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")
EMAIL_OK = ("github.com", "users.noreply.github.com", "example.com")
FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1\s*$", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
URL = re.compile(r"https?://[^\s)\]>\"'`]*")
PINNED = re.compile(r"/(blob|tree)/[0-9a-f]{40}(/|$)")
NUMBERED = re.compile(r"/(issues|pull)/\d+/?$")
PIN = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(?:blob|tree)/([0-9a-f]{40})")
# A repo cited at two commits on purpose, each named: two of its sharding sources exist at one commit only.
SECOND_PINS = {"ffroliva/sharpit": frozenset({"31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700", "e1e5f7e33535e25bb0fd11abc0011d46c4e71abb"})}
SHARED_SCRIPT = re.compile(r"`?(\w+\.py)`?")
LOOKALIKES = str.maketrans("аеорсхіѕԁ", "aeopcxisd")  # noqa: RUF001  Cyrillic NFKD leaves alone


def normalise(text: str) -> str:
    """Letters and digits only, lower case, accents and look-alikes folded: `Äcme-Corp` and `acmecorp` are one word."""
    folded = unicodedata.normalize("NFKD", text.lower().translate(LOOKALIKES)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", folded)


def load_denylist(root: Path) -> frozenset[str]:
    """The optional list. It must live outside the repository, and a list that cannot be read is an error."""
    named = os.environ.get("SBX_SKILL_DENYLIST", "")
    if not named:
        return frozenset()
    path = Path(named).resolve()
    if path.is_relative_to(root.resolve()):
        raise ValueError("SBX_SKILL_DENYLIST must point outside the repository")
    if not path.is_file():
        raise ValueError("SBX_SKILL_DENYLIST names no file")
    words = {normalise(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    if any(len(word) < 2 for word in words):
        raise ValueError("SBX_SKILL_DENYLIST holds an entry the scan can never match")
    return frozenset(words)


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """(fields, body). fields is None when the file has no frontmatter. Only top-level `key: value` lines are read."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None, text
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        return None, text
    fields: dict[str, str] = {}
    for line in head.splitlines():
        key, colon, value = line.partition(":")
        if colon and not line.startswith((" ", "-", "#")):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields, body


def _strip_code(text: str) -> str:
    return INLINE_CODE.sub("", FENCE.sub("", text))


def _all_files(root: Path) -> list[Path]:
    """Every file git would publish, or every file when `root` is no repository."""
    done = in_dir(root)(["git", "ls-files", "--cached", "--others", "--exclude-standard"])
    if done.rc == 0 and done.out.strip() and (root / ".git").exists():
        return sorted({root / line for line in done.out.splitlines() if (root / line).is_file()})
    return [path for path in sorted(root.rglob("*")) if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(root).parts)]


def _markdown(root: Path) -> list[Path]:
    return [path for path in _all_files(root) if path.suffix == ".md"]


def _check_skill(root: Path) -> list[str]:
    path = root / "skills" / "sandbox-runbook" / "SKILL.md"
    if not path.is_file():
        return ["skills/sandbox-runbook/SKILL.md: missing"]
    fields, body = split_frontmatter(path.read_text(encoding="utf-8"))
    if fields is None:
        return ["skills/sandbox-runbook/SKILL.md: no frontmatter"]
    problems: list[str] = []
    description = fields.get("description", "")
    if fields.get("name") != "sandbox-runbook":
        problems.append("SKILL.md: frontmatter name must be sandbox-runbook")
    if not fields.get("compatibility") or "sbx" not in fields.get("compatibility", "").lower():
        problems.append("SKILL.md: frontmatter compatibility must pin a checked sbx version")
    if not description.startswith("Use when"):
        problems.append('SKILL.md: description must start "Use when"')
    if len(description) > MAX_DESCRIPTION:
        problems.append(f"SKILL.md: description is over {MAX_DESCRIPTION} characters")
    problems += [f"SKILL.md: description lacks keyword {word!r}" for word in KEYWORDS if word not in description.lower()]
    if WORKFLOW_WORDS.search(description):
        problems.append("SKILL.md: description summarises a workflow; keep triggering conditions only")
    for line in body.splitlines():
        current_word = re.search(r"\b(?:current|latest)\b", line, re.IGNORECASE)
        literal_reference = re.search(r"\b(?:current environment|latest tag|:latest)\b", line, re.IGNORECASE)
        if current_word and not literal_reference:
            problems.append("SKILL.md: replace current/latest factual wording with a dated version")
            break
    words = len(body.split())
    if words > MAX_BODY_WORDS:
        problems.append(f"SKILL.md: body has {words} words, over {MAX_BODY_WORDS}")
    return problems + _check_sections(root, body)


def _note_trust(notes: Path, name: str) -> str | None:
    path = notes / name
    fields = split_frontmatter(path.read_text(encoding="utf-8"))[0] if path.is_file() else None
    return (fields or {}).get("trust")


def _check_section(root: Path, section: str, notes: Path) -> tuple[list[str], set[str]]:
    title = section.splitlines()[0]
    problems: list[str] = []
    script_line = next((line for line in section.splitlines() if "Script:" in line), None)
    if script_line is None:
        problems.append(f"SKILL.md: section {title!r} names no Script: line")
    else:
        problems += [f"SKILL.md: section {title!r} names {name}, which does not exist"
                     for name in SHARED_SCRIPT.findall(script_line.partition("Script:")[2].partition("Deep note")[0])
                     if not (root / "skills" / "sandbox-runbook" / "scripts" / name).is_file()]
    trust = re.search(r"\bTrust: (trusted|untrusted)\b", section)
    if not trust:
        problems.append(f"SKILL.md: section {title!r} states no trust level")
    linked = set(re.findall(r"docs/use-cases/([\w-]+\.md)", section))
    if trust:
        problems += [f"SKILL.md: section {title!r} and {name} disagree on trust" for name in sorted(linked)
                     if _note_trust(notes, name) not in (None, trust[1])]
    return problems, linked


def _check_sections(root: Path, body: str) -> list[str]:
    problems: list[str] = []
    linked: set[str] = set()
    notes = root / "skills" / "sandbox-runbook" / "docs" / "use-cases"
    for section in re.split(r"^## Use case: ", body, flags=re.MULTILINE)[1:]:
        found, names = _check_section(root, section, notes)
        problems += found
        linked |= names
    if notes.is_dir():
        problems += [f"skills/sandbox-runbook/docs/use-cases/{path.name}: no use case section in SKILL.md"
                     for path in sorted(notes.glob("*.md")) if path.name not in linked]
    return problems


def _check_docs(root: Path) -> list[str]:
    problems: list[str] = []
    docs = root / "skills" / "sandbox-runbook" / "docs"
    for path in sorted(docs.rglob("*.md")) if docs.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        fields, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        if fields is None:
            problems.append(f"{rel}: no OKF frontmatter")
            continue
        if fields.get("type") != "Knowledge":
            problems.append(f"{rel}: type must be Knowledge")
        problems += [f"{rel}: frontmatter lacks {key}" for key in OKF_FIELDS if not fields.get(key)]
        if path.parent.name == "use-cases":
            problems += _check_use_case(rel, fields)
    return problems


def _check_use_case(rel: str, fields: dict[str, str]) -> list[str]:
    problems: list[str] = []
    state, source = fields.get("state"), fields.get("source", "")
    if state not in STATES:
        problems.append(f"{rel}: state must be one of {', '.join(STATES)}")
    if fields.get("trust") not in TRUST_LEVELS:
        problems.append(f"{rel}: trust must be one of {', '.join(TRUST_LEVELS)}")
    if not source:
        problems.append(f"{rel}: frontmatter lacks source")
    elif state != "untested-idea" and "://" not in source and UNPUBLISHED_LABEL not in source:
        problems.append(f"{rel}: a {state} use case needs a URL source, or the target project label")
    return problems


def _check_troubleshooting(root: Path) -> list[str]:
    path = root / "skills" / "sandbox-runbook" / "docs" / "troubleshooting.md"
    if not path.is_file():
        return ["skills/sandbox-runbook/docs/troubleshooting.md: missing"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    entries = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
    anchors = {entry.splitlines()[0].strip() for entry in entries}
    for entry in entries:
        anchor = entry.splitlines()[0].strip()
        problems += [f"troubleshooting.md: {anchor} lacks {field}" for field in ENTRY_FIELDS if f"**{field}:**" not in entry]
    problems += [f"troubleshooting.md: no entry {anchor}, which the scripts print"
                 for anchor in sorted({anchor for _, anchor in KNOWN} - anchors)]
    return problems


def _check_templates(root: Path) -> list[str]:
    problems: list[str] = []
    folder = root / "skills" / "sandbox-runbook" / "templates"
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        unknown = sorted(set(TEMPLATE_VALUE.findall(text)) - TEMPLATE_VALUES)
        problems += [f"templates/{path.name}: unknown value {name}" for name in unknown]
        if "<your-" in text:
            problems.append(f"templates/{path.name}: use {{{{TARGET_PROJECT}}}}, the one placeholder")
    return problems


def _check_links(root: Path) -> list[str]:
    problems: list[str] = []
    root = root.resolve()
    skill = root / "skills" / "sandbox-runbook"
    for path in _markdown(root):
        path = path.resolve()
        rel = path.relative_to(root).as_posix()
        full = path.read_text(encoding="utf-8")
        for target in LINK.findall(_strip_code(full)):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            if not resolved.exists():
                problems.append(f"{rel}: broken link {target}")
            elif skill in path.parents and skill not in resolved.parents and resolved != skill:
                problems.append(f"{rel}: {target} leaves the skill folder, so it breaks once the folder is linked")
        for url in URL.findall(full):  # code spans too: an internal URL must not hide in backticks
            problems += _check_url(rel, path.name, url.rstrip(".,;:"))
    return problems


def _check_url(rel: str, filename: str, url: str) -> list[str]:
    parts = urlsplit(url)
    host, tail = parts.netloc, parts.path
    if host in ALLOWED_HOSTS:
        return []
    bits = tail.strip("/").split("/")
    repo = "/".join(bits[:2]).removesuffix(".git")
    if host != "github.com" or (repo not in ALLOWED_REPOS and repo not in ALLOWED_PAGES):
        return [f"{rel}: {url} is not on the public allow-list"]
    if repo in ALLOWED_PAGES or PINNED.search(tail) or NUMBERED.search(tail):
        return []
    if len(bits) == 2 and filename in ROOT_LINK_FILES:
        return []
    return [f"{rel}: {url} is not pinned to a commit"]


def _check_pins(root: Path) -> list[str]:
    """Every pin of one repository names one commit: a repin that missed a link cites two versions of the same evidence."""
    seen: dict[str, dict[str, str]] = {}
    for path in _all_files(root):
        if path.suffix in (".md", ".yml"):  # where evidence is cited; tests plant pins of their own
            for repo, sha in PIN.findall(path.read_text(encoding="utf-8", errors="replace")):
                seen.setdefault(repo, {}).setdefault(sha, path.relative_to(root).as_posix())
    return [f"{repo} is pinned at {len(shas)} commits: " + ", ".join(f"{sha[:12]} in {where}" for sha, where in sorted(shas.items()))
            for repo, shas in sorted(seen.items()) if len(shas) > 1 and not set(shas) <= SECOND_PINS.get(repo, frozenset())]


def _check_leaks(root: Path, deny: frozenset[str]) -> list[str]:
    problems: list[str] = []
    for path in _all_files(root):
        if path.suffix in BINARY_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [rel, *text.splitlines()]
        folded = {normalise(line) for line in lines}
        problems += [f"{rel}: leak, a denied name" for word in sorted(deny) if any(word in line for line in folded)]
        problems += [f"{rel}: local path {match.group(0)}" for pattern in LOCAL_PATHS for match in pattern.finditer(text)]
        problems += [f"{rel}: secret shape" for _ in SECRET_SHAPES.finditer(text)]
        problems += [f"{rel}: personal email domain {match.group(1)}" for match in EMAIL.finditer(text)
                     if match.group(1).rstrip(".") not in EMAIL_OK]
        if path.suffix == ".md" and "private project" in text.lower():
            problems.append(f"{rel}: write target project: evidence names no project")
    return problems


def _check_snapshot(root: Path) -> list[str]:
    path = root / "skills" / "sandbox-runbook" / "references" / "cli-snapshot.json"
    if not path.is_file():
        return ["skills/sandbox-runbook/references/cli-snapshot.json: snapshot missing; run sbx_drift.py snapshot"]
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"skills/sandbox-runbook/references/cli-snapshot.json: snapshot unreadable ({exc})"]
    if not is_valid_snapshot(snapshot):
        return ["skills/sandbox-runbook/references/cli-snapshot.json: snapshot unreadable"]
    problems = [] if re.fullmatch(r"\d+\.\d+\.\d+", str(snapshot["version"])) else ["cli-snapshot.json: version is not X.Y.Z"]
    return problems + [f"cli-snapshot.json: command {verb!r} is absent from the snapshot" for verb in VERBS
                       if verb not in snapshot["verbs"]]


def validate(root: Path, deny: frozenset[str]) -> list[str]:
    root = Path(root)
    return (_check_skill(root) + _check_docs(root) + _check_troubleshooting(root) + _check_templates(root)
            + _check_links(root) + _check_pins(root) + _check_leaks(root, deny) + _check_snapshot(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3], help="repository root")
    args = parser.parse_args(argv)
    try:
        findings = validate(args.root, load_denylist(args.root))
    except ValueError as exc:
        print(f"validate_skill: {exc}")
        return 1
    for finding in findings:
        print(finding)
    print(f"validate_skill: {len(findings)} finding(s)" if findings else "validate_skill: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
