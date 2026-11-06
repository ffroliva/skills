"""Write or update a target project's adoption file, and its stack recipe, filled with the project's name.

An update replaces only the generated tables and adds missing settings: everything a person wrote stays. A file with no
sbx-config block is refused, never overwritten.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sbxlib.adapters.project_scan import detect
from sbxlib.domain.adoption import ADOPTION_FILE, fill, parse_config, words
from sbxlib.domain.onboard import default_config, recipe_for, recommend, refresh, render_new

SKILL = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL / "templates" / "adoption.md"
RECIPE = "docs/sbx-recipe.md"
STATE = re.compile(r"^state: ([\w-]+)$", re.MULTILINE)
STATE_NOTE = re.compile(r"^state_note: (.+)$", re.MULTILINE)  # a state that differs by sbx version says so here


def use_case_states() -> dict[str, str]:
    """Each note's evidence state, from its own frontmatter."""
    states: dict[str, str] = {}
    for path in sorted((SKILL / "docs" / "use-cases").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = STATE_NOTE.search(text) or STATE.search(text)
        states[path.stem] = match[1] if match else "unknown"
    return states


def onboard(root: Path, target: str, want: tuple[str, ...], outside: Path | None = None) -> Path:
    """`outside` is for a project that must stay untouched: the file and its recipe go there, and nothing goes in the project."""
    root = root.resolve()
    path = outside.resolve() if outside else (root / target).resolve()
    if not outside and not path.is_relative_to(root):
        raise ValueError(f"{target} is outside the project: to keep the file elsewhere, pass --config")
    det = detect(root)
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    earlier = parse_config(existing) if existing else {}
    wanted = tuple(dict.fromkeys([*words(earlier.get("want", "")), *want]))
    config = default_config(det, wanted)
    recs = recommend(det, use_case_states(), wanted)
    if existing is None:
        text = render_new(TEMPLATE.read_text(encoding="utf-8"), det, recs, config)
    else:
        text = refresh(existing, det, recs, config)
        if want:  # a stated need outlives a rerun, joined with the earlier one
            text = re.sub(r"^want:.*$", f"want: {','.join(wanted)}", text, count=1, flags=re.MULTILINE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    project = earlier.get("target_project") or config["target_project"]
    _write_recipe(path.with_name(Path(RECIPE).name) if outside else root / RECIPE, recipe_for(det), project)
    return path


def _write_recipe(target: Path, name: str, project: str) -> None:
    if name and not target.exists():  # once written it is the project's own
        text = (SKILL / "templates" / name).read_text(encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fill(text, {"TARGET_PROJECT": project}), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    known = sorted(use_case_states())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path, help="the project (default: here)")
    parser.add_argument("--file", default=ADOPTION_FILE, help=f"adoption file, relative to the project ({ADOPTION_FILE})")
    parser.add_argument("--config", type=Path, help="write the adoption file here, at any path, and the recipe beside it, and "
                        "nothing in the project; the fleet's --config reads it from there")
    parser.add_argument("--want", action="append", default=[], metavar="USE_CASE", help="a use case the team needs although "
                        f"detection does not see it yet (one of: {', '.join(known)}); repeat. Kept on rerun")
    args = parser.parse_args(argv)
    unknown = [name for name in args.want if name not in known]
    if unknown:
        print(f"sbx_onboard: unknown use case {', '.join(unknown)}; choose from {', '.join(known)}")
        return 2
    try:
        path = onboard(args.root, args.file, tuple(args.want), args.config)
    except ValueError as exc:
        print(f"sbx_onboard: {exc}")
        return 2
    print(f"sbx_onboard: wrote {path}. Review `own_work`, `quota_vcpu`, `network_policy` and `command`, then run sbx_check.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
