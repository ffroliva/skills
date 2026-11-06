---
type: Knowledge
title: Full suite offload
description: Run a complete test suite on a fleet of cloud boxes from a pushed commit.
tags: [sbx, use-case, tests, fleet]
status: stable
date: 2026-11-05
state: measured
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L346
---

# Full suite offload

| Shape | Result | Repeats |
|---|---|---|
| Python, 22,438 tests, 5 x 8 vCPU | [750 s, then 521 s after four fixes](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L348), against 1 h 49 min on a laptop | one run each |
| Same suite | [19 runs](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478); same-commit pairs within 2.5% | 2 pairs, DRAFT in the source |
| Same suite after making slow tests cheaper | 293 s, 298 s. Measured on a target project, not independently reproducible | 2 runs |
| Pure Python, 7,000 tests, 5 x 8 vCPU, `shell` | [64 s, 82 s, setup 3 s](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L510) | 2 runs, DRAFT in the source |
| Public Python project, 2,490 ran plus 8 skipped, 3 x 4 vCPU, `sbx_fleet.py`, sbx 0.51.0 | 24 to 38 s per box, 465 + 551 + 1,482 reported, equal to the local count | 3 runs, the last on the round 6 tree |
| Pure Python, 6,879 tests, 5 boxes, that project's own driver, not `sbx_fleet.py`, sbx 0.51.0 | 70 s wall, 887 s CPU. Red, on 40 [failures CI does not show](../troubleshooting.md#red-in-box-green-on-ci). Measured on a target project, not independently reproducible | 1 run |

**Needs:** a pushed commit, `own_work: trusted`, the `shell` template, JUnit written to `$OUT`. A public repo needs no secret.

**Command:** `sbx_fleet.py --config docs/sbx.md --repo <url> --sha <sha> --out <empty-dir>`, then
`sbx_shard.py check --junit <dir> --expect <count>`. On Windows run it in a foreground terminal: a background stop runs
no clean-up ([entry](../troubleshooting.md#windows-background-stop)).

**Keep CI.** The fleet is the fast Linux check. CI still owns other operating systems, Python versions and coverage.
When a run could not start, exit 3 sends you back to CI.

**Rules the runner keeps:** only a pushed commit; a missing box, deadline or missing JUnit is red; no test skipped,
retried or deselected to fit a budget. A faster wrong verdict is a regression.

**Pitfalls:** [quota](../pitfalls/quota.md), [lifecycle](../pitfalls/lifecycle-billing.md),
[getting code in](../pitfalls/getting-code-in.md). Cost: [sizing](../reference/sizing.md).
