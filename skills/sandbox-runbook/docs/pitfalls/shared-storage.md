---
type: Knowledge
title: "Pitfalls: shared storage"
description: Why nothing writable may be shared across boxes, measured at each layer.
tags: [sbx, pitfalls, storage, memory]
status: stable
date: 2026-11-05
---

# Pitfalls: shared storage

Locks are per VM. On a shared `host-mount@1`, every box believes it holds the only lock.

| Id | Store | Result | Fix | sbx |
|---|---|---|---|---|
| [1](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L7) | Markdown memory, two writers | 93-97% of writes lost, 4 rounds; one writer 200/200 | one writer | 0.50.0 |
| [1](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L17) | SQLite, two writers | 228 of 400 inserts failed; database unopenable, 1 run | one writer | 0.50.0 |
| [1b](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L104) | PostgreSQL on one data directory | damaged or destroyed, 4 of 4; up to 100% of acknowledged rows lost | one box per store | 0.50.0 |
| [6](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L217) | Maven cache, three cold writers | 2 of 9 builds pass | [fill once, then share](../use-cases/shared-cache.md) | 0.50.0 |
| [7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L260) | Cloud volume on two boxes | no refusal; last to exit wins, other box's writes lost, 2 rounds | never share one for writing | 0.50.0 |
| [7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L315) | `volume@1` after `rm` | data reattaches to the next box with that name and kit, 2 rounds | treat the name as the storage identity | 0.50.0 |
| [2](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L149) | `host-mount@1` | outlives every box; no command lists or removes it | clean it by hand | 0.50.0 |

Silent loss is the worst form: in the PostgreSQL case `pg_amcheck` passed while most of one writer's data was gone.

The safe patterns are one writer, or git. A broker with fencing tokens is **proposed, not measured**: see the
[single-writer design](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/single-writer-design.md).

A Docker named volume differs: containers share one kernel, so tools' own locks can work.
