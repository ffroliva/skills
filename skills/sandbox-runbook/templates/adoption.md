# Docker Sandboxes in {{TARGET_PROJECT}}

Read this file before any `sbx` work here. `sbx_onboard.py` writes it. A rerun refreshes the two marked tables and adds
missing settings; everything else, including your edits, stays. `sbx_check.py` validates it before a run.

## What the project needs

{{DETECTION}}

## Use cases

{{USE_CASES}}

Evidence state: `measured` has repeated runs, `tried-once` has one run, `untested-idea` has none.

## Settings

Edit these. `sbx_fleet.py --config docs/sbx.md` reads them; a flag overrides a value. No secret value belongs here.

{{CONFIG}}

- `own_work`: `trusted` says this project's own pushed commits, in `repo`, may run with the secrets in `allowed_secrets`. It needs `repo`: with none the fleet refuses. Anything else is untrusted: one box, no secrets, short TTL.
- `trust_roles`, `trust_team`, `trust_logins`: who is trusted on a pull request. No rule means nobody. This file decides, so a pull request that touches it stays untrusted. Run from your default branch: the skill's trust notes say why.
- `repo`: the one repository these rules speak for, written from `origin`. Any other `--repo`, such as a fork, is untrusted and gets no secret. No value means nothing is trusted.
- `network_policy`: the default this project needs of your account; an untrusted run needs `deny-all`. Declare it here, and the fleet and `sbx_check.py` also read the account with `sbx --cloud policy ls --json`: an untrusted run stops when the account says otherwise, or when its own allow list holds an entry that names no host.
- An untrusted run also stops if the account holds a global secret that could reach a host in `allow`, one on the account's list, or `github.com`. `sbx_check.py` names it as `global-secrets`.
- `boxes`, `secret_service`: a project that can take a stranger's pull request starts with one box and no secret, so that run works as it is. Pass `--boxes N` on your own trusted run, and a secret's flags only where the level is known.
- `quota_vcpu`: your account's limit. It is declared, not read: no sbx command reports the quota.
- `max_usd`, optional, add it yourself: a run whose worst case, every box billing to its TTL, costs more is refused. `--max-usd` overrides it.
- `minutes`: the deadline for a run. Keep it below `ttl`, or the box is deleted before partial results are collected.
- `allow`: hosts a box may reach, on top of git. A deny-all account refuses everything else with a 403.
- `want`: use cases the team needs although detection does not see them yet. Kept on rerun.
- A `<set: ...>` in `command` is a decision for a person; `sbx_check.py` fails and `sbx_fleet.py` refuses until it is replaced.
- `command`: runs in a clone of the commit, with `$SHARD`, `$SHARDS` and `$OUT` set. Write JUnit XML to `$OUT`.

{{TRUST_STEP}}

## Owners

| Decision | Owner |
|---|---|
| Spend limit per month | |
| Who may start a fleet | |
| Who rotates the clone token | |

## Notes
