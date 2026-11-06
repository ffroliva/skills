---
type: Knowledge
title: PR review by a sandboxed agent
description: Review an untrusted pull request read-only in a box, and what the box does not protect.
tags: [sbx, use-case, review, agents]
status: stable
date: 2026-11-05
state: tried-once
trust: untrusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/council-1108-result.md
---

# PR review by a sandboxed agent

Untrusted: check the commit first ([contributor pull requests](contributor-prs.md)).

[One run](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/council-1108-result.md#L9): 15 files, nine review dimensions plus a synthesis in one box, 150 s wall, $3.55
API-equivalent. The reviewed tree stayed clean, and the claims checked by hand held up.

**Needs:** the [pr-review kit](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/kits/pr-review/pr-review.yaml) or your own, egress to the model API only, and a sha taken
from the platform, never typed.

**Steps:** pin the sha, deliver the protocol from your default branch and not from the PR, run, read results from an
agent-owned folder, verify findings against the pinned sha.

**What the box does not protect.** [Measured](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L193): the agent has passwordless `sudo`. It rewrote a baked file, and
it unmounted a `:ro` mount and wrote its own replacement. The host copy stayed safe. So kits and signatures protect
provenance. Instructions that must hold belong in the prompt, and a box is used once.

**Pitfalls:** an unscoped run reached telemetry and connector endpoints. One `api.github.com` request stayed
[unexplained](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/docs/council-1108-result.md#L16). `sbx cp` [writes as root](../pitfalls/getting-code-in.md).
