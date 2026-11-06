"""The dependency rule in docs/reference/architecture.md, checked on the import statements of every module."""

from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "skills" / "sandbox-runbook" / "scripts" / "sbxlib"
DOMAIN_STDLIB = {"__future__", "collections", "dataclasses", "enum", "fnmatch", "hashlib", "re", "shlex", "typing"}
APP_STDLIB = DOMAIN_STDLIB | {"concurrent", "json", "threading"}
LAYER_MAY_IMPORT = {"domain": {"domain"}, "app": {"domain", "ports", "app"}, "adapters": {"domain", "ports", "adapters"}}


def _imports(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            yield from (f"{base}.{alias.name}" if base.endswith(("sbxlib", ".")) else base for alias in node.names)


def _layer_of(name: str, module: Path, package: Path) -> str | None:
    """The sbxlib layer a dotted import reaches, resolving relative imports; None for a non-sbxlib import."""
    if name.startswith("."):
        dots = len(name) - len(name.lstrip("."))
        parent = module.parent
        for _ in range(dots - 1):
            parent = parent.parent
        target = parent.joinpath(*name.lstrip(".").split("."))
        parts = target.relative_to(package).parts if target.is_relative_to(package) else ("?",)
        return parts[0].removesuffix(".py") if parts else None
    if name == "sbxlib" or name.startswith("sbxlib."):
        return name.split(".")[1] if "." in name else "?"
    return None


def violations(package: Path) -> list[str]:
    found = []
    for module in sorted(package.rglob("*.py")):
        layer = module.relative_to(package).parts[0].removesuffix(".py")
        tree = ast.parse(module.read_text(encoding="utf-8"))
        rel = module.relative_to(package).as_posix()
        for name in _imports(tree):
            target = _layer_of(name, module, package)
            top = name.split(".")[0]
            if layer in LAYER_MAY_IMPORT and target is not None and target not in LAYER_MAY_IMPORT[layer]:
                found.append(f"{rel}: {layer} imports {target}")
            if target is None and layer == "domain" and top not in DOMAIN_STDLIB:
                found.append(f"{rel}: domain imports {top}")
            if target is None and layer == "app" and top not in APP_STDLIB:
                found.append(f"{rel}: app imports {top}")
            if layer == "ports" and target not in (None, "domain"):
                found.append(f"{rel}: ports imports {target}")
        if layer in ("domain", "app"):
            found += [f"{rel}: reads os.environ" for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute) and node.attr == "environ"]
            found += [f"{rel}: calls open" for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"]
            found += [f"{rel}: imports at runtime" for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "__import__"]
    return found


class Boundary(unittest.TestCase):
    def test_the_package_keeps_the_dependency_rule(self) -> None:
        self.assertEqual(violations(PACKAGE), [])

    def _planted(self, relative: str, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / "sbxlib"
            shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
            target = copy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            return violations(copy)

    def test_a_planted_subprocess_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: domain imports subprocess", self._planted("domain/planted.py", "import subprocess\n"))

    def test_a_planted_adapter_import_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: domain imports adapters",
                      self._planted("domain/planted.py", "from sbxlib.adapters import process\n"))

    def test_a_planted_relative_adapter_import_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: domain imports adapters",
                      self._planted("domain/planted.py", "from ..adapters import process\n"))

    def test_a_planted_environ_read_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: reads os.environ", self._planted("domain/planted.py", "x = 0\ny = x.environ\n"))

    def test_a_planted_network_import_in_the_app_is_caught(self) -> None:
        self.assertIn("app/planted.py: app imports urllib", self._planted("app/planted.py", "import urllib.request\n"))

    def test_a_planted_adapter_import_in_the_app_is_caught(self) -> None:
        self.assertIn("app/planted.py: app imports adapters", self._planted("app/planted.py", "from sbxlib.adapters import gh_cli\n"))

    def test_a_planted_stdlib_module_the_app_never_needed_is_caught(self) -> None:
        self.assertIn("app/planted.py: app imports glob", self._planted("app/planted.py", "import glob\n"))

    def test_a_planted_runtime_import_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: imports at runtime", self._planted("domain/planted.py", "x = __import__('subprocess')\n"))

    def test_a_planted_importlib_in_the_app_is_caught(self) -> None:
        self.assertIn("app/planted.py: app imports importlib", self._planted("app/planted.py", "import importlib\n"))

    def test_a_planted_open_in_the_domain_is_caught(self) -> None:
        self.assertIn("domain/planted.py: calls open", self._planted("domain/planted.py", "x = open('f')\n"))

    def test_a_planted_open_in_the_app_is_caught(self) -> None:
        self.assertIn("app/planted.py: calls open", self._planted("app/planted.py", "x = open('f')\n"))

    def test_a_planted_adapter_import_in_the_ports_is_caught(self) -> None:
        self.assertIn("ports.py: ports imports adapters", self._planted("ports.py", "from sbxlib.adapters import gh_cli\n"))


if __name__ == "__main__":
    unittest.main()
