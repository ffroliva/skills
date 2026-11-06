---
type: Knowledge
title: Parallel test shards
description: Split one suite across boxes, and what sets the wall.
tags: [sbx, use-case, tests, shards]
status: stable
date: 2026-11-05
state: tried-once
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L410
---

# Parallel test shards

One run each, on a target project. Python, 22,000 tests. Five boxes gave the same wall as eight (750 s, and 761 s with one of the eight refused; one run
each). The suite is about 294
test-minutes, so within 40 vCPU the floor is about 7.4 minutes of tests per box. Source: the
[fleet case, L97](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L97).

- **The slowest box sets the wall.** Shard by measured duration, not by count. Rebalancing has a floor: at level boxes
  the work per box has to fall ([case L115](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/fleet-case-target-project.md#L115)).
- **A file longer than one box's share sets the floor.** Split it rather than adding boxes.
- **Separate the floor from the fleet.** Sum the busy CPU-seconds and divide by vCPUs. [Finding 8.20](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L510), DRAFT in the source: 700 CPU-seconds over 40 vCPUs is an 18 s floor,
  against 64-82 s wall, because shards were unbalanced (83-219 CPU-s per box); 2 runs.

**Needs:** a shard filter ([Python recipe](../../templates/python.md), [Java recipe](../../templates/java.md)). Maven sharding is an
untested idea. How to plan and check shards: [sharding](../reference/sharding.md).

**Pitfalls:** [quota](../pitfalls/quota.md).
