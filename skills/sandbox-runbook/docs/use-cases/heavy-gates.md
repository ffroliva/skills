---
type: Knowledge
title: Heavy gates
description: Corpus and mutation gates in boxes, split by resource, including gates that are red by design. Tried once.
tags: [sbx, use-case, mutation, gates]
status: stable
date: 2026-11-05
state: tried-once
trust: trusted
source: measured on a target project, not independently reproducible, one run, sbx 0.51.0
---

# Heavy gates

**Tried once.** Measured on a target project, not independently reproducible: one run of each row, sbx 0.51.0, 2026-11-05.

| Gate | Shape | Result |
|---|---|---|
| A live oracle against four database servers, plus planted faults: 21,859 tests | 2 fleets, 6 boxes of 8 vCPU, serial | 8 min 52 s wall (342 s + 190 s), 1,302 box-seconds, about $0.20 |
| A gate run twice, a mutation list, a planted fault | 1 fleet, 4 boxes of 8 vCPU | 115 s wall, 246 box-seconds, about $0.04. The gate boxes took 47 s each, the mutants 46 s |
| That day's whole ledger: six fleets, one of them stopped and one invalid | 13 boxes | 2,186 box-seconds, $0.34 by ledger. No create refused, no 429, no Docker Hub 5xx, no out-of-memory, TTL never reached |

The dollars are a ledger at $0.56 an hour for 8 vCPU, not a bill. On CI the same gate was cancelled at 2 h 38 min with no verdict, because of a defect in the project that a first box showed at minute 2 ([count container starts](testcontainers.md#count-container-starts)), so that is no speed comparison. Fuzzing is still an untested idea here: no fuzz run was measured.

## How

1. **One box first.** Run a small part, read it live, and size from it. That first box cost $0.07 and found a wrong gate. It also showed a row took 32 ms, where the plan had assumed 70 ms, so one later fleet was not needed.
2. **Split by resource, and prove the partition.** `sbx_shard.py` splits by file and weight, which does nothing for one file over fixed servers. Select by server, then run `--collect-only -q` on each selection, locally: the counts must sum to the whole file (5,691 + 5,226 + 7,864 + 3,074 + 4 plants here). pytest's `-k` ignores case, so a word can select a leg of every server.
3. **One command per box.** Give each a `--label`, and the run `--expect-tests <the sum>`. It counts tests that ran, not skipped ones, and boxes with their own commands add up, so one test on two servers counts twice; boxes that share a command are shards, where it counts once. A label is a name in the output and in `verdict.json`; it never reaches a box name, which `--sweep-only` parses.
4. **Rehearse.** Collect on an export of the same sha before spending a box: a helper the project refuses at collection lost one box's result here.

A command can be many lines. The fleet writes it to a file in the box through a quoted heredoc, so it runs as written, with `$OUT`, `$SHARD` and `$SHARDS` set. The one thing it may not hold, anywhere in it, is the terminator `SBX_COMMAND_END`, which the fleet refuses. `bash` runs it with no `-e`, so start with what you need.

```bash
# gates/postgres.sh
set -euo pipefail
uv sync --locked --python 3.14
docker run -d --name db -e POSTGRES_HOST_AUTH_METHOD=trust -p 5432:5432 postgres:17-alpine
PYTHONUNBUFFERED=1 uv run pytest -v -n 0 -k postgres --junitxml=$OUT/junit.xml 2>&1 | tee $OUT/progress.log
```

```bash
python <skill>/scripts/sbx_fleet.py --config docs/sbx.md --repo <url> --sha <sha> --out <empty-dir> --expect-tests 8765 \
  --label postgres --command "$(cat gates/postgres.sh)" \
  --label mysql --command "$(cat gates/mysql.sh)"
```

## Reading the verdict

- **Red by design.** When the list of failures is the product, the exit code is 1 whichever way the run went. Read the line above the verdict: `complete: every box finished, 21859 of 21859 expected tests ran, 0 skipped, 0 lost`, or `INCOMPLETE`, which is a run that died or skipped what you expected to run. Lost counts what neither ran nor was skipped, so skips are never called lost. `verdict.json` holds `complete`, `tests`, `expect_tests`, `ran`, `skipped`, `lost` and one row per box. With no `--expect-tests`, `complete` is null: a command that died early with an exit code looks the same as one that finished.
- **An inverted gate.** On a planted fault a test passes when the gate failed on the plant, so green means the opposite of what it reads. Say what green means before running: `--means "each plant was caught"` prints it beside the verdict and keeps it in `verdict.json`.
- **rc-judged boxes.** `--no-junit` is per fleet, and a box then prints `tests n/a`. It cannot be combined with `--expect-tests`.

## Deadlines and shapes

- A JUnit file written at session end is lost at the `--minutes` deadline. A run killed there returns what it already wrote to `$OUT`: keep a per-test log, as above. `SIGINT` is ignored by a background job in the box, so `timeout -s INT` would not save JUnit either.
- A serial run (`-n 0`) sized by vCPU leaves most of the box idle: [shape it by memory](../reference/sizing.md#serial-runs).
- One small public helper file that is not in the repository: put it in `--command` as base64, and see [getting code in](../pitfalls/getting-code-in.md).

Keep this as an extra check, not a required gate: one run is no basis for that.
