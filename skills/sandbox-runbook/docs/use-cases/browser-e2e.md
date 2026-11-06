---
type: Knowledge
title: Browser end-to-end tests
description: Playwright on cloud boxes - workers, browser install, kit or no kit.
tags: [sbx, use-case, playwright, browser]
status: stable
date: 2026-11-05
state: tried-once
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L427
---

# Browser end-to-end tests

Python, 2,331 HTTP and browser tests are part of the suite in the [19-run series](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478). A quarter of the Playwright tests took
875 s serial and 311 s at `-n 4`, one run each. Browser tests stop scaling at 4 workers: one file held a worker for the
whole run. Source for these and the table: the fleet case,
[L23](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L23),
[L43-L49](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L43-L49),
[L66-L72](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L66-L72).

**Install or bake:**

| | stock template | [kit](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/kits/python-e2e/python-e2e.yaml) |
|---|---|---|
| First create | 7 s | 325 s, once |
| Later creates | 7 s | 16 s |
| OS libraries, browser, ffmpeg per run | ~114 s | 0 s |

One run each, 2 vCPU. The kit's Playwright version must equal the lock file's, or the browser downloads again.
Upstream also has a [playwright kit](https://github.com/docker/sbx-kits-contrib/tree/1de3c1e3313a4cc8f2ac4d93646ab204f2b3b769/playwright): second-hand, not tried here.

**Pitfalls:** the download [redirects to `storage.googleapis.com`](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L443). The kit's first
create is [billed](../pitfalls/getting-code-in.md).
