"""Run a fleet: one thread per box, a stop that works on Windows, and proof at the end that nothing is left billing."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace

from ..domain.fleet import (
    BOX_HOME,
    VCPU_HOUR_USD,
    BoxResult,
    RunRequest,
    as_data,
    box_name,
    box_script,
    completeness,
    count_problem,
    counts,
    estimated_usd,
    exit_code,
    exposed_secrets,
    is_fleet_box,
    is_transient,
    open_account_hosts,
    ran_tests,
    scrub,
    verdict,
)
from ..domain.known_errors import anchor_for
from ..domain.profile import NetworkPolicy, OutputPolicy, RunProfile, SecretPolicy
from ..domain.trust import TrustVerdict
from ..ports import AccountPolicy, BoxRow, Clock, CommandTimeout, Done, RunFiles, SandboxRuntime, SecretRow, SecretStore, Unreadable

POLL_S = 2
CREATE_ATTEMPTS = 5
RM_ATTEMPTS = 3
LATE_CHECKS = 3  # a create whose client gave up can still finish (FINDINGS 8.2): look again before leaving
LATE_WAIT_S = 20
WAIT_S = 1  # the main thread must wake to take a signal: Windows does not interrupt a lock wait


@dataclass(frozen=True)
class ScopedSecret:
    service: str
    value: str = field(repr=False)


@dataclass(frozen=True)
class Edge:
    runtime: SandboxRuntime
    secrets: SecretStore
    files: RunFiles
    clock: Clock
    out: Callable[[str], None]


class _Run:
    def __init__(self, request: RunRequest, profile: RunProfile, edge: Edge, secret: ScopedSecret | None,
                 env_values: tuple[str, ...], stop: threading.Event) -> None:
        self.request, self.profile, self.edge, self.secret, self.stop = request, profile, edge, secret, stop
        self.hidden = (secret.value if secret else "", *env_values)
        self.names = [box_name(request, index) for index in range(1, request.total + 1)]
        self.deadline = edge.clock.now() + request.minutes * 60
        self.late = threading.Event()
        self.unsure: set[str] = set()  # boxes whose create never answered 0: it can still finish (FINDINGS 8.2), and nobody saw them

    def tell(self, line: str) -> None:
        self.edge.out(line)

    def label(self, index: int) -> str:
        return self.request.labels[index - 1] if self.request.labels else ""

    def _announce(self, index: int, name: str) -> None:
        """A live read has no effect on the run, and is how a wrong gate shows itself at minute 2. Never an untrusted box's text."""
        label = self.label(index)
        read = f": read it live with sbx --cloud exec {name} bash -c 'tail -n 20 ~/out/run.log'"
        self.tell(f"box {index}/{self.request.total}{f' ({label})' if label else ''}: {name}"
                  + (read if self.profile.output is OutputPolicy.EVERYTHING else ""))

    def _failure(self, what: str, err: str) -> None:
        tail = scrub(err, self.hidden).strip()[-300:]  # scrub first: a cut through a token hides it from the scrub
        anchor = anchor_for(err)
        self.tell(f"{what}: {tail}" + (f" (see {anchor})" if anchor else ""))

    def _create(self, name: str) -> Done:
        done = Done(1)
        for attempt in range(CREATE_ATTEMPTS):
            done = self.edge.runtime.create(name, self.request)
            if done.rc == 0 or not is_transient(done.err):
                break
            self.edge.clock.sleep(2 + 3 * attempt)
        return done

    def _wait_done(self, name: str) -> str:
        """'' when the box finished; otherwise why not."""
        runtime, clock = self.edge.runtime, self.edge.clock
        while clock.now() < self.deadline:
            try:
                rc = runtime.run(name, "test", "-f", f"{BOX_HOME}/out.done", timeout=60).rc
                if rc == 0:
                    return ""
                if rc == 125:
                    return "the box is gone"
            except CommandTimeout:
                pass
            if self.stop.is_set():
                return "interrupted"
            clock.sleep(POLL_S)
        runtime.run(name, "bash", "-c", "tar -czf ~/out.tgz -C ~ out", timeout=120)  # partial results still help
        return "did not finish before the deadline"

    def _read(self, index: int, name: str, fatal: str, seconds: float) -> BoxResult:
        files = self.edge.files
        if self.edge.runtime.download(name, f"{BOX_HOME}/out.tgz", files.archive(name)).rc != 0:
            return BoxResult(index, fatal=fatal or "failed to copy the result", seconds=seconds)
        read = files.read_result(index, name, seconds, self.profile.output)
        missing = "" if read.rc is not None else "the box returned no exit code"  # it ran, so this is red, not a box that never started
        text = scrub(fatal or read.fatal or missing, self.hidden)  # scrub first: a box can print a value it was handed
        shown = as_data(text) if text and self.profile.output is OutputPolicy.RESULTS_ONLY else text
        return replace(read, fatal=shown, seconds=seconds)

    def _start(self, index: int, name: str) -> str:
        """'' once the box is running its script; otherwise why not."""
        runtime = self.edge.runtime
        path = self.edge.files.write_script(name, box_script(self.request, index))
        if runtime.upload(path, name, f"{BOX_HOME}/box.sh").rc != 0:
            return "failed to upload the box script"
        launch = "nohup bash ~/box.sh > ~/box.out 2>&1 & disown"  # the CLI has no detached exec
        return "" if runtime.run(name, "bash", "-c", launch).rc == 0 else "failed to start the box script"

    def _prepare(self, index: int, name: str) -> bool:
        """Secret, then box: a box never sees a secret added later. False when no box exists: no verdict, not red."""
        if self.secret:
            done = self.edge.secrets.set_scoped(name, self.secret.service, self.secret.value)
            if done.rc != 0:
                self._failure(f"box {index}: secret not set", done.err)
                return False
        try:
            created = self._create(name)
        except CommandTimeout:
            created = None
        if created is None or created.rc != 0:  # a killed client exits non-zero, and the server may finish its create anyway
            self.late.set()
            self.unsure.add(name)
        if created is None:
            self.tell(f"box {index}: create timed out; it may still finish, so this run looks again before leaving")
            return False
        if created.rc != 0:
            self._failure(f"box {index}: create failed", created.err)
        return created.rc == 0

    def box(self, index: int) -> BoxResult:
        request, clock, name = self.request, self.edge.clock, self.names[index - 1]
        began = clock.now()
        if index > 1 and request.stagger:
            clock.sleep(request.stagger * (index - 1))
        if self.stop.is_set():
            return BoxResult(index, fatal="interrupted")
        try:
            if not self._prepare(index, name):
                return BoxResult(index)
            self._announce(index, name)
            problem = self._start(index, name)
            if problem:
                return BoxResult(index, fatal=problem)
            fatal = self._wait_done(name)
            if fatal in ("interrupted", "the box is gone"):
                return BoxResult(index, fatal=fatal, seconds=clock.now() - began)
            return self._read(index, name, fatal, clock.now() - began)
        except CommandTimeout:
            return BoxResult(index, fatal="sandbox command timed out")
        except Exception as exc:  # a full disk or a bad archive is this box's red: it must not skip the final proof
            return BoxResult(index, fatal=scrub(f"failed on the host: {type(exc).__name__}: {exc}", self.hidden))
        finally:
            self._remove(name)  # a create that failed or timed out may still have made a billing box

    def _remove(self, name: str) -> None:
        """Both, always: `rm` leaves a cloud scoped secret behind, and a box with that name would receive it."""
        try:
            self.edge.runtime.remove(name)
            if self.secret:
                self.edge.secrets.remove_scoped(name, self.secret.service)
        except CommandTimeout:
            pass  # the final check finds what this left
        except Exception as exc:  # the same: the final check must still run
            self.tell(f"fleet: removing {name}: {type(exc).__name__}; the final check looks again")

    def _still_here(self) -> tuple[list[str], list[SecretRow]]:
        boxes, secrets = _account(self.edge)
        return [row.name for row in boxes if row.name in self.names], [row for row in secrets if row.scope in self.names]

    def confirm_gone(self) -> list[str]:
        """`rm` exits 0 while a removal is still completing, and a timed-out create can finish later: look, retry, say."""
        left: list[str] = []
        for attempt in range(RM_ATTEMPTS + (LATE_CHECKS if self.late.is_set() else 0)):
            try:
                boxes, secrets = self._still_here()
                for name in boxes:
                    self._remove(name)
                    self.unsure.discard(name)
                for row in secrets:
                    self.edge.secrets.remove_scoped(row.scope, row.name)
                boxes, secrets = self._still_here()
            except (Unreadable, CommandTimeout) as exc:
                self.tell(f"fleet: could not confirm the boxes are gone ({exc}): run `sbx --cloud ls`")
                return [*self.names]
            left = [*boxes, *(f"secret {row.name} of {row.scope}" for row in secrets)]
            if not left and not (self.late.is_set() and attempt < LATE_CHECKS - 1):
                return []
            self.edge.clock.sleep(LATE_WAIT_S)
        return left


def _account(edge: Edge) -> tuple[list[BoxRow], list[SecretRow]]:
    return edge.runtime.boxes(), edge.secrets.secrets()


def _collisions(request: RunRequest, boxes: list[BoxRow], secrets: list[SecretRow]) -> list[str]:
    """A low chance of a repeated hash is still a secret leak: a scoped secret outlives its box."""
    names = {box_name(request, index) for index in range(1, request.total + 1)}
    found = [f"a live box is already named {row.name}" for row in boxes if row.name in names]
    return found + [f"leftover secret {row.name} is scoped to {row.scope}: run --sweep-only"
                    for row in secrets if row.scope in names]


def exposure(rows: list[SecretRow], allow: tuple[str, ...], boxes: list[BoxRow]) -> list[str]:
    """Why a run that may hold no secret must not start on this account. The proxy injects a global secret into any box."""
    held = exposed_secrets([(row.name, row.scope, row.hosts) for row in rows], allow, frozenset(row.name for row in boxes))
    return [f"global secret {name} can reach a host this box may reach, so its code could act as that identity: remove it "
            f"(`sbx --cloud secret rm {name}`), or run on an account that holds none" for name in held]


def _gather(run: _Run) -> list[BoxResult]:
    total = run.request.total
    with ThreadPoolExecutor(max_workers=total) as pool:
        futures: list[Future[BoxResult]] = [pool.submit(run.box, index) for index in range(1, total + 1)]
        pending = set(futures)
        while pending:
            try:
                pending = wait(pending, timeout=WAIT_S).not_done
            except KeyboardInterrupt:
                run.stop.set()  # each box thread sees it within POLL_S and removes its box; a create in flight finishes
                run.tell("fleet: stopping; removing the boxes")
    return [future.result() for future in futures]


def _report(run: _Run, results: list[BoxResult], lines: list[str], code: int) -> None:
    if code == 3:
        ran = sum(1 for result in results if result.rc is not None)
        run.tell(f"fleet: NO VERDICT, {ran} of {run.request.total} boxes ran and none failed; the rest never started "
                 "(credit, vCPU quota or an outage). Use CI; never retry in a loop.")
        return
    for line in lines:
        run.tell(line)
    request = run.request
    for result in sorted(results, key=lambda r: r.index):
        label = run.label(result.index)
        tests = f"{result.tests} tests" if request.require_junit else "tests n/a"
        skipped = f", {result.skipped} skipped" if result.skipped else ""
        run.tell(f"{f'{label}, ' if label else ''}{run.names[result.index - 1]}: {result.seconds:.0f} s, {tests}{skipped}, rc {result.rc}")
    seconds = sum(r.seconds for r in results)
    run.tell(f"total: {seconds:.0f} box-seconds, about ${estimated_usd(seconds, request.cpus):.3f} at ${VCPU_HOUR_USD} a vCPU-hour, "
             "the rate of October 2026")
    run.tell(f"fleet: {completeness(results, request.expect_tests, request.commands)[1]}")
    means = f"{'; green would have meant' if code else ', which here means'}: {request.means}" if request.means else ""
    run.tell(f"fleet: {'RED' if code else 'GREEN'}{means}")


def _settle(run: _Run) -> list[str]:
    """A signal here must not skip the proof that nothing is left: look again, once."""
    try:
        return run.confirm_gone()
    except KeyboardInterrupt:
        run.stop.set()
        return run.confirm_gone()


def _left_line(name: str) -> str:
    if name.startswith("secret "):
        return f"fleet: left behind: {name}, a live credential with no expiry: run --sweep-only"
    return f"fleet: left behind: {name}. It bills to its TTL: run --sweep-only"


def _possibly_line(name: str, project: str) -> str:
    return (f"fleet: possibly left behind: {name}. Its create was cut off and can still finish, billing to its TTL. "
            f"Check with `sbx --cloud ls`, and remove it with `sbx_fleet.py --project {project} --sweep-only`")


def run_fleet(request: RunRequest, profile: RunProfile, trust: TrustVerdict, edge: Edge, secret: ScopedSecret | None = None,
              env_values: tuple[str, ...] = (), stop: threading.Event | None = None) -> int:
    stop = stop or threading.Event()
    denied = profile.network is NetworkPolicy.DENY_BY_DEFAULT
    try:
        policy = edge.runtime.account_policy() if denied else AccountPolicy("")
        if denied and policy.mode != "deny-all":
            edge.out(f"fleet: refused before any box was created: the account's network default is {policy.mode}, "
                     f"and a {profile.level.value} run needs deny-all (`sbx --cloud policy init deny-all`)")
            return 2
        boxes, secrets = _account(edge)
    except (Unreadable, CommandTimeout) as exc:
        anchor = anchor_for(str(exc))
        edge.out(f"fleet: NO VERDICT, cannot read the account: {exc}" + (f" (see {anchor})" if anchor else ""))
        return 3
    found = _collisions(request, boxes, secrets) + open_account_hosts(policy.allow)
    if profile.secrets is SecretPolicy.NONE:
        found += exposure(secrets, (*request.allow, *policy.allow), boxes)
    if found:
        edge.out(f"fleet: level {profile.level.value} ({trust.rule}): refused before any box was created")
        edge.out("\n".join(f"fleet: {line}" for line in found))
        return 2
    run = _Run(request, profile, edge, secret, env_values, stop)
    edge.out(f"fleet: {request.total} box(es) on {request.sha}, level {profile.level.value} ({trust.rule})")
    results = _gather(run)
    left = _settle(run)
    possibly = sorted(run.unsure - set(left))
    short = count_problem(results, request.expect_tests, request.commands)
    lines = verdict(results, request.total, request.require_junit) + ([short] if short else [])
    code = 130 if stop.is_set() else exit_code(results, request.total, request.require_junit)
    code = 1 if left and code == 0 else code  # a box or a credential left behind is never green
    code = 1 if short and code == 0 else code
    seconds = sum(r.seconds for r in results)
    try:  # a disk a box filled must not skip the left-behind lines below, and is never green
        edge.files.write_verdict({"sha": request.sha, "exit": code, "ok": code == 0, "lines": lines, "level": profile.level.value,
                                  "rule": trust.rule, "evidence": trust.evidence, "left_behind": left,
                                  "possibly_left_behind": possibly, "box_seconds": seconds,
                                  "estimated_usd": estimated_usd(seconds, request.cpus), "means": request.means,
                                  "complete": completeness(results, request.expect_tests, request.commands)[0],
                                  "expect_tests": request.expect_tests, "tests": sum(r.tests for r in results),
                                  "ran": ran_tests(results, request.commands), "skipped": sum(r.skipped for r in results),
                                  "lost": counts(results, request.expect_tests, request.commands)[2]
                                  if request.expect_tests is not None else None,
                                  "boxes": [{"name": run.names[r.index - 1], "label": run.label(r.index), "rc": r.rc,
                                             "tests": r.tests, "skipped": r.skipped, "failed": r.failed, "seconds": r.seconds}
                                            for r in results]})
    except OSError as exc:
        edge.out(f"fleet: could not write verdict.json: {exc}")
        code = code or 1
    for name in left:
        edge.out(_left_line(name))
    for name in possibly:
        edge.out(_possibly_line(name, request.project))
    edge.out("fleet: see for yourself with `sbx --cloud ls` and `sbx --cloud secret ls`: `sbx ls` shows no cloud box")
    if code == 130:
        edge.out("fleet: stopped; every box was removed" if not (left or possibly) else "fleet: stopped, with boxes left behind")
        return code
    _report(run, results, lines, code)
    return code


def _sweep_box(name: str, edge: Edge) -> bool:
    edge.out(f"fleet: removing {name}")
    return edge.runtime.remove(name).rc == 0


def sweep(project: str, edge: Edge) -> int:
    """Remove this project's fleet boxes and every secret scoped to a fleet name: `rm` alone leaves the secret."""
    try:
        boxes, secrets = _account(edge)
        ok = [_sweep_box(row.name, edge) for row in boxes if is_fleet_box(row.name, project)]
        ok += [edge.secrets.remove_scoped(row.scope, row.name).rc == 0 for row in secrets if is_fleet_box(row.scope, project)]
        boxes, secrets = _account(edge)
        left = [row.name for row in boxes if is_fleet_box(row.name, project)]
        left += [f"secret {row.name} of {row.scope}" for row in secrets if is_fleet_box(row.scope, project)]
    except (Unreadable, CommandTimeout) as exc:
        edge.out(f"fleet: cannot read the account: {exc}")
        return 3
    for name in left:
        edge.out(f"fleet: left behind: {name}")
    edge.out(f"fleet: swept {len(ok)} item(s)")
    return 1 if left or not all(ok) else 0
