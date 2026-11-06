---
type: Knowledge
title: "Pitfalls: quota"
description: The vCPU quota and create limits a fleet hits, and how to treat them.
tags: [sbx, pitfalls, quota]
status: stable
date: 2026-11-05
---

# Pitfalls: quota

| Id | Pitfall | Cost | Fix | sbx |
|---|---|---|---|---|
| [8.5](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L410) | The 40 vCPU quota is enforced at create, inconsistently: 56 ran against 40, then one box was refused | a run red because a box never existed | size the fleet up front; `sbx_check.py` counts live boxes | 0.50.0 |
| [8.6](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L414) | Eight concurrent creates: one fails with HTTP 429, and the CLI does not retry | one box missing | stagger creates; retry 429 only | 0.50.0 |

The quota is per account, so another project's live boxes count against yours. Your limit may differ from 40: confirm
it.

There is no sbx command that reads the quota: no `sbx quota` or equivalent appears in `sbx --help` on 0.50.1 or 0.51.0, and
[8.17](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L464) found
none on sbx 0.50. `quota_vcpu` in the adoption file is therefore a figure you declare, and `sbx_check.py` says so. The only
live signal is a refused create (`Maximum running vCPU quota reached ... limit 40`, 8.5). `sbx --cloud ls --json` reports `cpus` per box on 0.51.0, so `sbx_check.py` counts live vCPU.

The bound: 40 vCPU allows 5 boxes of 8, or 20 of 2 ([8.5](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L410), sbx 0.50.0). More than 10 boxes is unmeasured: see
[measurements still owed](../reference/evidence.md#measurements-still-owed).

Measured on a target project, not independently reproducible: a kit `create` failed with `settings platform
construction failed` in 1 of 5 parallel creates, three times in three days. `sbx_fleet.py` retries it. Without a retry,
that slice is no verdict, not a code red.

Exit 3 from `sbx_fleet.py` says nothing about the code: a box never started, and no box that ran failed. One refused box of three
is exit 3, because quota is enforced inconsistently (8.5), so a partial refusal is the likely one. A box that ran and failed still
makes the run red. Fall back to CI. Never retry in a loop.
