---
type: Knowledge
title: Sizing and cost
description: Which box shape, how many workers, and what a run costs, with repeat counts.
tags: [sbx, sizing, cost]
status: stable
date: 2026-11-05
---

# Sizing and cost

Case source: the [22,000-test Python suite case](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md).

## Workers (8 vCPU / 16 GiB, one run per row, [case L36-L51](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L36-L51))

| Workload | Workers | Result |
|---|---|---|
| Database tests | 8 | best, 164 s; 12 and 16 are no faster and leave 0.1-0.3 GiB free |
| Browser tests | 4 | stops scaling: one 69-test file held a worker for the run |
| Both at once | 8 + 4 | 24% faster than in sequence, 0.7 GiB free |

One worker per vCPU for database tests. Each costs about 1.1 GiB, so memory runs out before CPU.

## Serial runs

"One worker per vCPU" is for parallel runs. A serial run (`-n 0`) uses one core whatever the box, so shape it by memory alone. Measured on a target project, not independently reproducible, one run, sbx 0.51.0: a serial gate on 8 vCPU showed load about 1 and under 1 GiB used, so three quarters of what was paid for sat idle. A 2 vCPU box would cost a quarter for the same wall if single-core speed holds on the smaller shape, and that was not measured.

## Shapes

Cloud shapes are fixed. `sbx --cloud create --help` on 0.51.0 lists micro 1/2, small 2/4, medium 4/8, large 8/16 and xl 16/32
vCPU / GiB, and `sbx_fleet.py` refuses anything else before `create`.

On that project a 4/8 box used 78-96% CPU but at most 2.4 of 8 GB; a 2/4 box took 1.61 times the box-seconds (three
runs against one).

## Cost

Billing is per runtime second by shape: Large (8 vCPU) is [$0.56 an hour](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L119), Medium [$0.28 an hour](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L113).
A 22,000-test run on 5 boxes was about $0.48, one run. The rate is linear in vCPU, so more boxes change the wall, not
the price. Faster tests lower both.

Prices were read in October 2026. Check yours on the Usage page.

The CLI shows no [rate or cost](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L454), so keep your own ledger, and charge a box you could not
remove its full TTL. Every client-side ledger undercounts when its client dies.

`sbx_fleet.py` prints such a ledger at the end and keeps it in `verdict.json` as `estimated_usd`: box-seconds at $0.07 a vCPU-hour, the rate above. `--max-usd`, or `max_usd` in the adoption file, refuses a run before any box exists when its worst case, every box billing to its TTL, is over that amount. So a 5 x 8 vCPU fleet with a 30 minute TTL needs a ceiling of at least $1.40, whatever it would really spend. If your rate differs, the figure is wrong by the same factor.
