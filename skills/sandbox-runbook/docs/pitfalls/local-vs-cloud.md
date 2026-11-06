---
type: Knowledge
title: "Pitfalls: local against cloud"
description: Same verbs, different behaviour. What changes between a local box and a cloud box.
tags: [sbx, pitfalls, cloud, local]
status: stable
date: 2026-11-05
---

# Pitfalls: local against cloud

| | Local | Cloud | Source |
|---|---|---|---|
| Runs on | needs KVM or Windows Hypervisor Platform; a KVM-guest VPS cannot run it | any signed-in client | [4c](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L209) |
| `--ttl`, `--on-timeout`, `--allow-network` | not available | yes | `sbx create --help`, 0.50.1 |
| Scoped secret after `rm` | deleted, 3/3 | kept and re-injected, 6/6 | [8.1](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L360) |
| Shared storage | live folder, locks do not cross | private copy, last exit wins | [7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L285) |
| Private kit volumes | survive `rm`, measured | ordinary disk, per Docker's docs | [7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L312) |
| Agent wall on 3 features | 140 s, 4 CPU / 4 GB | 97 s, 4 vCPU / 8 GB; one run each | [bench 7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L97) |
| `kit builder status` | works | not yet supported | [8.9](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L427) |

- A failed startup hook is [invisible](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L177): `sbx ls` says running with the service dead.
- Behind a TLS-filtering firewall, `sbx login` can say signed in while cloud fails:
  [network policy](../reference/network-policy.md).
- Measured on a target project, not independently reproducible: a local box needs free host RAM beyond its own size.
  One runner refuses below box memory + 6 GB.
- Default sizing was the whole host on 0.46. On 0.50.1 the help says all host CPUs and 50% of memory. Pass `--cpus` and
  `--memory` every time.
