---
type: Knowledge
title: Live-database tests with Testcontainers
description: Docker inside a cloud box, so tests can start real databases. Measured on sbx 0.50.1; one real PostgreSQL run on 0.51.0.
tags: [sbx, use-case, testcontainers, docker]
status: stable
date: 2026-11-05
state: measured
state_note: measured on 0.50.1, tried once on 0.51.0
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L346
---

# Live-database tests with Testcontainers

Measured on sbx 0.50.1: Testcontainers worked unchanged in a box. **On sbx 0.51.0 it ran once** (gate 9, 2026-11-05): a Testcontainers PostgreSQL test passed in a box through `sbx_fleet.py`, see [below](#testcontainers-on-sbx-0510). Python, 3,642 integration tests
on PostgreSQL, one container per worker, are part of the suite in the [19-run series](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478).

**Needs:** `template: shell`, `**.docker.com` and `**.docker.io`, one worker per vCPU, one database per worker.

**Sizing:** [about 1.1 GiB per worker](../reference/sizing.md); memory runs out before CPU.

## Count container starts

"Containers start" is not enough, because a gate can want thousands of them. Measured on a target project, not independently reproducible, one run, sbx 0.51.0: the box was fine (sync 1 s, pulls 8 s, 0.7 of 16 GiB), and the gate was not. A `scope="session"` fixture, parametrized with mixed direct and indirect arguments, runs at function scope: pytest's parametrize scope overrides the fixture's. So it started a new container per row, and 252 of 256 PostgreSQL rows reported nothing real, on a dead port. SQLite has no container, which is why an offline run never showed it. It is also why that gate's CI job was cancelled at 2 h 38 min: thousands of containers in series.

Before the whole gate, run a few tests and count:

- `docker ps` in a [live read](../pitfalls/lifecycle-billing.md): Up time must grow. "Up Less than a second" at every sample is this defect. This is how it was found, at minute 2, for $0.07.
- Starts in the run, as a line in the command: `docker events --filter event=start --format '{{.Time}} {{.Actor.Attributes.name}}' > $OUT/docker-starts.log &`, then compare the count with your plan. Proposed from that run, not yet run in a box.

The full gate then ran with one server per box through `docker run` and the project's URL route, not through Testcontainers: 21,855 tests on 4 boxes, in [heavy gates](heavy-gates.md).

**Timeouts:** pytest-timeout counts fixture setup by default, so a container's boot under a per-test timeout fails the first row, and a session fixture then caches that error for every row. `-o timeout_func_only=true` leaves each test's limit as it is. Read from pytest-timeout, not measured in a box.

**A multi-line setup** goes in `--command` as written: [worked example](heavy-gates.md#how).

**Pitfalls:**

- [`*.docker.com` is not enough](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L439): blobs come from a host two labels deep.
- Pre-pull with retries, including the reaper image. Measured on a target project, not independently reproducible.
- Local trust auth in test containers saved the most wall of any single fix: 621 s to 521 s, one run each ([the fleet
  case, L110](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L110)).

Java with Testcontainers in a box is an untested idea here: a Java suite ran in a box, without containers.

## Docker in a box on sbx 0.51.0

Measured on a target project, not independently reproducible (sbx 0.51.0, 2 boxes, one run): the plain `shell` box has the Docker CLI 29.9.3 and a running daemon, `docker run --rm hello-world` printed
`Hello from Docker!` with `--allow-network '**.docker.com' --allow-network '**.docker.io'`, and it ships uv 0.13.7 and
Python 3.14.10 on Docker Hardened Images (Debian) 13.

Use `shell`, never `shell-docker`. `shell-docker` was the route on 0.50.1, and some older notes still name it, and it is not a working route on 0.51.0: [as an agent](../troubleshooting.md#shell-docker-unknown-agent), [as a
template](../troubleshooting.md#shell-docker-unknown-template), and [as a kit](../troubleshooting.md#kit-pull-limit) all fail.

## Testcontainers on sbx 0.51.0

Tried once (gate 9, 2026-11-05, one 4 vCPU / 8 GiB `shell` box, `sbx_fleet.py` on a public project's commit). The command pre-pulled
`postgres:17-alpine` and the Ryuk image with the retry loop from the [recipe](../../templates/python.md), then ran one pytest test
with `testcontainers` and `pg8000` from `uv run --with`: start PostgreSQL, create a table, insert two rows, `sum(x) = 42`.
Result: 1 passed, `PostgreSQL 17.11 on x86_64-pc-linux-musl`, rc 0, 28 s from create to removal, nothing left on the account.
Allowed hosts: `pypi.org`, `files.pythonhosted.org`, `astral.sh`, `**.astral.sh`, `**.docker.com`, `**.docker.io`, plus the
fleet's `github.com` and `**.githubusercontent.com`. Not measured: more than one container, more than one worker, Java.

Example for a single PostgreSQL test (adjust the selection and configured egress hosts):

```sh
python <dir>/scripts/sbx_fleet.py --config docs/sbx.md --repo <url> --sha <sha> \
  --command 'uv run --with testcontainers --with pg8000 pytest -q tests/test_postgres.py' \
  --boxes 1 --cpus 4 --memory 8g
```

The measured run covered one test and one PostgreSQL container. An 87-test suite, more containers, or multiple workers exceed
that evidence; measure container starts and memory on a small selection before scaling.
