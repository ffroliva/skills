---
type: Knowledge
title: Test optimisation and flaky hunting
description: Rank a suite's slow files, change one thing, and measure it in boxes before CI does. Flaky hunting is untested.
tags: [sbx, use-case, tests, speed]
status: stable
date: 2026-11-06
state: tried-once
state_note: measured once on a target project, 0.51.0; CI not measured
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L348
---

# Test optimisation and flaky hunting

**A project's speed tool removes a cost. The fleet moves it, and measures it.** Two jobs, two tools.

| Job | Who does it | What it shows |
|---|---|---|
| Remove a test's cost: a slow fixture, repeated setup, a sleep | your project's speed tool, on the tests themselves | a test that costs less wherever it runs |
| Move the cost off the laptop, and measure a change | the fleet | the same work elsewhere, and a before and after on equal boxes |

A suite that got faster because the fleet grew has not been optimised. CI stays the final measure of whether a change made
the suite cheaper, and of whether every test still ran.

**State: measured once on a target project, and CI's confirmation is not measured.** Python, sbx 0.51.0, 2026-11-06. One
file, `test_red_check.py`, ran 22 nested pytest runs that each loaded seven plugins they never used. One change: 34.4 s to
22.2 s, the median of 12 runs a side (3 boxes of 4 vCPU, 4 ABBA rounds each), spread 34.1 to 35.4 s against 22.0 to 22.5 s,
every change run under every base run. Three fleets, 9 boxes, about $0.17 by the fleet's ledger. Box seconds ran 1.4 to 1.6
times CI's on the same files, so 12 s is a box figure: expect less on CI, which was not run.

## Steps

1. **Rank.** Use your speed tool on JUnit: from CI if CI has the run, else from one fleet run of the whole suite. A box ranks
   the same top files as CI, at 1.4 to 1.6 times the seconds, and one file can differ for a reason in the box (it went
   [red early there](../troubleshooting.md#red-in-box-green-on-ci)). Take order from a box, seconds from CI. `sbx_shard.py plan`
   is for balancing shards, not ranking: it needs a green JUnit.
2. **CI shards give one folder each.** A tool that reads one folder needs each `junit.xml` copied in under its own name; a
   group column then means "which file". A file's seconds there are the sum of its test times, not wall time.
3. **Find the cause** in the slowest file, in setup, call and teardown separately. On a target project, not independently
   reproducible: 1,225 tests over 5 s carried 53% of 344 test-minutes.
4. **Change one thing, test first.** Bind the one value you check to a name: a failing assert on an expression that holds
   `os.environ` prints all of it ([entry](../troubleshooting.md#test-printed-the-environment)).
5. **Measure in boxes.** Pass the same `--command` once per box, three times or more: each box is a repeat, and
   `--expect-tests` counts every box's tests. `sbx_check.py` wants every key onboarding writes, `on_timeout: delete` included;
   an older file gets them from a rerun of `sbx_onboard.py --config <file>`.
6. **An unpushed change.** The fleet clones a commit. Push a scratch branch and pass its sha, or put the diff in the command:
   the box clones the base, copies the tree, applies the patch, and runs both (three runs, a 1.2 KB diff). The command is
   written to the run folder and sent to the box, so only a diff you would publish goes in it.
7. **Each side syncs its own dependencies.** `uv run` re-syncs and drops an extra: run `uv sync --extra test` in each tree,
   then the runs with `UV_NO_SYNC=1`.
8. **Quote the spread from the per-run reports**, not a tool's noise line: one printed `0.0s` over base runs 0.8 s apart.
   Name any difference in test count between the sides, as 21 against 22.
9. **A suite red in a box ends RED, exit 1**, even when every timing is good. Read the `complete` line and `--expect-tests`,
   and say with `--means` what the run shows. The fleet will not read an expected red as green: that is the one mistake a
   verdict exists to prevent. Or leave the box-only failures out of the run's selection.
10. **Then CI.** Push the change and compare CI's seconds for the file, before and after. Until then the gain is a box figure.

**Comparing runs:** not across a [slow window](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478). Compare the same commit twice first.

**Another project's series**, one change per pull request, one fleet run on each commit, Python, 22,000 tests: 750 s to
649 s, 621 s, 521 s. The 750 to 649 step changed no test, so it is run-to-run spread. Source: the
[fleet case, L105-L110](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L105-L110).

Faster tests lower cost; [more boxes do not](../reference/sizing.md).

**Flaky hunting: untested idea.** No evidence here. The shape would be one command per box, repeating the suspect test
on clean machines. Never retry a whole suite to turn it green.

One fix in that series was a race in a browser test's wait, so timing work can surface flakes, but that was not a hunt.
