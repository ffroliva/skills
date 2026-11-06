---
type: Knowledge
title: "Pitfalls: lifecycle and billing"
description: What keeps a box billing, what rm destroys, and how to watch a long run.
tags: [sbx, pitfalls, billing, lifecycle]
status: stable
date: 2026-11-05
---

# Pitfalls: lifecycle and billing

| Id | Pitfall | Cost | Fix | sbx |
|---|---|---|---|---|
| [8.2](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L393) | A `create` whose client is killed still completes | bills to its TTL | always `--ttl`; `rm` after any failed or timed-out create | 0.50.0 |
| [8.19](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L494) | A new cloud box hibernates at 60 min by default, captured once | a box left behind | `--on-timeout delete` | 0.50.0 |
| [bench 2](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L32) | A stopped box stops serving its git remote, and `rm` deletes uncollected commits | 2 of 3 features lost in one run | collect as each agent exits, retry, never `rm` what is uncollected | 0.50.0 |
| [8.14](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L449) | No detached exec | a run tied to one exec | `nohup ... & disown`, then poll for a done file | 0.50.0 |
| [8.15](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L452) | No resource metrics in the cloud | blind sizing | sample `/proc/stat` in the box | 0.50.0 |
| [8.16](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L454) | No cost per box, no run history | spend discovered late; the Usage page lags up to 48 h | your own ledger | 0.50.0 |
| [8.17](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L464) | `stats`, `logs`, `quota`, `wait` do not exist; `events` is local only | polling | poll exec | 0.50.0 |

Measured on a target project, not independently reproducible:

- A live read works and changes nothing (sbx 0.51.0, one run). A trusted run prints each box's name at create, with its read: `sbx --cloud exec <box> bash -c 'tail -n 20 ~/out/run.log'`. Add `docker ps` for a Testcontainers run. An untrusted run prints the name alone: that box's text is data, and the fleet does not invite it into a terminal.
- `sbx ls` printed `No sandboxes found` with a cloud box running: [entry](../troubleshooting.md#sbx-ls-shows-nothing).
- Exec streams drop large output (a 55 MB tar failed): `tar` in the box, `sbx cp`, compare sha256, and only then `rm`.
- Killing a local fleet client's process tree leaves its boxes running. Stop it with Ctrl+C or SIGTERM. After a hard
  kill, run `sbx_fleet.py --project <name> --sweep-only`.
- A TTL of about 1.5-2.2 times the expected run, with a deadline 15 minutes before it, left time to collect partial
  output. Start the run under `setsid`, so stopping it also stops its children.
- `env VAR=x` must precede `nohup`. A variable placed after it runs as a program, and a test that inspects the built
  string will not catch that: test through the real entry point.
