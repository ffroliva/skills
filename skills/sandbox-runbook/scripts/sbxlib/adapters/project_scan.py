"""Inspect a project: what a sandbox plan needs to know. Reads no secret file and calls no sbx."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from ..domain.fleet import sanitize_project
from ..ports import CommandRunner
from .process import in_dir

SHARD_PLUGINS = ("pytest-split", "pytest-shard", "pytest-test-groups")
SHARD_ENV = re.compile(r"\b(?:[A-Z][A-Z0-9_]*_)?SHARDS?\b")
SYNC_FLAG = re.compile(r"--(?:extra|group)[ =]+[\w.-]+|--all-extras|--all-groups")
SKIPPED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "target", "build", "dist"}
SHARD_FILE_DEPTH = 3
MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "pom.xml", "build.gradle", "build.gradle.kts",
             "package.json", "go.mod", "Cargo.toml", "docker-compose.yml", "docker-compose.yaml", "compose.yml",
             "compose.yaml")
MAX_MANIFEST_BYTES = 2_000_000
BROWSERS = ("cypress", "playwright", "puppeteer", "selenium")
HEAVY_GATES = ("atheris", "cosmic-ray", "hypothesis", "jazzer", "jqwik", "mutmut", "pitest")
JS_RUNNERS = ("jest", "mocha", "vitest")
CI_MARKERS = {".github/workflows": "github-actions", ".gitlab-ci.yml": "gitlab-ci", "Jenkinsfile": "jenkins",
              ".circleci": "circleci", "azure-pipelines.yml": "azure-pipelines"}
LOCK_TOOLS = {"uv.lock": "uv", "poetry.lock": "poetry", "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn",
              "package-lock.json": "npm"}
_CREDENTIAL = re.compile(r"^([a-z][a-z0-9+.-]*://)(?!git@)[^/]*@", re.IGNORECASE)  # `git@` is ssh's ordinary user, and names no secret
SECRET_NAMES = (".env", ".env.local", ".env.production")
SECRET_GLOBS = ("*.pem", "*.key", "*.p12")


def _manifest_text(root: Path) -> str:
    paths = [root / name for name in MANIFESTS]
    paths += list(root.glob("requirements*.txt")) + list(root.glob("*/pom.xml")) + list(root.glob("*/build.gradle*"))
    texts = [path.read_text(encoding="utf-8", errors="replace") for path in paths
             if path.is_file() and path.stat().st_size <= MAX_MANIFEST_BYTES]
    return "\n".join(texts).lower()


def _languages(root: Path) -> list[str]:
    python = (root / "pyproject.toml").exists() or (root / "setup.py").exists() or any(root.glob("requirements*.txt"))
    java = (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists()
    found = {"python": python, "java": java, "javascript": (root / "package.json").exists(),
             "go": (root / "go.mod").exists(), "rust": (root / "Cargo.toml").exists()}
    return [name for name, present in found.items() if present]


def _build_tools(root: Path, languages: list[str]) -> list[str]:
    tools = [tool for name, tool in LOCK_TOOLS.items() if (root / name).exists()]
    if "python" in languages and not {"uv", "poetry"} & set(tools):
        tools.append("pip")
    if "java" in languages:
        tools.append("maven" if (root / "pom.xml").exists() else "gradle")
    if "javascript" in languages and not {"npm", "pnpm", "yarn"} & set(tools):
        tools.append("npm")
    tools += [lang_tool for lang, lang_tool in (("go", "go"), ("rust", "cargo")) if lang in languages]
    return tools


def _test_runners(root: Path, languages: list[str], tools: list[str], text: str) -> list[str]:
    runners: list[str] = []
    if "python" in languages and ("pytest" in text or (root / "tests").is_dir()):
        runners.append("pytest")
    if "maven" in tools:
        runners.append("maven-surefire")
    if "gradle" in tools:
        runners.append("gradle-test")
    runners += [runner for runner in JS_RUNNERS if "javascript" in languages and runner in text]
    runners += [name for lang, name in (("go", "go-test"), ("rust", "cargo-test")) if lang in languages]
    return runners


def _secret_files(root: Path) -> list[str]:
    names = {name for name in SECRET_NAMES if (root / name).is_file()}
    for pattern in SECRET_GLOBS:
        names |= {path.name for path in root.glob(pattern)}
    return sorted(names)


def _remote(run: CommandRunner) -> str:
    done = run(["git", "remote", "get-url", "origin"])
    if done.rc != 0:
        return ""
    return _CREDENTIAL.sub(r"\1", done.out.strip())  # a token in a URL must never reach a report


def _visibility(remote: str, run: CommandRunner) -> str:
    slug = re.search(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$", remote)
    if not slug:
        return "unknown"
    done = run(["gh", "repo", "view", slug.group(1), "--json", "visibility", "--jq", ".visibility"])
    return done.out.strip().lower() if done.rc == 0 and done.out.strip() else "unknown"


def _ci_text(root: Path) -> str:
    files = [*(root / ".github" / "workflows").glob("*.y*ml"), root / ".gitlab-ci.yml"]
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files if f.is_file())


def _shard_files(root: Path) -> list[Path]:
    """Files whose name says shard, at most SHARD_FILE_DEPTH folders deep, skipping dependency and build folders."""
    found: list[Path] = []
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:  # a root-owned folder such as pgdata/
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < SHARD_FILE_DEPTH and entry.name not in SKIPPED_DIRS:
                    stack.append((entry, depth + 1))
            elif "shard" in entry.name.lower():
                found.append(entry)
    return sorted(found)


def _sharding(root: Path, manifest: str, ci: str) -> list[str]:
    """How the project already splits its tests: a plugin, a shard file, a shard variable. [] when none."""
    found = [f"plugin:{name}" for name in SHARD_PLUGINS if name in manifest]
    texts = [ci]
    for path in _shard_files(root):
        found.append(f"file:{path.relative_to(root).as_posix()}")
        if path.is_file() and path.stat().st_size <= MAX_MANIFEST_BYTES:  # a broken link is named, not read
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    names = {name for text in texts for name in SHARD_ENV.findall(text)}
    return found + [f"env:{name}" for name in sorted(names)]


def _sync_flags(ci: str) -> list[str]:
    """The extras and groups the project's CI syncs with, in order and without repeats: `--extra test`."""
    flags = [re.sub(r"[ =]+", " ", flag) for line in ci.splitlines() if "uv " in line
             for flag in SYNC_FLAG.findall(line)]
    return list(dict.fromkeys(flags))


def _target_project(remote: str, root: Path) -> str:
    name = re.search(r"([^/:]+?)(?:\.git)?$", remote)
    return sanitize_project(name[1] if name else root.resolve().name)


def _host_os() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def detect(root: Path, run: CommandRunner | None = None) -> dict[str, Any]:
    root = Path(root)
    run = run or in_dir(root)
    text = _manifest_text(root)
    ci = _ci_text(root)
    languages = _languages(root)
    tools = _build_tools(root, languages)
    remote = _remote(run)
    return {
        "target_project": _target_project(remote, root),
        "language": languages,
        "build_tool": tools,
        "test_runner": _test_runners(root, languages, tools, text),
        "parallel_runner": "xdist" in text,
        "testcontainers": "testcontainers" in text,
        "browser": [name for name in BROWSERS if name in text],
        "ci": [name for marker, name in CI_MARKERS.items() if (root / marker).exists()],
        "benchmarks": (root / "benchmarks").is_dir() or bool(re.search(r"pytest-benchmark|\bjmh\b|\basv\b", text)),
        "heavy_gates": [name for name in HEAVY_GATES if name in text],
        "secret_files": _secret_files(root),
        "remote": remote,
        "repo_visibility": _visibility(remote, run) if remote else "unknown",
        "host_os": _host_os(),
        "sharding": _sharding(root, text, ci),
        "sync_flags": _sync_flags(ci),
    }
