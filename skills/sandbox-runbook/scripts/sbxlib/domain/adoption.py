"""The adoption file's values: the sbx-config block, durations, and placeholders."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .trust import TrustLevel, TrustRules, TrustVerdict, repo_id, repo_rule, untrusted

ADOPTION_FILE = "docs/sbx.md"
PLACEHOLDER = "<set:"  # onboard writes this where a person must decide; a run with it left in is refused
TEMPLATE_VALUE = re.compile(r"\{\{([A-Z_]+)\}\}")
FENCE = "```sbx-config"
REGION_END = "<!-- sbx:end-"  # every generated table ends with this: the block sits below them, where nothing is generated
_OPEN = re.compile(rf"^{FENCE}[ \t]*\r?\n", re.MULTILINE)
_CLOSE = re.compile(r"^```[ \t]*\r?$", re.MULTILINE)


def _body(text: str) -> tuple[int, int] | None:
    """Where the one sbx-config block's lines start and end; None when it has none. Trust rules live here, so anything
    but one block, opened and closed on lines of their own, below the generated tables, is refused."""
    if FENCE not in text:
        return None
    if text.count(FENCE) > 1:
        raise ValueError(f"more than one {FENCE} block: the rules must have one source, and a second may be a planted one")
    opened = _OPEN.search(text)
    if not opened:
        raise ValueError(f"the {FENCE} block must open on its own line")
    if text.find(REGION_END, opened.end()) != -1:
        raise ValueError(f"the {FENCE} block must sit below the generated tables")
    closed = _CLOSE.search(text, opened.end())
    if not closed:
        raise ValueError(f"the {FENCE} block never closes")
    return opened.end(), closed.start()


def parse_config(text: str) -> dict[str, str]:
    """The `key: value` lines of the sbx-config block; {} when it has none. ValueError when the file cannot be read as one."""
    span = _body(text)
    config: dict[str, str] = {}
    for line in text[span[0]:span[1]].split("\n") if span else ():  # not splitlines: U+2028 and friends start no key
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith("#"):
            config[key.strip()] = value.strip()
    return config


def _lines(config: Mapping[str, str]) -> str:
    if any("\n" in value or "\r" in value for value in config.values()):
        raise ValueError("a setting's value holds a line break: it would write a key of its own")
    return "".join(f"{key}: {value}\n" for key, value in config.items())


def config_block(config: Mapping[str, str]) -> str:
    return f"{FENCE}\n{_lines(config)}```"


def add_missing_keys(text: str, config: Mapping[str, str]) -> str:
    """Append keys the block lacks, leaving every key it has, and everything around it, as written."""
    span, existing = _body(text), parse_config(text)
    missing = _lines({key: value for key, value in config.items() if key not in existing})
    return text[:span[1]] + missing + text[span[1]:] if span else text


def words(value: str) -> tuple[str, ...]:
    return tuple(word.strip() for word in value.split(",") if word.strip())


def duration_minutes(text: str) -> int:
    """`30m`, `2h`, `1h30m` or bare minutes -> minutes. ValueError when it is none of those."""
    if text.strip().isdigit():
        return int(text)
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", text.strip().lower())
    if not match or not any(match.groups()):
        raise ValueError(f"not a duration: {text!r} (use 30m, 2h or 1h30m)")
    return int(match[1] or 0) * 60 + int(match[2] or 0)


def trust_rules(config: Mapping[str, str]) -> TrustRules:
    return TrustRules(frozenset(words(config.get("trust_roles", ""))), config.get("trust_team", ""),
                      frozenset(words(config.get("trust_logins", ""))), config.get("repo", ""))


def own_work_verdict(config: Mapping[str, str], repo: str, sha: str) -> TrustVerdict:
    """A run with no pull request: trusted only as the file says, and only in the repository the file names."""
    if config.get("own_work") != "trusted":
        return untrusted("not-proven", sha=sha)
    rule = repo_rule(config.get("repo", ""), repo)
    return untrusted(rule, sha=sha, repo=repo) if rule else TrustVerdict(TrustLevel.TRUSTED, "own-work", {"sha": sha})


def own_work_problem(config: Mapping[str, str]) -> str:
    """A file that says trusted and names no repository: running it untrusted is safe, spends money and drops every log."""
    if config.get("own_work") != "trusted" or repo_id(config.get("repo", "")):
        return ""
    return ("own_work: trusted needs `repo: <owner/name>` in the adoption file: with none, nothing is trusted, and a run would "
            "bring back no log and take no secret. Add it, or rerun sbx_onboard.py, which writes it from origin")


def unfilled(text: str) -> list[str]:
    """Every template value left in `text`: a generated file must hold none."""
    return sorted(set(TEMPLATE_VALUE.findall(text)))


def fill(template: str, values: Mapping[str, str]) -> str:
    """Replace each `{{NAME}}`. A name with no value is an error, so a generated file never keeps one."""
    missing = sorted(set(TEMPLATE_VALUE.findall(template)) - set(values))
    if missing:
        raise ValueError(f"no value for {', '.join(missing)}")
    return TEMPLATE_VALUE.sub(lambda match: values[match[1]], template)
