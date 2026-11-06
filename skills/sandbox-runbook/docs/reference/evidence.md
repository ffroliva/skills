---
type: Knowledge
title: Evidence and versions
description: How to read a number here, the sbx versions behind the findings, and how a new finding gets in.
tags: [sbx, evidence, versions]
status: stable
date: 2026-11-06
---

# Evidence and versions

## Labels

| Label | Means |
|---|---|
| measured | a script, and repeated runs |
| tried-once | one run; labelled one run |
| untested-idea | no evidence; not a recommendation |
| proposed | a design, never a result |
| second-hand | read from someone else's list, not run here |
| measured on a target project, not independently reproducible | a run on a project this skill was applied to: shape and repeat count given, the source is unpublished |

## Versions

Findings were measured on a Windows 11 host, in October and November 2026.

| sbx | Covers |
|---|---|
| 0.46 | early CLI friction, [findings section 4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L165) |
| 0.50.0 | everything else unless a note says otherwise |
| 0.50.1 | the scoped-secret lifecycle (8.1) and the help text quoted in these notes |
| 0.51.0 | the CLI snapshot, the help text, the two-box smoke run marked in the notes, and the gate runs below |

The release observed on 2026-11-05 was 0.51.0. Only what a note marks 0.51.0 was re-measured on it. Before relying on a finding that
would change a plan, re-run its script from [sbx-team-kit](https://github.com/ffroliva/sbx-team-kit/tree/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/tests).

The source repo's items 8.18 and 8.19 are marked DRAFT there: measured once, not yet re-checked.

macOS and Linux hosts are [not tested](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L533).
The Windows-specific findings may not apply elsewhere.

## Measured by the gate runs on 0.51.0

One run each unless stated, Windows 11 host, a public Python project (2026-11-05). The logs are kept outside this repository.

| Measured | Result |
|---|---|
| `sbx_fleet.py` end to end, targeted, 1 box | 451 ran plus 4 skipped, rc 0, 60 s, same count as the local run |
| Sharded, 3 boxes of 4 vCPU | green, 2,490 ran plus 8 skipped (465 + 551 + 1,482 reported), 26 to 35 s per box; a local run counted the same |
| A box deleted by hand mid-run | exit 1, `box 2/3: the box is gone`, and `sbx_shard.py check` said `expected 2498 unique tests, found 1947: a shard was lost` |
| CTRL_BREAK to a running fleet | exit 130, 2 boxes removed in 9 s |
| A hard kill (`taskkill /F`) | box and scoped secret stay; the box died at its 4 minute TTL; `--sweep-only` removed the secret |
| A name collision, live box and leftover secret | both refused before create, exit 2 |
| A request over `--quota`, or off a billable shape | refused before create, exit 2; sbx itself also refuses an off-shape request |
| Trust, real `gh` OAuth token | member trusted (`role:admin`), fork author `no-rule-matched`, wrong sha `sha-changed`, no token `no-token`, bad token `host-error:401`, no access `host-error:403`, a 217-file pull request `listing-incomplete` |
| Custom secret through the fleet | see [credentials](../pitfalls/credentials.md) |
| Scoped secret on running box | on sbx 0.51.0 (measured 2026-11-06, cloud, custom secret): not injected within 60 s; set before `create`, it did; restart case not measured |
| Bare `-e NAME` under `--cloud` | the variable reached the box |
| `sbx --cloud policy ls --json` | `{"mode": "deny-all", "allow_networks": [], "deny_networks": []}`; per box it lists the allow hosts |
| `sbx ls --json` output shapes | on sbx 0.51.0 (measured 2026-11-06), cloud `ls --json` is an array of rows; empty local list is `[]`; non-empty local shape still unseen |
| `kit.allowedSources` setting | on sbx 0.51.0 (verified 2026-11-06), exists with default `["docker.io/","dhi.io/"]`, env var `DOCKER_SANDBOXES_KIT_ALLOWED_SOURCES`; set and enforcement not measured |
| `--app-name` isolated daemon | on sbx 0.51.0 (measured 2026-11-06), accepted; daemon not signed in (`error: not signed in to Docker`), answers `settings` and `version`, cannot create boxes or list |
| Testcontainers PostgreSQL | see [Testcontainers](../use-cases/testcontainers.md) |

## The first real use, on 0.51.0

Measured on a target project, not independently reproducible: one run of each row, Windows 11 host, 2026-11-05. A frozen snapshot of the scripts ran, with the repository binding, JUnit outcomes and the capped archive reader in it. Each fleet below reached its verdict on real boxes, and the fleet removed every box.

| Fleet | Shape | Result |
|---|---|---|
| Stopped by hand: a downgrade nobody asked for | 1 box | 76 box-seconds, $0.012 |
| Testcontainers, PostgreSQL and SQLite | 1 box of 8 vCPU | 3,074 of 3,074 tests reported, 466 box-seconds, $0.072. PostgreSQL rows invalid: [a project defect](../use-cases/testcontainers.md#count-container-starts) |
| All base rows, one server per box | 4 boxes of 8 vCPU | 21,855 of 21,855 tests reported, 342 s wall, 960 box-seconds, $0.149 |
| Planted faults | 2 boxes of 8 vCPU | 190 s wall, 342 box-seconds, $0.053 |
| A gate twice, mutants, a planted fault | 4 boxes of 8 vCPU | 115 s wall, 246 box-seconds, $0.038 |
| An inverse planted fault | 1 box of 8 vCPU | 112 s wall, 96 box-seconds, $0.015 |
| The whole day | 13 boxes | 2,186 box-seconds, $0.34 by ledger of $0.56 an hour, no bill read. No create refused, no 429, no Docker Hub 5xx, no out-of-memory, no TTL reached |

Another project's own fleet driver, not `sbx_fleet.py`, ran 6,879 tests on 5 boxes in 70 s wall and 887 s CPU, red on [40 failures CI does not show](../troubleshooting.md#red-in-box-green-on-ci).

## The speed run, on 0.51.0

Measured once on a target project, 2026-11-06, Windows 11 host, a copy of the skill as it stood that day. Three fleets, 9 boxes
of 4 vCPU, 17 box-minutes, about $0.17 by ledger, and the account empty at the end.

| Fleet | Result |
|---|---|
| Rank, 3 boxes, the whole suite of 4,441 tests | 175 to 186 s per box; the same top files as CI bar one, at 1.4 to 1.6 times CI's seconds; one file 52 to 76 s between boxes on one sha |
| A/B, 3 boxes by 4 ABBA rounds, one change shipped as a patch in the command | `test_red_check.py` 34.4 s to 22.2 s, median of 12 runs a side, spread 34.1-35.4 against 22.0-22.5; an earlier patch gave 34.5 against 22.1 |
| CI after the change | **not run**: the change is unpushed |

The repeats were made distinct with a dummy variable, since the fleet then refused one command repeated per box. Round 6
accepts the repeat and counts each box's tests on its own; no box has run that.

That snapshot was a frozen working tree, and it differs from the final tree of that round in six files (`sbx_check.py`, `sbx_drift.py`, `adapters/files.py`, `adapters/process.py`, `domain/onboard.py`, `ports.py`), the archive reader's exception list among them. The changes made since (the refusal on a trusted file with no `repo`, the box lines at create, `--expect-tests`, `--means`, `--label`, `--max-usd`, the `--config` of `sbx_check.py` and `sbx_onboard.py`) are tested on the fake and in real bash, and ran on boxes on 2026-11-06 on the tree of that round: see the README's table. Rounds 5 and 6 changed the code again, and no box has run that.

## Measurements still owed

- Whether restarting a box picks up a scoped secret added after `create` (on sbx 0.51.0 cloud, measured 2026-11-06, with a custom secret, a scoped secret added to a running box did not reach it within 60 s; set before `create`, it did; the restart case is not measured).
- Whether a non-empty local list emits a top-level `sandboxes` key in `sbx ls --json` (on sbx 0.51.0, measured 2026-11-06, cloud `ls --json` is an array of rows and an empty local list is `[]`; a non-empty local shape is still unseen; the `{"sandboxes": [...]}` shape was seen on an older version by a third party). The adapter accepts both shapes and refuses others.
- Whether `kit.allowedSources` setting replaces the full list and enforces kit sources (exists on sbx 0.51.0, verified 2026-11-06, default `["docker.io/","dhi.io/"]`, env var `DOCKER_SANDBOXES_KIT_ALLOWED_SOURCES`; set and enforcement not measured).

Each is unverified until someone runs it, with a log.

| Owed | Why it matters |
|---|---|
| The fleet on real boxes since the last code change | the second runs of 2026-11-06 used the tree of that round; rounds 5 and 6 then changed the fleet, the parser, the process runner and how a repeated command counts, and no box has run them. One targeted and one sharded run would cover the final tree, with its new output and `verdict.json` fields |
| CI's seconds for a change the boxes measured | the speed run's 12 s gain is a box figure; box seconds ran 1.4 to 1.6 times CI's, so CI should gain less |
| Why 40 tests fail in a box and pass on CI | [root cause not found](../troubleshooting.md#red-in-box-green-on-ci) |
| `docker events` as a count of container starts | proposed from the field run, not run in a box |
| An untrusted run on an account holding a global `github` secret, and one holding only `anthropic` | the refusal is tested on the fake and on the live row shape; the hosts per service are from Docker's page, not measured |
| A global row in `sbx --cloud secret ls --json` | only a box-scoped row has been seen under `--cloud`; the global row and `custom_secrets` shape come from a listing with no `--cloud`. A global row with a scope other than `global` or empty would not be recognised |
| A physical Ctrl+C | CTRL_BREAK and a raised SIGINT were tested; the gate harness had no console to send a real Ctrl+C from |
| The account's real vCPU quota refusing a create | the quota is the user's declared number; a refusal from the server needs more than 3 boxes of 4 vCPU |
| `tests/test_contract.py` with `SBX_LIVE=1` | proves the fake matches the tool; costs one small box |
| A fleet of more than 10 boxes | 40 vCPU allows 20 of 2, and more than 10 is unmeasured |
| The box name length limit | `--help` states the characters, not a maximum; 30 for the project part is a cautious guess |
| A real fork's test suite through `sbx_fleet.py --pr`, on the final tree | one real fork's pull request ran in a box on 2026-11-06, level untrusted, rc 0, with `--no-junit` and a one-line command, on an earlier tree |
| The two CI templates on GitHub, and `sbx login --password-stdin` in a job | they pass zizmor, actionlint and their tests; Docker documents the sign-in; no job has run them. A hosted runner's install, Read scope for `--cloud`, and the December 2026 event policy are unmeasured |
| A non-empty `allow_networks` on a real account | only an empty list has been seen live; the fleet reads the documented shape, and reads anything else as unreadable |
| A killed `create` on the real CLI through the fleet | the exit code is modelled from [finding 8.2](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L393), not measured; the fleet looks for 40 s, and a create that finishes later is reported as possibly left behind |
| A fine-grained token against `sbx_trust.py doctor` | endpoints were called with an OAuth token; permissions come from GitHub's docs |
| Spend | no billing figure was read. The ledger is box-seconds at a rate read in October 2026: about 30 box-minutes of 2 or 4 vCPU in the gate runs, and $0.34 in the field run |
| A real install on each harness | the manifests pass `claude plugin validate` and `agy plugin validate`; nothing was installed from the pushed repository, and Gemini CLI, Cursor and `npx skills` were not run |
| How each harness gives the model the skill's folder | the rule is "the directory of the SKILL.md you loaded"; whether each harness shows that path was not checked |

## Adding a finding

1. Put it in a public source repo, with its script, log and repeat count. Measure twice before quoting it.
2. Pin the link to a commit sha and add one line here or in a pitfall note, with the sbx version.
3. Run `validate_skill.py`.
