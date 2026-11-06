---
type: Knowledge
title: Parallel agents on features
description: Headless coding agents building independent features, one box each or one box between them.
tags: [sbx, use-case, agents]
status: stable
date: 2026-11-05
state: measured
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L145
---

# Parallel agents on features

Three features on a Java 25, Spring Boot service, [two rounds each](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L145):

| | 3 boxes, 4 CPU / 4 GB | 1 box, 12 CPU / 12 GB, 3 worktrees |
|---|---|---|
| Agent wall | 140 s, 144 s | 137 s, 130 s |
| Token cost | $0.53, $0.54 | $0.41, $0.38 |
| Merged, full verify | 3/3, 3/3 | 3/3, 3/3 |

Separate boxes buy isolation, not speed: a blast radius, a policy and limits per agent. One box shares `~/.m2` safely,
because locks work on one kernel. Agent time is mostly model time.

**Steps:** `sbx create --clone --cpus 4 --memory 4g claude <repo>`, `claude -p` through `sbx exec`, `git fetch
sandbox-<name>` the moment an agent exits, merge on the host, run the real build there.

**Runner:** [parallel_features.py](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/parallel_features.py), and an
[orchestrator proof of concept](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/orchestrator/README.md) with a single-writer host inbox, one run.

**Cloud:** no host workspace. Each worker clones, then pushes a scratch branch with the proxy-held token.
[One run](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L97).

**Pitfalls:** one worker named a commit that does not exist, so trust git refs, not prose. A
[stopped box serves no remote](../pitfalls/lifecycle-billing.md). Files must be independent, or merges conflict.
