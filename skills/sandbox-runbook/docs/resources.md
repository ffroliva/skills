---
type: Knowledge
title: Resources
description: The main documents to research on Docker Sandboxes, what to read each for, verified with last activity.
tags: [sbx, resources]
status: stable
date: 2026-11-05
---

# Resources

Every link was checked on 2026-11-05. The date is the repo's last push. Stars are not a quality signal.

## Official

| Resource | Read it for | Last activity |
|---|---|---|
| [Docker Sandboxes docs](https://docs.docker.com/ai/sandboxes/) | start here: concepts, setup | live |
| [`sbx` CLI reference](https://docs.docker.com/reference/cli/sbx/) | verbs and flags. `sbx <verb> --help` is authoritative for your version | live |
| [Customize](https://docs.docker.com/ai/sandboxes/customize/) | templates and kits | live |
| [Kits](https://docs.docker.com/ai/sandboxes/customize/kits/) | kit format; verify against the pinned spec version | live |
| [Credentials](https://docs.docker.com/ai/sandboxes/configuration/credentials/) | how secrets reach a box | live |
| [Isolation](https://docs.docker.com/ai/sandboxes/security/isolation/) | what a box separates | live |
| [Cloud](https://docs.docker.com/ai/sandboxes/cloud/) | cloud boxes | live |
| [Cloud credentials](https://docs.docker.com/ai/sandboxes/cloud/credentials/) | what differs in the cloud | live |
| [docs.docker.com/llms-full.txt](https://docs.docker.com/llms-full.txt) | the whole docs, for an agent | live |
| [docker/sbx-releases](https://github.com/docker/sbx-releases) | releases, issues, known bugs. Version observed: v0.51.0 | 2026-11-05 |
| [docker/sandbox-kit-spec](https://github.com/docker/sandbox-kit-spec) | the normative v3 kit grammar | 2026-11-05 |
| [docker/sbx-kits-contrib](https://github.com/docker/sbx-kits-contrib) | ready kits and mixins; Docker's repo, community kits | 2026-11-05 |
| [docker/skills](https://github.com/docker/skills) | Docker-authored agent skills, including local sandbox lifecycle | 2026-11-06 |
| [docker/docs](https://github.com/docker/docs) | docs source; docs changes per release | 2026-11-05 |
| [docker/sbx-kit-claude](https://hub.docker.com/r/docker/sbx-kit-claude) | the `sbx-kit-*` agent images; pin by digest | live |
| [dockersamples/sbx-quickstart](https://github.com/dockersamples/sbx-quickstart) | a first run | 2026-07-01 |

## Evidence behind this skill

| Resource | Read it for | Last activity |
|---|---|---|
| [ffroliva/sbx-team-kit](https://github.com/ffroliva/sbx-team-kit) | community. FINDINGS, bench, the fleet case in `docs/`, UPSTREAM, kits, and a script per finding | 2026-11-03 |
| [shelajev/sbx-skill](https://github.com/shelajev/sbx-skill) | independent sbx skill | 2026-09-14 |

## Community

| Resource | Read it for | Last activity |
|---|---|---|
| [ajeetraina/awesome-docker-sbx](https://github.com/ajeetraina/awesome-docker-sbx) | the curated list and a CLI cheatsheet. Check commands against `--help` | 2026-10-25 |
| [dvdksn/kits-cookbook](https://github.com/dvdksn/kits-cookbook) | example kits; check the kit format against the spec | 2026-04-29 |
| [maxkrivich/sbx-toolkit](https://github.com/maxkrivich/sbx-toolkit) | shareable templates and one-command startup | 2026-04-10 |
| [geut/sbx-shell-pi](https://github.com/geut/sbx-shell-pi) | a custom template image | 2026-11-04 |
| [dirien/herdr-sbx-plugin](https://github.com/dirien/herdr-sbx-plugin) | one microVM per agent, from a plugin | 2026-09-13 |
| [mattjohnson/orca-sbx-recipes](https://github.com/mattjohnson/orca-sbx-recipes) | one microVM per project, from a plugin | 2026-09-09 |
| [restuhaqza/deepagents-sbx](https://github.com/restuhaqza/deepagents-sbx) | sbx as an agent framework's sandbox backend | 2026-11-03 |
| [karanverma/sbx-ai-eval-kit](https://github.com/karanverma/sbx-ai-eval-kit) | runtime evidence patterns | 2026-09-01 |

None of the community projects was run here.
