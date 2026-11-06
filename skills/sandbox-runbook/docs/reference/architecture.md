---
type: Knowledge
title: Architecture
description: The pieces of the sbx skill's code, which interfaces are public, the dependency rule and what enforces it.
tags: [sbx, architecture, hexagonal]
status: stable
date: 2026-11-05
---

# Architecture

Ports and adapters, in Python 3.12 standard library only. The installed plugin runs a script by path with no install
step, so the package sits next to the scripts and `sys.path` already resolves it.

## Pieces

| Piece | Path under `scripts/` | Holds | May import |
|---|---|---|---|
| Domain | `sbxlib/domain/` | trust levels, run profiles, box names, the box script, verdicts, shard plans, adoption-file values, the known-error table | a short list of pure stdlib modules |
| Ports | `sbxlib/ports.py` | `typing.Protocol` interfaces and their exceptions | domain |
| Application | `sbxlib/app/` | the use cases: run a fleet, check a PR, doctor, check a project, drift | domain, ports |
| Adapters | `sbxlib/adapters/` | the `sbx` CLI, the `gh` CLI, git, processes, files and archives, the clock | domain, ports |
| Entry points | `sbx_*.py`, `validate_skill.py` | argument parsing, wiring, printing; onboarding is `sbx_onboard.py` over `domain.onboard` | anything |

## The dependency rule

Dependencies point inward: entry points, then adapters and application, then ports, then domain. The domain and the
application import only a short list of pure stdlib modules, no adapter, call no builtin `open` and read no environment.
`tests/test_architecture.py` enforces this on every run with an allow list, and a planted violation proves each rule still bites.

## Public interfaces

Everything here is a promise to a reader, and changes only with a note.

| Interface | Shape |
|---|---|
| CLIs | `sbx_detect`, `sbx_onboard`, `sbx_check`, `sbx_fleet`, `sbx_trust`, `sbx_shard`, `sbx_drift`: flags and exit codes |
| Adoption file | `docs/sbx.md`, its one `sbx-config` block below the `<!-- sbx:... -->` generated regions, its keys. A second block refuses, and tree data in a region is escaped |
| CI templates | `templates/github-pr-target.yml`, `templates/github-pr.yml` |
| JSON outputs | `sbx_trust check`, `sbx_shard plan`, `sbx_detect`, `sbx_drift check`, `verdict.json` |
| Fleet exit codes | 0 green, 1 red, 2 not runnable and nothing created, 3 no verdict (a box never ran, and none failed), 130 stopped |
| Box names | `<target-project>-<mode>-<NN>-<hash>`: `--sweep-only` parses them, so a `--label` stays out of them |
| Manifests | one per harness, all pointing at `skills/`. `scripts/check_versions.py` holds them to one version, one name and one copy of the skill |

`sbxlib` itself is private: nothing outside this repository imports it, and it can be reshaped freely.

## Ports

| Port | Real adapter | In tests |
|---|---|---|
| `CommandRunner` | `adapters.process.run_command`, which resolves each tool from absolute `PATH` entries | `tests/fakes.py`: `FakeSandbox`, `FakeGitHub`, `FakeGit` |
| `SandboxRuntime` | `adapters.sbx_cli.SbxCli` | the real adapter over `FakeSandbox` |
| `SecretStore`, `CliSurface` | `adapters.sbx_cli.SbxCli` | the real adapter over `FakeSandbox` |
| `RepoHost` | `adapters.gh_cli.GhCli` | the real adapter over `FakeGitHub` |
| `SourceControl` | `adapters.git_cli.GitCli` | the real adapter over `FakeGit` |
| `RunFiles` | `adapters.files.RunDirectory` | the real adapter on a temp folder |
| `Clock` | `adapters.clock.SystemClock` | `FakeClock` |
| `RunIdSource` | `adapters.clock.new_run_id` | a fixed id |

The fake replaces the process, never the adapter. So every test drives the real argv-building code, and `FakeSandbox`
refuses any flag absent from `references/cli-snapshot.json`. It also keeps state the way sbx 0.51.0 does: a scoped secret
outlives `rm`. `tests/test_contract.py` runs one suite against the fake, and against the real tool when `SBX_LIVE=1`. A
live run costs money, is off by default, and CI never sets it.

## Trust

The decision is a pure function of facts about one exact commit, and of the rules in the adoption file.
`TrustLevel` is an enum with two values, and anything not proven `TRUSTED` is `UNTRUSTED`, including an error, no
network, no `gh`, no token or an unknown value. Each level has a `RunProfile`, and `domain.fleet.refusals` refuses a
request that breaks it before any box exists. What only the account can answer, `SandboxRuntime.account_policy` and the
secret list, `run_fleet` refuses on the same way, before the first create.

Adoption-file rules are read on the host, and bound to the repository the file names. A pull request that touches a path a
decision reads is untrusted: `adapters.files.protected_paths` resolves those paths, because only the host knows where a file really
sits. `tests/test_trust_property.py` holds the decision to an oracle written from the numbered steps, over a fixed list of
seeds, and feeds junk to every GitHub route. `tests/mutants.py` breaks each safety rule on purpose, and a weekly job
runs it. See the [trust notes](trust.md).

## Sharding

`domain.shard` is language-agnostic: a *unit* is whatever one worker must keep together, a test file or a test class.
`plan` and `check` are pure. `sbx_shard.py` reads JUnit through an adapter and prints JSON. A project's own sharding is
reused: `check` takes any assignment in the same JSON. See the [sharding notes](sharding.md).

## What left the code, and why

| Gone | Why |
|---|---|
| hashed denylist, its loader, its test | it could be reversed; `validate_skill.py` reads an optional list from a path outside the repo |
| `shell-docker` mapping and its check | on sbx 0.51.0 `shell-docker` is refused three ways, and `shell` runs Docker |
| `sbx_junit.py` | merged into `sbx_shard.py check`; `--merge` had no reader |
| `name_prefix` | box names are now `<target-project>-<mode>-<NN>-<hash>` |
| per-box CPU and steal figures | nothing measured relies on them any more |
| `used_by`, the "added" list and the local help walk in drift | grep does the first; drift now walks the `--cloud` surface the scripts call |
| `frameworks`, `databases`, `KEYS` in detect | nothing read them |
| `MSYS_NO_PATHCONV` | Python starts `sbx.exe` directly, so MSYS path conversion never runs |
| `--sweep` before a run | replaced by `--sweep-only`, which also removes scoped secrets |
| manifest checks in the validator | `claude plugin validate` does this |
| `tests/test_docs.py`, the `*_more` sequel test files | they pinned wording, or were sequels rather than a design |
| `sbx_trust.py --adoption-path`, the `TrustSource` port | a second spelling of a path let two commands disagree; the port had one user and no test double |

## Left as recipes, on purpose

These do not earn code: one database per worker and one worker per vCPU (a test-fixture decision in the target project),
a weights table per platform (one `sbx_shard.py plan` output per platform), and selecting a shard's units at collection
time (each language's runner does it its own way).

