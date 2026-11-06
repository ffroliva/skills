---
type: Knowledge
title: Targeted tests
description: Run a selected set of tests in one box for a quick answer, keeping the interactive loop fast.
tags: [sbx, use-case, tests, fleet]
status: stable
date: 2026-11-05
state: tried-once
state_note: tried three times on 0.51.0
trust: trusted
source: https://github.com/ffroliva/sharpit/tree/e1e5f7e33535e25bb0fd11abc0011d46c4e71abb
---

# Targeted tests

The purpose of the testing fleet is to keep the interactive loop fast by moving test time off the laptop. This mode runs
only what you just touched, in one box or a few, and hands the terminal back.

**State:** tried once on sbx 0.51.0 (gate 4, 2026-11-05). `tests/fastapi` of a public Python project, one 4 vCPU / 8 GiB box: 451 ran plus 4 skipped (455 reported), rc 0, 60 s from create to removal, including `uv sync`. The same subset ran locally, green: 451 passed, 4 skipped. Run twice more on 2026-11-06 (sbx 0.51.0), the last on the round 6 tree with `--expect-tests 451`: 451 ran plus 4 skipped, rc 0, `complete: true`. `--expect-tests` counts tests that ran: skips are not counted (passing `--expect-tests 455` gave red "tests were lost" where the 4 were skips). Whether it beats a local run depends on your create and clone time, so measure yours.

**Do:** `sbx_fleet.py --config docs/sbx.md --repo <url> --sha <pushed-sha> --command "<runner> <selection>" --boxes 1 --expect-tests <ran-count>`. Note that `--expect-tests` counts tests that ran: skips are not counted. Commit and
push first: a box sees only the pushed commit.

**Do not:** treat a targeted run as the verdict. The [full suite](full-suite-offload.md) is.
