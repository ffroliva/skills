"""Every manifest states one version and one name, one copy of the skill exists, and a tag run equals that version.

Each harness has its own manifest, all thin, all pointing at `skills/`. They go stale together unless something checks them.
Exit 0 aligned, 1 with every finding printed. A tag run is read from GITHUB_REF_TYPE and GITHUB_REF_NAME, which GitHub sets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

VERSIONED = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".antigravity-plugin/plugin.json", "gemini-extension.json")
MARKETPLACES = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")
ANTIGRAVITY = ".antigravity-plugin/plugin.json"
CODEX = ".codex-plugin/plugin.json"
SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache"}
MAX_ANTIGRAVITY_DESCRIPTION = 160
VERSION = re.compile(r"\d+\.\d+\.\d+")


def _load(root: Path, name: str, problems: list[str]) -> dict[str, Any]:
    try:
        value = json.loads((root / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"{name}: missing")
        return {}
    except ValueError:
        problems.append(f"{name}: not JSON")
        return {}
    if not isinstance(value, dict):
        problems.append(f"{name}: not a JSON object")
        return {}
    return cast(dict[str, Any], value)


def _names(root: Path, manifests: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for file, manifest in manifests.items():
        name = str(manifest.get("name", ""))
        # Gemini installs one extension per skill; the other manifests name the multi-skill plugin bundle.
        expected = "sandbox-runbook" if file == "gemini-extension.json" else "ffroliva-skills"
        if name != expected or not (root / "skills" / "sandbox-runbook" / "SKILL.md").is_file():
            problems.append(f"{file}: name must be {expected}, with skills/sandbox-runbook/SKILL.md present")
    return problems


def _copies(root: Path) -> list[str]:
    found = sorted(path.relative_to(root).as_posix() for path in root.rglob("SKILL.md") if not SKIPPED_DIRS & set(path.parts))
    return [] if len(found) == 1 else [f"one copy of the skill, found {len(found)}: {', '.join(found)}"]


def _marketplaces(root: Path, problems: list[str], plugin: str) -> None:
    for file in MARKETPLACES:
        listed = [row.get("name") for row in _load(root, file, problems).get("plugins", [])]
        if plugin not in listed:
            problems.append(f"{file}: does not list {plugin}")


def _version(manifests: dict[str, dict[str, Any]], problems: list[str]) -> str:
    stated = {file: str(manifest.get("version", "")) for file, manifest in manifests.items()}
    problems += [f"{file}: version {value!r} is not X.Y.Z" for file, value in stated.items() if not VERSION.fullmatch(value)]
    versions = sorted(set(stated.values()))
    if len(versions) > 1:
        problems += [f"{file}: says {value}" for file, value in stated.items()]
    return versions[-1] if versions else ""


def check(root: Path, env: dict[str, str]) -> tuple[str, list[str]]:
    """(the version, every finding)."""
    problems: list[str] = []
    manifests = {file: _load(root, file, problems) for file in VERSIONED}
    version = _version(manifests, problems)
    problems += _names(root, {file: manifest for file, manifest in manifests.items() if manifest}) + _copies(root)
    _marketplaces(root, problems, "ffroliva-skills")
    if len(str(manifests[ANTIGRAVITY].get("description", ""))) > MAX_ANTIGRAVITY_DESCRIPTION:
        problems.append(f"{ANTIGRAVITY}: description is over {MAX_ANTIGRAVITY_DESCRIPTION} characters")
    if manifests[CODEX] and manifests[CODEX].get("skills") != "./skills/":
        problems.append(f"{CODEX}: skills must be ./skills/, the one copy")
    log = root / "CHANGELOG.md"
    if not log.is_file() or f"\n## {version}\n" not in log.read_text(encoding="utf-8").replace("\r\n", "\n"):
        problems.append(f"CHANGELOG.md: no heading ## {version}")
    if env.get("GITHUB_REF_TYPE") == "tag" and env.get("GITHUB_REF_NAME") != f"v{version}":
        problems.append(f"tag {env.get('GITHUB_REF_NAME')} is not v{version}")
    return version, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    args = parser.parse_args(argv)
    version, problems = check(args.root, dict(os.environ))
    for line in problems:
        print(line)
    print(f"check_versions: {len(problems)} finding(s)" if problems else f"check_versions: {version}, aligned")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
