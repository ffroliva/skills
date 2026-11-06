---
type: Knowledge
title: "Pitfalls: Windows host"
description: What bites when the sbx host is Windows, with the fixes that were tested.
tags: [sbx, pitfalls, windows]
status: stable
date: 2026-11-05
---

# Pitfalls: Windows host

| Id | Pitfall | Cost | Fix | sbx |
|---|---|---|---|---|
| [1b](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L125) | A mount reports an inode that changes on first write | SQLite rollback journal 0/50; anything using inode identity is exposed | WAL mode, or the VM disk | 0.50.0 |
| [1b](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L111) | Unix sockets on a mount hit the host path limit: bind fails from 108 characters | service will not start | put the socket in `/tmp` | 0.50.0 |
| [1b](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L110) | Git checks `.sh` files out CRLF | `pipefail\r: invalid option`; `sbx ls` still says running | `*.sh text eol=lf` | 0.50.0 |
| [7](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L288) | Git Bash rewrites `/vol` in `sbx exec` arguments you type | a void run, every command rc 0 | `MSYS_NO_PATHCONV=1` in that shell; these scripts start `sbx` directly and do not need it | 0.50.0 |
| [section 4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L175) | a Windows drive path appears in the VM as `/c/...` | wrong path | do not assume the same absolute path | 0.46, 0.50 |
| [section 4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L176) | Git Bash rewrites `msiexec` switches | the silent install hangs | install from PowerShell | installer |
| [section 4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L172) | `sbx daemon start` never returns | a script blocks | run `sbx ls`, which starts it | 0.50 |

Measured on a target project, not independently reproducible:

- Each kit `create` writes a copy of the image to the local temp drive, once per box. With 18 GB free, 2 of 5 creates
  failed. That project refuses to start below 6 GB free per box.
- Windows `TerminateProcess` runs no cleanup. Boxes run to their TTL, and scoped secrets stay.
- A background stop is `TerminateProcess` too: see [the entry](../troubleshooting.md#windows-background-stop).
- Under Git Bash with `MSYS_NO_PATHCONV=1`, a kit path must be in Windows form.

A console tool started from a background process can open a window on Windows. These scripts start every process with
`CREATE_NO_WINDOW`.
