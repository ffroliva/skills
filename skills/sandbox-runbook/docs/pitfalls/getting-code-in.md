---
type: Knowledge
title: "Pitfalls: getting code in"
description: Clone against cp against volumes against kits, and what each costs per box.
tags: [sbx, pitfalls, kits, transfer]
status: stable
date: 2026-11-05
---

# Pitfalls: getting code in

| Id | Pitfall | Cost | Fix | sbx |
|---|---|---|---|---|
| [8.7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L420) | `sbx --cloud cp` is slow and erratic, and a fleet divides one uplink | 33-181 s for 81 MB, three boxes | clone inside the box: 2-7 s at depth 1 | 0.50.0 |
| [8.8](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L424) | A new cloud volume is 89 MB, with no size option | `No space left on device` | no repo or cache on a volume | 0.50.0 |
| [8.9](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L427) | A server-built kit costs 227-325 s on first create, then 16-20 s, against 7 s stock | billed once per kit change | worth it only when it saves more per box: about 100 s here | 0.50.0 |
| [8.10](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L431) | `sbx kit validate --offline` rejects a v3 source kit | no offline check | validate with a real build | 0.50.0 |
| [8.11](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L433) | Template contents are undocumented | a kit reinstalls what exists | look first | 0.50.0 |
| [section 6](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L253) | A v3 mixin cannot be added to a built-in agent | refused at create | use a v3 workload | 0.50.0 |
| [section 6](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L255) | The v3 claude workload ships no JDK | Java silently lost | add [a JDK mixin](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/kits/jdk25/jdk25.yaml) | 0.50.0 |
| [council run](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/council-1108-result.md#L61) | `sbx cp` writes as root, and `dir/.` copies the directory itself | a stale runner waited 30 min | use an agent-owned output folder, a landing check, a fail-fast | 0.50.0 |

## Which route

The box clones the pushed commit, so nothing from a working tree or `.env` reaches it. That is why only what you would
publish belongs in a box headed for a public remote.

A private repo has three routes. A read-only token scoped to one box, through the proxy. A fine-grained push token, the
same way, [measured](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L129). Or `git archive` over exec, which needs no token and no network: measured on a
target project, not independently reproducible.

Use a full clone unless you know your tests never read history. Measured on a target project, not independently
reproducible: a `--filter=blob:none` clone failed tests that read git history, once, until those blobs were prefetched.

One small public helper file that belongs in no commit, such as a probe: put it in `--command` as base64, decoded in the box. Windows caps a command line at about 32 KB, which is that route's ceiling. Worked on a target project, sbx 0.51.0, one run. There is no upload flag on purpose: "nothing from the working tree reaches a box" stays true, so what a box received can be read from the run's own command. Never a secret this way.

`sbx --cloud template save` is a documented fan-out route, [not measured here](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L420).
