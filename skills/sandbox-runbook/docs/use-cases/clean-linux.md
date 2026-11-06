---
type: Knowledge
title: Reproduce a bug on a clean Linux
description: One box, one pushed commit, for a bug that needs a fresh Linux. No evidence yet.
tags: [sbx, use-case, debugging, linux]
status: stable
date: 2026-11-05
state: untested-idea
trust: trusted
source: none, untested idea
---

# Reproduce a bug on a clean Linux

**Untested idea.** Nobody measured this as a debugging route.

The nearest evidence: a real Java build [passed in a Linux microVM](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L20), which shows a box can hold a full build, not that it
reproduces a bug.

If you try it: `sbx_fleet.py --no-junit --command "<the failing command>"`, then read `box1/out/run.log`. A box clones
only what was pushed, so it cannot show a bug that depends on your working tree, your cache or your host. Template
contents are [undocumented](../pitfalls/getting-code-in.md), so a box is not your CI image: 40 tests have failed in a box
and passed on CI ([entry](../troubleshooting.md#red-in-box-green-on-ci)).
