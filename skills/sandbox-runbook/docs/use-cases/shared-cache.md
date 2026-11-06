---
type: Knowledge
title: Shared dependency cache
description: Share a dependency cache across boxes only after one writer has filled it.
tags: [sbx, use-case, cache, maven]
status: stable
date: 2026-11-05
state: measured
trust: trusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L217
---

# Shared dependency cache

[Three sandboxes building at once](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L227), a real Java build, 207 MB of dependencies, local:

| | Rounds | Builds passed | Wall per round |
|---|---|---|---|
| Private caches, cold | 2 | 6/6 | 156 s, 147 s |
| Shared, cold, 3 writers | 3 | 2/9 | - |
| Shared, filled by one writer first | 2 | 6/6 | 107 s, 101 s |

No silent corruption was found: Maven fails loudly. But it works only with one writer. A read-only mode is
[requested upstream](https://github.com/docker/sbx-releases/issues/775), not available.

For agent work this matters less: agent time is mostly model time. In the cloud, depend on a fast cold install, or bake
the cache into a kit. `host-mount@1` is local only.

Kit: [maven-cache](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/kits/maven-cache/maven-cache.yaml). It needs a root startup hook, because the mount creates `~/.m2` owned by
root. More: [shared storage](../pitfalls/shared-storage.md).
