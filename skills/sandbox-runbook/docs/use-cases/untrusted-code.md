---
type: Knowledge
title: Untrusted tool or clone
description: Run code you do not trust in a box. Tried on an untrusted pull request, not on a tool.
tags: [sbx, use-case, security, isolation]
status: stable
date: 2026-11-05
state: tried-once
trust: untrusted
source: https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L193
---

# Untrusted tool or clone

**State:** tried once, on an [untrusted pull request](pr-review.md). Running an untrusted tool's own code is untested.

What was measured, on the isolation it would rely on:

- [Default deny](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L162): an unlisted host got 403.
- [Read-only is enforced host-side](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L201): a guest remount changed nothing on the host.
- Boxes [cannot reach each other](../reference/network-policy.md).

**Do:** a fresh box, no secrets, the narrowest egress, no writable mount, one use. Read `sbx policy log` afterwards.

**Do not:** attach a credential. A global `github` secret on the account is injected into a box that may reach
github.com. Reuse a name: [`volume@1` data reattaches](../pitfalls/shared-storage.md). Trust what the tool reports
about itself: it has `sudo` in the box.

Upstream has scanning kits such as [trivy](https://github.com/docker/sbx-kits-contrib/tree/1de3c1e3313a4cc8f2ac4d93646ab204f2b3b769/trivy): second-hand, not tried here.
