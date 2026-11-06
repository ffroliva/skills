---
type: Knowledge
title: Versioned CLI facts
description: Selected Docker Sandboxes CLI facts and their evidence state, pinned to the checked release.
tags: [sbx, cli, evidence]
status: stable
date: 2026-11-06
---

# Versioned CLI facts

Checked against sbx 0.51.0 help/source and the peer-review notes dated 2026-11-06. These are versioned observations, not promises for later releases.

| Fact | Evidence, version and safe use |
|---|---|
| `sbx create --clone` needs a repository URL; work is returned through refs under `refs/sandboxes/<name>/*`. | `docker/skills` lifecycle guidance, Apache-2.0, reviewed at commit `9f04a05d5fcdbfac0f6088bc711e930a75896482`; not re-run here on 0.51.0. Treat as guidance and inspect `sbx create --help` before use. |
| `--skills` controls the shared skills store; it is read-only by default. | V11, sbx 0.51.0 help/source snapshot, peer review 2026-11-06. Verify the exact flag with local help. |
| `kit.allowedSources` | V17: exists on sbx 0.51.0 (verified 2026-11-06), default `["docker.io/","dhi.io/"]`, env var `DOCKER_SANDBOXES_KIT_ALLOWED_SOURCES`; set and enforcement not measured. |
| `sbx ttl` exists and caps a box at 24 hours. | sbx 0.51.0 `sbx --cloud ttl --help`, peer review 2026-11-06. |
| Cloud `run --new` creates a new box and `--detach` detaches it. | sbx 0.51.0 `sbx --cloud run --help`, peer review 2026-11-06. |
| Local boxes auto-stop after an idle period. | `mattjohnson/orca-sbx-recipes`, MIT, commit `40f210f3f0d390cd66de7923de2d773ea82d9c96`, reported on sbx 0.38.0; not rechecked on 0.51.0. |
| `sbx ls --json` output shapes | V15: on sbx 0.51.0 (measured 2026-11-06), cloud `ls --json` is an array of rows; an empty local list is `[]`; a non-empty local list is not measured. The `{"sandboxes": [...]}` shape was seen on an older version by a third party. The adapter accepts both shapes (an array of rows or `{"sandboxes": [...]}`) and refuses others; adapter and tests kept as-is. |
| `--app-name` isolated daemon | On sbx 0.51.0 (verified 2026-11-06), `--app-name` is accepted, but the isolated daemon is not signed in to Docker (`error: not signed in to Docker`), so it answers `settings` and `version` and cannot create boxes or list. |

The 0.51.0 source of truth for an installed CLI is its own `sbx --help` and `sbx <command> --help`. Run probes with `--app-name` where available so they cannot attach to the owner's daemon; note that on sbx 0.51.0 (verified 2026-11-06) the isolated daemon is not signed in, so it answers `settings` and `version` only and cannot create boxes or list.
