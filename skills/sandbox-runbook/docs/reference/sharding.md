---
type: Knowledge
title: Sharding
description: How to split a suite across boxes, the bounds a split must keep, and when not to shard. Language-agnostic.
tags: [sbx, sharding, tests, fleet]
status: stable
date: 2026-11-05
---

# Sharding

The slowest shard sets the wall. `sbx_shard.py` plans a split from measured JUnit, and checks any split, generated or
your own, against the bounds below. A *unit* is whatever one worker must keep together: a test file in pytest, a test
class in Surefire. Python and Java steps are in the [recipes](../../templates/python.md).

If your project already shards, keep it. Print your assignment in the same JSON and run `check`: a second filter conflicts.

## The method

Public source for the techniques below, all at one commit: [`_shard.py`](https://github.com/ffroliva/sharpit/blob/31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700/tests/_shard.py),
[`test_shard.py`](https://github.com/ffroliva/sharpit/blob/31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700/tests/test_shard.py),
[`test_ci_layout.py`](https://github.com/ffroliva/sharpit/blob/31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700/tests/test_ci_layout.py) and
[`fleet.py`](https://github.com/ffroliva/sharpit/blob/31ea6ecc2c15934fabffc6c8fbc9e80df2ffb700/scripts/ci/fleet.py).

| Technique | Why | Where |
|---|---|---|
| Weights from a real run's JUnit, per platform | a test's cost differs by platform: keep one plan per platform | `plan --junit` |
| Longest first onto the lightest shard | balances within a known bound | `plan` |
| Hash only for an unmeasured unit | a new unit never moves another | `plan` |
| A limit on unmeasured units | a blind placement can land a slow unit on a loaded shard | `check --max-unmeasured` |
| Refresh weights from a real run | weights go stale as the suite moves | rerun `plan` |
| A load ceiling per shard | the shard count is what keeps you under it; `check` names the count | `--ceiling` |
| A unit alone over the ceiling gets its own job | no shard count fixes it. Two real cases on 2026-11-05: 487 s and 386 s | `--ceiling`, `--own-job` |
| CPU-heavy units away from timing tests | a busy box fails a budget test | `--heavy`, `--timing` |
| Disjoint and complete | shards must be exactly the suite | `check --units` |
| A lost shard must fail | compare unique tests with the expected total | `check --junit --expect` |

Two more are test-fixture decisions in the target project, so they stay recipes: one database per worker, and one worker per
vCPU for database tests.

## The longest-first bound

Longest-first stays within 4/3 of the best possible split (Graham, 1969). The best
split is expensive to compute, so `check` compares against a lower bound: the largest of the heaviest unit, the mean load,
and the sum of the n-th and (n+1)-th heaviest units. That last term matters. Without it four equal units on three shards
have a floor of 1.33 units, and a load of 2, the best any split can do, reads as a breach. Random search found the two-term
form breached by up to 1.58 times; the three-term form held in 600,000 random cases, at worst 1.32 times, and a seeded property test keeps
checking it. That is evidence, not a proof. `check` skips this bound when `--heavy` and `--timing` limit placement.

## Numbers

Seen on 2026-11-05 on a public project's CI: a shard ceiling of 170 weighted seconds on Linux, 305 on Windows, and two files
at 487 s and 386 s, each moved to its own job.

Lessons measured on a target project, not independently reproducible (22,000 tests, 5 boxes of 8 vCPU, a handful of runs):
shard before importing test code, or every box pays to import what it will not run. Keep the check that a green run really
ran the suite, as a count: a green build that ran nothing is not green. Separate database and browser stages inside a box. A
file longer than a box's share sets the floor: split it rather than adding boxes. Faster tests lower both the wall and the bill;
more boxes lower only the wall.

## When not to shard

- The whole suite fits under the ceiling on one box: `plan` says so.
- One unit dominates: `plan` names it. Split that unit before adding boxes.
- Tests share a writable store across boxes: [shared storage](../pitfalls/shared-storage.md).
- During development: run the affected tests, in [one box](../use-cases/targeted-tests.md).

## What a split cannot fix

A shard count is bounded by quota. 40 vCPU allows 5 boxes of 8, or 20 of 2 ([8.5](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L410), sbx 0.50.0). More than
10 boxes is unmeasured: see [measurements still owed](evidence.md#measurements-still-owed).
