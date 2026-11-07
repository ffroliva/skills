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
- **PowerShell vs Git Bash path conversion:** PowerShell (`pwsh` / `powershell`) and Python `subprocess` pass arguments to `sbx.exe` verbatim with no POSIX path conversion and do not need `MSYS_NO_PATHCONV=1`. Git Bash (MSYS2) rewrites leading-slash arguments (such as `/vol` or `/tmp` in `sbx exec` or `sbx cp`) into Windows drive paths before `sbx.exe` sees them unless `MSYS_NO_PATHCONV=1` is set in that shell (`MSYS_NO_PATHCONV=1 sbx ...`). Under Git Bash with `MSYS_NO_PATHCONV=1`, any host file or kit path passed to `sbx.exe` must stay in native Windows form, never an MSYS `/<drive>/...` path; prefer invoking `sbx.exe` from PowerShell or Python `subprocess` so no shell path substitution occurs.
- **Hidden background execution and exact PID/box ownership:** A console tool started from a background process can open a window on Windows. These scripts start every process with `CREATE_NO_WINDOW`. For any detached or background run on Windows, launch it hidden (`CREATE_NO_WINDOW` or `-WindowStyle Hidden`) with an explicit timeout and stdout/stderr redirected to a log file, and record the exact PID and box names at launch. Before stopping or restarting a job, inspect that exact PID and confirm its commandline or job record matches; stop only the exact owned PID and remove only the exact owned `<box>` names (`sbx --no-input --cloud rm -f <box>`), never killing by process name (`taskkill /IM`, `Stop-Process -Name`, `pkill`).
- **Noninteractive cloud policy prompt:** Without `--no-input`, passing `--allow-network` on `sbx --cloud create` can wait at `NETWORK POLICY ... Proceed? (y/N)` on stderr. On sbx 0.51.0, global `--no-input` before `--cloud` plus the explicit host flags is verified to create the box and scope those rules to it; if another command or version still requires an answer, use the two-step fallback in [create-allow-network-prompt](../troubleshooting.md#create-allow-network-prompt). An empty `sbx --cloud ls` is only an empty inventory.
