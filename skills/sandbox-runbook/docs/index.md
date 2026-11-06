---
type: Knowledge
title: sbx knowledge index
description: Map of the deep notes behind the sbx skill - use cases, troubleshooting, pitfalls by area, and reference.
tags: [sbx, index]
status: stable
date: 2026-11-05
---

# sbx knowledge index

Short notes. The source repositories stay authoritative: each number links to its pinned source.

## Use cases

| Note | Trust | State |
|---|---|---|
| [Targeted tests](use-cases/targeted-tests.md) | trusted | tried twice on 0.51.0 |
| [Full suite offload](use-cases/full-suite-offload.md) | trusted | measured |
| [Parallel shards](use-cases/parallel-shards.md) | trusted | tried-once |
| [Testcontainers](use-cases/testcontainers.md) | trusted | measured on 0.50.1, tried once on 0.51.0 |
| [Browser e2e](use-cases/browser-e2e.md) | trusted | tried-once |
| [Parallel agents](use-cases/parallel-agents.md) | trusted | measured |
| [Shared cache](use-cases/shared-cache.md) | trusted | measured |
| [Isolated benchmarks](use-cases/isolated-benchmarks.md) | trusted | tried-once |
| [Test optimisation](use-cases/test-optimisation.md) | trusted | measured once on a target project, 0.51.0; CI not measured |
| [Heavy gates](use-cases/heavy-gates.md) | trusted | tried-once |
| [Clean Linux](use-cases/clean-linux.md) | trusted | untested-idea |
| [Contributor pull requests](use-cases/contributor-prs.md) | untrusted | tried-once |
| [PR review](use-cases/pr-review.md) | untrusted | tried-once |
| [Untrusted code](use-cases/untrusted-code.md) | untrusted | tried-once |

## Troubleshooting

[Troubleshooting](troubleshooting.md): search it by the error text.

## Pitfalls

[Credentials](pitfalls/credentials.md), [lifecycle and billing](pitfalls/lifecycle-billing.md),
[quota](pitfalls/quota.md), [getting code in](pitfalls/getting-code-in.md),
[shared storage](pitfalls/shared-storage.md), [local against cloud](pitfalls/local-vs-cloud.md),
[Windows host](pitfalls/windows-host.md).

## Reference

[History](history.md), [architecture](reference/architecture.md), [trust levels](reference/trust.md), [the GitHub token](reference/github-token.md),
[sharding](reference/sharding.md), [evidence and versions](reference/evidence.md), [CLI facts](reference/cli-facts.md), [sizing and cost](reference/sizing.md),
[network policy](reference/network-policy.md), [resources](resources.md).
