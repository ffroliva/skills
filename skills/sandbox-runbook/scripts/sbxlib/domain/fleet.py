"""A fleet run as values: its request, its box names, the script each box runs, and its verdict."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum

from .adoption import PLACEHOLDER
from .profile import NetworkPolicy, RunProfile, SecretPolicy, TemplatePolicy

# sbx --cloud create --help, sbx 0.51.0: at least two characters, starting with a letter or number, letters, numbers and
# hyphens only. No length limit is stated; 30 for the project part is a cautious choice, unverified.
MAX_PROJECT = 30
BOX_HOME = "/home/agent"
DEFAULT_ALLOW = ("github.com", "**.githubusercontent.com")
SHAPES = {1: "2g", 2: "4g", 4: "8g", 8: "16g", 16: "32g"}  # sbx --cloud create --help, 0.51.0; memory in GiB
VCPU_HOUR_USD = 0.07  # linear across shapes: $0.56 an hour for 8 vCPU, $0.28 for 4, read in October 2026; docs/reference/sizing.md
TERMINATOR = "SBX_COMMAND_END"
MAX_STAGGER_S = 300  # between creates; past this a box waits longer than most TTLs
_REPO = re.compile(r"https://[^\s/@]+/[^\s?#@]+")  # no query or user part: both are ways to carry a credential
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEMPLATE = re.compile(r"shell|\.{0,2}/\S+|(?!-)[\w.-]+(?:/[\w.-]+)+(?::[\w.-]+)?(?:@sha256:[0-9a-f]{64})?")
_NAMED_HOST = re.compile(r"(?:\*\*?\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE)
_TRANSIENT = re.compile(r"(?:status code:?|HTTP)\s*429\b|settings platform construction failed")
_CONTROL = re.compile(r"[^\x20-\x7e]+")
_V1_COMMAND = re.compile(r"##+\[")
_MEMORY = re.compile(r"(\d+)\s*(?:g|gi|gb|gib)", re.IGNORECASE)
# The API domains the proxy injects each stored secret into, from Docker's "Manage credentials" page, read 2026-11-05.
# A service absent here, such as copilot or devin, has no published list: it is read as reaching every host.
SERVICE_HOSTS = {
    "anthropic": ("api.anthropic.com", "console.anthropic.com", "claude.ai", "mcp-proxy.anthropic.com"),
    "cursor": ("api2.cursor.sh", "api3.cursor.sh", "repo42.cursor.sh", "cursor.com"),
    "droid": ("api.factory.ai", "app.factory.ai", "relay.factory.ai"),
    "github": ("api.github.com", "github.com", "raw.githubusercontent.com", "gist.github.com", "copilot.github.com",
               "api.githubcopilot.com"),
    "google": ("generativelanguage.googleapis.com", "oauth2.googleapis.com", "aiplatform.googleapis.com",
               "vertexai.googleapis.com"),
    "groq": ("api.groq.com",),
    "mistral": ("api.mistral.ai",),
    "nebius": ("api.studio.nebius.com", "api.tokenfactory.nebius.com"),
    "openai": ("api.openai.com", "openai.com", "chatgpt.com", "www.chatgpt.com"),
    "openrouter": ("openrouter.ai",),
    "xai": ("api.x.ai",),
}


class Mode(Enum):
    TARGETED = "targeted"
    SHARDS = "shards"
    PULL = "pr"


_FLEET_SCOPE = re.compile(rf"[a-z0-9][a-z0-9-]*-(?:{'|'.join(mode.value for mode in Mode)})-\d{{2,}}-[a-z0-9]{{4}}")
_PLAIN_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE)


@dataclass(frozen=True)
class RunRequest:
    repo: str
    sha: str
    commands: tuple[str, ...]
    project: str
    run_id: str
    mode: Mode = Mode.TARGETED
    template: str = "shell"
    cpus: int = 8
    memory: str = "16g"
    quota: int = 40
    ttl_minutes: int = 30
    minutes: int = 15
    allow: tuple[str, ...] = ()
    secret_service: str = ""
    env_names: tuple[str, ...] = ()
    allowed_secrets: frozenset[str] = frozenset()
    network_policy: str = ""
    clone: str = "public"
    pull: int | None = None
    stagger: float = 2.0
    require_junit: bool = True
    labels: tuple[str, ...] = ()  # one per box, for a person: a label never reaches a box name, which sweep parses
    expect_tests: int | None = None  # the JUnit cases the whole run must report
    means: str = ""  # what green means on a gate whose pass and fail are inverted
    max_usd: float | None = None
    per_box: bool = False  # each box's command was given on its own, so a repeat is on purpose: a benchmark's repeats

    @property
    def total(self) -> int:
        return len(self.commands)


@dataclass(frozen=True)
class BoxResult:
    index: int  # 1-based, the shard number
    rc: int | None = None  # the command's exit code; None when it never ran
    tests: int = 0
    fatal: str = ""
    seconds: float = 0.0
    failed: int = 0  # failed or errored cases in its JUnit
    skipped: int = 0
    ids: frozenset[str] = frozenset()  # the cases that ran: a skipped test is not one


def estimated_usd(box_seconds: float, cpus: int) -> float:
    """A client-side ledger: it counts what this run timed, and undercounts when its client dies."""
    return round(box_seconds * cpus * VCPU_HOUR_USD / 3600, 3)


def worst_case_usd(boxes: int, cpus: int, ttl_minutes: int) -> float:
    """Every box billing to its TTL: what a run can cost if the client dies at once. Rounded past any ceiling worth setting."""
    return round(boxes * cpus * VCPU_HOUR_USD * ttl_minutes / 60, 6)


def sanitize_project(name: str) -> str:
    """What sbx accepts in a box name. Anything shorter than its two-character minimum becomes `project`."""
    clean = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_PROJECT].rstrip("-")
    return clean if len(clean) >= 2 else "project"


def box_name(request: RunRequest, index: int) -> str:
    """`<project>-<mode>-<NN>-<hash>`. The hash is why two runs never share a name: a scoped secret outlives its box,
    and the next box with that name would receive it."""
    width = max(2, len(str(request.total)))
    return f"{request.project}-{request.mode.value}-{index:0{width}d}-{request.run_id}"


def is_fleet_box(name: str, project: str) -> bool:
    modes = "|".join(mode.value for mode in Mode)
    return re.fullmatch(rf"{re.escape(project)}-(?:{modes})-\d{{2,}}-[a-z0-9]{{4}}", name) is not None


def parse_custom(service: str) -> tuple[str, str] | None:
    """`custom:<exact host>:<ENV>` -> (host, ENV); None for anything else."""
    match = re.fullmatch(r"custom:([a-z0-9-]+(?:\.[a-z0-9-]+)+):([A-Za-z_][A-Za-z0-9_]*)", service)
    return (match[1], match[2]) if match else None


def custom_name(host: str) -> str:
    return host.replace(".", "-")  # what sbx derives from the first --host


def template_problem(template: str) -> str:
    if template == "shell-docker":
        return "template shell-docker does not exist on sbx 0.51.0: use shell, which runs Docker"
    return "" if _TEMPLATE.fullmatch(template) else f"template {template!r}: use shell, or a kit reference"


def shape_problem(cpus: int, memory: str) -> str:
    match = _MEMORY.fullmatch(memory.strip())
    if SHAPES.get(cpus) is not None and match and f"{match[1]}g" == SHAPES[cpus]:
        return ""
    shapes = ", ".join(f"{count}/{gib}" for count, gib in SHAPES.items())
    return f"{cpus} vCPU with {memory} is not a billable shape: use one of {shapes}"


def _common(request: RunRequest) -> list[str]:
    found: list[str] = []
    if not _REPO.fullmatch(request.repo):
        found.append("--repo must be an https URL with no credentials: a token belongs to the sbx secret proxy")
    if request.total < 1:
        found.append("boxes must be at least 1")
    if not 0 <= request.stagger <= MAX_STAGGER_S:  # nan and 1e308 fail too: `time.sleep` would raise past the final proof
        found.append(f"stagger {request.stagger}: must be a number of seconds, from 0 to {MAX_STAGGER_S}")
    if not re.fullmatch(r"[0-9a-f]{40}", request.sha):
        found.append("--sha must resolve to a full sha")
    if any(PLACEHOLDER in command for command in request.commands):
        found.append(f"a command still holds a `{PLACEHOLDER} ...>` placeholder: write the real command first")
    if any(TERMINATOR in command for command in request.commands):
        found.append(f"a command holds the script terminator {TERMINATOR}")
    if request.total > 1 and not request.per_box and len(set(request.commands)) == 1 and "SHARD" not in request.commands[0]:
        found.append(f"{request.total} boxes would each run the whole suite: read $SHARD of $SHARDS in the command, "
                     "or pass --command once per box to repeat it")
    found += filter(None, [template_problem(request.template)])
    if request.minutes >= request.ttl_minutes:
        found.append(f"--minutes {request.minutes} must be below the TTL of {request.ttl_minutes} minutes, "
                     "or the deadline never fires")
    return found


def _capacity(request: RunRequest) -> list[str]:
    found: list[str] = []
    if request.total * request.cpus > request.quota:
        found.append(f"{request.total} boxes of {request.cpus} vCPU exceed the quota of {request.quota}; "
                     "sbx would refuse them part-way")
    worst = worst_case_usd(request.total, request.cpus, request.ttl_minutes)
    if request.max_usd is not None and worst > request.max_usd:
        found.append(f"{request.total} boxes of {request.cpus} vCPU billing to a TTL of {request.ttl_minutes} minutes can cost "
                     f"${worst:.4f}, over the ceiling of ${request.max_usd:.4f}")
    return [*found, *filter(None, [shape_problem(request.cpus, request.memory)])]


def _reading(request: RunRequest) -> list[str]:
    found: list[str] = []
    if request.labels and len(request.labels) != request.total:
        found.append(f"--label given {len(request.labels)} times for {request.total} boxes: give one per box")
    if request.expect_tests is not None and not request.require_junit:
        found.append("--expect-tests counts JUnit cases, and --no-junit reads none")
    return found


def _profile(request: RunRequest, profile: RunProfile) -> list[str]:
    level = profile.level.value
    run = f"{'an' if level[0] in 'aeiou' else 'a'} {level} run"
    secrets = (request.secret_service, *request.env_names) if request.secret_service else request.env_names
    found: list[str] = []
    if profile.secrets is SecretPolicy.NONE and (secrets or request.clone == "token"):
        found.append(f"{run} takes no secrets: run it public, or decide the commit is trusted in the adoption file")
    elif profile.secrets is SecretPolicy.CONFIGURED:
        found += [f"{name} is not in allowed_secrets in the adoption file" for name in secrets
                  if name not in request.allowed_secrets]
    if profile.max_boxes is not None and request.total > profile.max_boxes:
        found.append(f"{run} gets one box per pull request, not {request.total}")
    if profile.max_ttl_minutes is not None and request.ttl_minutes > profile.max_ttl_minutes:
        found.append(f"{run} keeps a short TTL: at most {profile.max_ttl_minutes} minutes")
    if profile.templates is TemplatePolicy.STOCK_ONLY and request.template != "shell":
        found.append(f"{run} uses the stock shell, never a kit")
    if profile.network is NetworkPolicy.DENY_BY_DEFAULT:
        if request.network_policy != "deny-all":
            found.append(f"{run} needs a deny-all account: run `sbx --cloud policy init deny-all`, "
                         "then set network_policy: deny-all in the adoption file")
        found += [f"allow {host!r}: {run} takes a named host only" for host in request.allow
                  if not _named(host)]
    return found


def _covers(pattern: str, host: str) -> bool:
    """A wildcard is read as any depth, wider than sbx's `*`: this answers "could it reach", where wider fails closed."""
    base = pattern.lstrip("*.").lower()
    return not base or host == base or (pattern.startswith("*") and host.endswith(f".{base}"))


def reaches(hosts: tuple[str, ...], allow: tuple[str, ...]) -> bool:
    """Could a secret for `hosts` be used from a box allowed `allow`? No hosts means they are unknown: yes. So is a host
    that is no plain DNS name, such as `*.corp.example.com` or `api.example.com:443`, which no exact match can place."""
    return (not hosts or any(_PLAIN_HOST.fullmatch(host) is None for host in hosts)
            or any(_covers(pattern, host.lower()) for pattern in (*DEFAULT_ALLOW, *allow) for host in hosts))


def _one_box(scope: str, live: frozenset[str]) -> bool:
    """A scope is harmless only when it names one sandbox: a live one, or one of a fleet's, which a scoped secret outlives.
    `global`, `*`, `all-sandboxes` or a spelling not seen yet counts as every box (review 4, M1)."""
    return scope in live or _FLEET_SCOPE.fullmatch(scope) is not None


def exposed_secrets(rows: list[tuple[str, str, tuple[str, ...]]], allow: tuple[str, ...],
                    live: frozenset[str] = frozenset()) -> list[str]:
    """Names of secrets a new box could use. `rows` are (name, scope, hosts); `live` the account's box names."""
    return [name for name, scope, hosts in rows
            if not _one_box(scope, live) and reaches(hosts or SERVICE_HOSTS.get(name, ()), allow)]


def _named(host: str) -> bool:
    # shortcut: `**.co.uk` passes, for telling it from `**.example.com` needs the public suffix list; upgrade if one ships here
    return _NAMED_HOST.fullmatch(host) is not None


def open_account_hosts(allow: tuple[str, ...]) -> list[str]:
    """Entries on the account's own list that name no host: with one, a deny-all account is not deny-all."""
    return [f"the account's own allow list holds {host!r}, which names no host, so this run would not be deny-all: "
            f"`sbx --cloud policy rm network --resource {host}`, or run on another account" for host in allow if not _named(host)]


def refusals(request: RunRequest, profile: RunProfile) -> list[str]:
    """Why this request must not create a box; [] when it may."""
    found = _common(request) + _capacity(request) + _reading(request) + _profile(request, profile)
    if request.secret_service.startswith("custom:") and not parse_custom(request.secret_service):
        found.append("--secret-service custom:<exact host>:<ENV> takes one exact DNS name, with no wildcard, and a variable name")
    if request.clone == "token" and not request.secret_service:
        found.append("a token clone needs --secret-service: boxes would clone with no credentials")
    found += [f"--env {name.partition('=')[0]}: takes a variable NAME, never NAME=value" for name in request.env_names
              if not _ENV_NAME.fullmatch(name)]
    return found


# A full clone: a shallow one breaks tests that read git history. The command is written to its own file, so a syntax
# error there is an ordinary non-zero rc, and `set -u` stays out of it.
_BOX_SCRIPT = """set -u
export PATH=$HOME/.local/bin:$PATH CI=true SHARD=@INDEX@ SHARDS=@TOTAL@
export OUT=$HOME/out; rm -rf $OUT; mkdir -p $OUT; cd $HOME
@ENVCHECK@git clone -q @REPO@ work > $OUT/clone.log 2>&1 && cd work@FETCH@ \\
  && git checkout -q @SHA@ >> $OUT/clone.log 2>&1 || echo clone-failed >> $OUT/fatal
if [ ! -f $OUT/fatal ]; then
  cat > $HOME/cmd.sh <<'@TERMINATOR@'
@COMMAND@
@TERMINATOR@
  bash $HOME/cmd.sh > $OUT/run.log 2>&1; echo $? > $OUT/rc
fi
tar -czf $HOME/out.tgz -C $HOME out; touch $HOME/out.done
"""


def box_script(request: RunRequest, index: int) -> str:
    check = "".join(f'[ -n "$(printenv "{name}")" ] || echo "env {name} is empty in the box" >> $OUT/fatal\n'
                    for name in request.env_names)
    fetch = f" && git fetch -q origin pull/{request.pull}/head" if request.pull is not None else ""
    values = {"REPO": shlex.quote(request.repo), "SHA": request.sha, "COMMAND": request.commands[index - 1], "INDEX": str(index),
              "TOTAL": str(request.total), "ENVCHECK": check, "FETCH": fetch, "TERMINATOR": TERMINATOR}
    return re.sub(r"@([A-Z]+)@", lambda match: values[match[1]], _BOX_SCRIPT)


def _problem(result: BoxResult, total: int, require_junit: bool) -> list[str]:
    label = f"box {result.index}/{total}"
    if result.fatal:
        return [f"{label}: {result.fatal}"]
    if result.rc is None:
        return [f"{label} returned no result"]
    if result.rc != 0:
        return [f"{label} exited {result.rc}"]
    if not require_junit:
        return []
    if not result.tests:
        return [f"{label} wrote no JUnit XML to $OUT"]
    if result.failed:
        return [f"{label} exited 0 with {result.failed} failed or errored tests in its JUnit: the command masks its exit code"]
    return [f"{label}: all {result.tests} tests were skipped, so nothing was tested"] if result.skipped == result.tests else []


def verdict(results: list[BoxResult], total: int, require_junit: bool) -> list[str]:
    """Why the run is red; [] only when all `total` boxes reported, exited 0 and (when required) reported tests."""
    by_index = {result.index: result for result in results}
    lines: list[str] = []
    for index in range(1, total + 1):
        lines += _problem(by_index.get(index, BoxResult(index)), total, require_junit)
    return lines


def ran_tests(results: list[BoxResult], commands: tuple[str, ...]) -> int:
    """Tests that ran. Boxes sharing a command that reads $SHARD are shards of one suite, so the same test twice is one test.
    Every other box adds up: one gate may run on two servers, or one benchmark three times, and every run counts."""
    seen: dict[str | int, set[str]] = {}
    for result in results:
        command = commands[result.index - 1]
        seen.setdefault(command if "SHARD" in command else result.index, set()).update(result.ids)
    return sum(len(ids) for ids in seen.values())


def counts(results: list[BoxResult], expected: int, commands: tuple[str, ...]) -> tuple[int, int, int]:
    """(ran, skipped, lost). Lost is what neither ran nor was skipped, so a skip is never called lost. Skips are summed, not
    deduplicated: an overlap can only shrink `lost`, and the run is red anyway while fewer ran than expected."""
    ran, skipped = ran_tests(results, commands), sum(result.skipped for result in results)
    return ran, skipped, max(0, expected - ran - skipped)


def count_problem(results: list[BoxResult], expected: int | None, commands: tuple[str, ...]) -> str:
    if expected is None:
        return ""
    ran, skipped, lost = counts(results, expected, commands)
    if ran == expected:
        return ""
    if ran > expected:
        return f"expected {expected} tests to run, {ran} ran: more ran than the suite holds"
    why = (f"{lost} tests were lost" if lost else
           f"none was lost, and a skipped test is not one that ran: give --expect-tests {ran} if the skips are meant")
    return f"expected {expected} tests to run: {ran} ran, {skipped} skipped, {lost} lost; {why}"


def completeness(results: list[BoxResult], expected: int | None, commands: tuple[str, ...]) -> tuple[bool | None, str]:
    """(complete, a line saying so): what a gate that is red by design has instead of an exit code. None: nothing to prove it by."""
    tests = ran_tests(results, commands)
    left = [str(result.index) for result in results if result.rc is None or result.fatal]
    ran, skipped, lost = counts(results, expected or 0, commands)
    count = f"{ran} of {expected} expected tests ran, {skipped} skipped, {lost} lost"
    if left:
        return False, f"INCOMPLETE: box {', '.join(left)} did not finish" + (f", {count}" if expected is not None else "")
    if expected is None:
        return None, "every box finished; no expected count was given, so a command that died early reads the same: --expect-tests"
    return (True, f"complete: every box finished, {count}") if tests == expected else (False, f"INCOMPLETE: {count}")


def exit_code(results: list[BoxResult], total: int, require_junit: bool) -> int:
    """1 when a box that ran failed. 3 when none failed and one never ran: credit, quota or an outage says nothing of the code."""
    ran = [result for result in results if result.rc is not None or result.fatal]
    if any(_problem(result, total, require_junit) for result in ran):
        return 1
    return 0 if len(ran) == total else 3


def is_transient(stderr: str) -> bool:
    return _TRANSIENT.search(stderr) is not None


def scrub(text: str, values: tuple[str, ...]) -> str:
    """Printed sbx output never carries a value this run handed to a box. Scrub before cutting: a cut hides a token."""
    for value in filter(None, values):
        text = text.replace(value, "***")
    return text


def as_data(text: str) -> str:
    """Text an untrusted box wrote, made safe to print: one line, printable, short, and labelled as data. The prefix stops
    `::` commands; the runner's older `##[` form is found anywhere in a line, so it is broken up (review 4, M3)."""
    return "[box output, data only] " + _V1_COMMAND.sub("#[", _CONTROL.sub(" ", text).strip()[:200])
