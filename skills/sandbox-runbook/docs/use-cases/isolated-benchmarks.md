---
type: Knowledge
title: Isolated benchmarks
description: Use a box to escape host noise, and what it still cannot promise.
tags: [sbx, use-case, benchmarks]
status: stable
date: 2026-11-05
state: tried-once
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L483
---

# Isolated benchmarks

A box escapes your workstation's other processes. It does not promise a quiet host.

- **Steady, normally.** Same commit, 5 x 8 vCPU: two pairs agree, DRAFT in the source, [within 2.5%](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L483). On a target project (not independently
  reproducible), three 4 vCPU / 8 GB runs matched to about 3% per stage, while the same work on a shared workstation
  ranged 769-1152 s.
- **Not always.** One [window ran up to 1.5 times slower](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L478), 4 runs, one occurrence, DRAFT. Steal does not show it.
- **So measure the box.** Run a fixed CPU workload before and after, and report the coefficient of variation. On the
  target project it was under 1% in most runs and 13.9% once, from one slow sample.

**Do:** pin the image by digest, use one shape and repeat at least three times: the same `--command` once per box is a repeat. Compare ratios inside one box. Quote
run count and spread. A baked, offline image means a run downloads nothing.

**Do not:** compare absolute times across boxes, or treat steal as a contention signal. A database in the app's
process hides what a networked one costs.

Warm, a Java build ran [22% faster in the box than on its Windows host](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L20), cause unmeasured. Do not read a box as your host.
