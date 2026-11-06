---
type: Knowledge
title: History of the findings
description: How each use case was found and abstracted, what failed on the way, and what the sbx team could take apart from the skill.
tags: [sbx, history, evidence, donation]
status: stable
date: 2026-11-05
---

# History of the findings

An evidence log, written for the sbx team. Each section gives the problem a project had, what was tried, what failed, what was
measured, and the rule the skill took from it. Wrong turns stay in. Findings come from one account and one Windows 11 host, in
October and November 2026, so read every number with its sbx version and repeat count. Sources are pinned to a commit. A private target project keeps
its [provenance label](reference/evidence.md#labels) and no name.

Most sources are in [sbx-team-kit at a pinned commit](https://github.com/ffroliva/sbx-team-kit/tree/b25e1d28a135bcc2d6f643b3b95f129bc53008b1), below called the kit.

## Use cases

### Shared memory across agents (27 Oct, sbx 0.50.0)

- **Problem:** several agents wanted one memory store through `host-mount@1`.
- **Tried:** two boxes writing one Markdown memory file at once.
- **Measured:** [11 lines of 400 survived](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L7), then 28, 17 and 16 on three repeats; a one-writer control kept 200 of 200 every round.
- **Rule:** one writer per shared store, because locks do not cross boxes. A writable store shared across boxes is on the "wrong tool" list.

### Parallel agents (27 Oct, sbx 0.50.0)

- **Problem:** independent files, one agent per box.
- **Wrong turn:** separate boxes were the plan, until a maintainer asked on [sbx-releases#775](https://github.com/docker/sbx-releases/issues/775) why the agents did not share one box.
- **Measured:** one box with worktrees 130 to 137 s and USD 0.38 to 0.41, against 140 to 144 s and USD 0.53 to 0.54 for separate boxes, two rounds each ([the table](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/UPSTREAM.md)).
- **Rule:** one box was as fast and cheaper; separate boxes buy isolation, not speed.

### Shared dependency cache (27 and 28 Oct, sbx 0.50.0)

- **Problem:** every box downloaded the same Maven and Python dependencies.
- **Tried:** a [`host-mount@1` Maven cache](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L217), then [cloud volumes](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L260).
- **Failed:** two boxes on one cloud volume, where the last to exit won.
- **Rule:** fill the cache with one writer, then share it; no build writes to it.

### Full suite offload (27 to 30 Oct, sbx 0.50.0)

- **Problem:** a target project's whole suite blocked a laptop. Measured on a target project, not independently reproducible.
- **Tried:** [five boxes of 8 vCPU](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L358) on a suite of about 22,000 tests, 750 s on the first green run and 521 s four fixes later.
- **Failed:** a box lost to the vCPU quota, a 429 on concurrent creates, and a slow window on the hosts that the guest could not see. The last is a [draft, measured once](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478).
- **Rule:** one verdict from every shard; a lost shard fails on the unique test count; a box that never ran is no verdict, not red. Keep CI.

### Credentials in a box (2 Nov to 5 Nov, sbx 0.50.1 and 0.51.0)

- **Problem:** private clones and private indexes from a box.
- **Measured:** [a cloud scoped secret outlives `rm` and the TTL reaper, and the next box with that name receives it](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L360): 6 of 6 cloud, 0 of 3 local, on 0.50.1; outliving `rm` confirmed on 0.51.0.
- **Wrong turn:** a usage test showed the skill had no route for a token outside sbx's service list. `set-custom` and bare `-e` were added from `--help`, unverified, and the fleet could not actually use `set-custom` until gate 8 failed on it.
- **Rule:** unique box names, a refusal on a leftover secret, `rm` and `secret rm` both, always, and a secret set before `create`.

### Testcontainers (0.50.1, then 0.51.0)

- **Problem:** tests that start real databases.
- **Wrong turn:** on 0.50.1 `shell-docker` worked and the skill mapped to it. On 0.51.0 it [is refused three ways](troubleshooting.md#shell-docker-unknown-agent): as an agent, as a template, and as a kit over the pull limit. Plain `shell` runs Docker instead.
- **Measured:** 0.50.1 worked unchanged inside the full suite; on 0.51.0, [one PostgreSQL 17.11 container](use-cases/testcontainers.md#testcontainers-on-sbx-0510), 1 passed in 28 s, one run.
- **Rule:** `template: shell`, `**.docker.com` as well as `**.docker.io`, one database per worker. Facts about what a template ships carry their version.

### The testing fleet on real boxes (5 Nov, sbx 0.51.0)

- **Problem:** the fleet script had 493 tests and had never touched a real box.
- **Measured, one run each, on a public project:** a targeted run of 451 ran plus 4 skipped (455 reported; sbx 0.51.0, 2026-11-06), rc 0, 60 s, the same count as a local run (451 passed, 4 skipped); `--expect-tests` counts tests that ran: skips are not counted. Three boxes summing 465, 551 and 1,482 to the expected 2,498. One box deleted by hand: red, and `found 1947: a shard was lost`.
- **Failed, and fixed by a test first:** a pull request's head absent from the host clone refused the main untrusted route. CTRL_BREAK ended the process with no clean-up. The custom-secret path above was missing. The account's network default was declared, and never read.
- **Rule:** a fake built from `--help` finds wrong flags, and finds none of those four.

### The first real user (5 Nov, sbx 0.51.0)

- **Problem:** a target project needed a live oracle over four database servers and planted faults: 21,859 tests, no Docker on the laptop, and a CI job that had run for hours. Measured on a target project, not independently reproducible, one run of each fleet.
- **Tried:** the skill as written, from a frozen snapshot, by an agent that logged every guess: 25 entries.
- **Measured:** the live gate and its plants in 8 min 52 s on 6 boxes of 8 vCPU, about $0.20. A gate run twice with its mutants in 115 s. The whole day: six fleets, 13 boxes, 2,186 box-seconds, $0.34 by ledger. No create refused, no 429, no out-of-memory, no TTL reached. The platform was never the problem.
- **Wrong turns, the skill's:** a trusted file with no `repo` ran on at level untrusted, billing for a run that would have brought back no log. `sbx ls` said no boxes while one was billing. "Containers start" was true of a gate starting one container per row, 252 of 256 rows invalid, and a live read found that at minute 2 for $0.07, where the same defect had kept CI busy for 2 h 38 min. GREEN on a planted fault read as success. A gate that is red by design could not be told from one that died. `Heavy gates` was marked an untested idea, and worked first time.
- **Wrong turns, the agent's:** a probe shipped untested and lost one box's result; a gate split off for fear of a deadline it would have met; 8 vCPU paid for a serial run.
- **Also seen:** another project's own fleet driver went red on 40 tests that CI does not fail, new since `shell` became a hardened Debian 13 kit. Root cause not found, so it is [a troubleshooting entry](troubleshooting.md#red-in-box-green-on-ci), not a rule.
- **Rule:** a refusal beats a surprise downgrade. A verdict says what it covers: `--expect-tests` for complete, `--means` for what green means, the box names and a live read at create. A State line says only what evidence shows, including who ran it and on what.

### Contributor pull requests (5 Nov, sbx 0.51.0)

- **Problem:** a public project cannot vouch for a contributor's code.
- **Wrong turn:** two levels, an enforced profile and a verdict on one exact commit came first, and the first version let a contributor trust themselves by editing the adoption file, and could not reach a pull request's commit from a plain clone at all. Then a second review broke the fix three ways, each with a working probe: on Windows the adoption-file guard compared `docs\sbx.md` with `docs/sbx.md` and never fired; a run with no secrets still reached `github.com` on an account holding a global `github` secret; and `--repo` could name a fork whose owner was an admin there.
- **Rule:** a level follows from facts about the commit, its repository and the account, never from a flag. Paths are resolved, the repository is named in the adoption file, and the account is read before create.
- **State:** the refusals are tested; a real fork has not run through a box. See [what is owed](reference/evidence.md#measurements-still-owed).

### Staying current (5 Nov)

- **Problem:** sbx changes between releases: 0.51.0 made `shell` a published kit, and the images behind `shell-docker` stopped being refreshed.
- **Wrong turn:** the first drift check walked local help, which lists flags `--cloud` refuses, and it read a lost cloud command as aligned.
- **Rule:** walk `--cloud --help` for the commands the scripts call, read no network as "could not check", and open one issue from a weekly job.

## Wrong turns in the method

- **A list became a runbook.** The skill began as a list of facts. A usage test, with the skill and without it, found ten gaps a list could not close. It became scenarios with steps and checks, run by scripts.
- **The hashed denylist.** Private names shipped as hashes, on the idea that a hash hides them. A review recovered 15 of 32, 12 from public text alone, and 19 of 21 planted leaks passed the check. The file went. A word list now lives outside the repository.
- **The false green.** A reused `--out` counted an earlier run's JUnit as this run's. Later, exit 0 with a failed test in JUnit printed GREEN while `sbx_shard.py check` on the same folder said `1 failed`. Both now refuse or go red. A verdict reads outcomes, not just a count.
- **A review broke its own rule.** The brief said no sbx write command. A background fork ran `sbx --cloud cp` three times at a box that did not exist. All three failed, and listings showed nothing created. The review disclosed it.
- **A test that matched by luck.** A check that the deadline tars partial results passed because "tar" sits inside `acme-targeted`. A mutant showed it.
- **Mutants found what tests missed.** The first review left 29 of 56 hand-picked safety mutants alive. The second found three more, among them `own_work: untrusted` read as trusted, in code no test had reached. Green tests said nothing about those lines.
- **A "4/3" load bound** as commonly written is false, on four equal files and three shards. The bound the skill uses adds the pigeonhole term: worst 1.32 in 600,000 random cases, which is evidence, not proof.
- **A scrub that cleaned the tip and left the history.** The kit's commit that removed private names removed them from its latest snapshot only. Its pinned commit, `b25e1d2`, holds none of them, but the kit's earlier public commits still do: the private target projects' names, local paths and a private repository's name. The owner decided, on 2026-11-06, to leave that history as it is. Rewriting it would change `b25e1d2` and break every evidence link here, and those commits have been public since they were pushed, so a rewrite would not take them back. The tip is clean; the history is not, and is not going to be.
- **An archive limit that was a sentence.** The reader relied on `tarfile`'s `data` filter, and asked in prose for a current Python. On Python 3.13.1 a box's archive overwrote a host file through a hard link, by a published bypass of that filter. The reader now writes regular files itself, and refuses a link, device, absolute path or `..`, whatever the Python.

## What the sbx team could take

Apart from the skill, and useful alone:

- The fake at the process edge, `tests/fakes.py` in this repository: it refuses any flag absent from a help snapshot, and it keeps a scoped secret after `rm`.
- [`sbx_drift.py`](../scripts/sbx_drift.py) and its snapshot, as a check that `--cloud` help does not move silently.
- The [`/rate_limit` probe](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L360), which tells a scoped secret, a global secret and no secret apart from inside a box.
- [Troubleshooting](troubleshooting.md), keyed by exact error text.

## Product suggestions, not skill content

Each of these is a workaround in the skill that sbx could make unnecessary. What was filed, and what was not, is tracked in [UPSTREAM](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/UPSTREAM.md).

| Finding | Workaround here | What would remove it |
|---|---|---|
| A cloud scoped secret outlives its box | unique names, `secret rm` after every `rm`, a refusal on a leftover | `rm` and the reaper delete it, as local does |
| No command reads the quota; enforcement varies | a declared `quota_vcpu`; a refused create is the only signal | `sbx quota` with usage, and a fleet refused up front |
| A killed `create` still completes and bills to its TTL | a final listing, and a second look after a timed-out create | a create that can be cancelled |
| 429 on concurrent creates | retries with backoff in the script | a retry with the server's delay, or `create --count N` |
| A global secret reaches any box that may reach its hosts | the fleet reads `secret ls`, and refuses | a per-create "no global secrets" flag |
| No limit on `sbx cp`, and an archive from a box is untrusted | caps after the download | a size limit on `cp` |
| `sbx ls` shows no cloud box, and says so as if the account were empty | the fleet and the notes name `sbx --cloud ls` | a hint in that output when the account holds cloud boxes |
| No cost per box in the CLI | a ledger at a rate read by hand, and a worst-case ceiling | a cost in `ls --json`, and a rate command |

## Licence

Apache-2.0, as is sbx-team-kit. The licence allows the sbx team to take any of this, with its notice. There are no contributor terms beyond it.
