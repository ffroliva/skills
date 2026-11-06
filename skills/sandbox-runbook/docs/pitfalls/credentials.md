---
type: Knowledge
title: "Pitfalls: credentials"
description: How scoped secrets behave across create, rm and the TTL reaper, and what to do about it.
tags: [sbx, pitfalls, credentials]
status: stable
date: 2026-11-05
---

# Pitfalls: credentials

| Id | Pitfall | Cost | Fix | sbx |
|---|---|---|---|---|
| [8.1](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L360) | A cloud scoped secret outlives `rm` and the TTL reaper; the next box with that name receives it: 6/6 cloud, 0/3 local | a live credential with no expiry | unique names; `secret rm --sandbox <box> <service> --force` after `rm`; `sbx_fleet.py` does both | 0.50.1; outlives `rm` confirmed on 0.51.0 |
| [8.3](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L397) | A scoped secret added to a running box does not reach it | credential absent in running box | fail safe: set it before `create` | measured on sbx 0.51.0 (2026-11-06, cloud, custom secret): not injected within 60 s; set before `create`, it did; restart case not measured |
| [8.3](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L397) | `--command` with `--cloud` prompts, and the fetch falls back to a global secret | wrong identity, silently | pipe the value on stdin; check `secret ls` | 0.50.0 |
| [8.4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L403) | `secret set` from stdin overwrites with only `Updated` | a global secret replaced | list before you set | 0.50.0 |
| [section 4](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L179) | A non-interactive `create` of a kit with a required credential warns, and creates the box without it | a box that fails later | set the secret first | 0.50 |

Measured: with a secret set before `create`, a private fetch took 5 s with no token in `.git`,
`~/.gitconfig` or the environment. Only the proxy holds it.

Mask token shapes in logs you keep. A global `github` secret on the account is reachable by any box that may reach
github.com, so `sbx_fleet.py` refuses an untrusted run on such an account, and `sbx_check.py` says so first. See
[trust levels](../reference/trust.md) for which secrets count.

Set host variables with `export NAME=value` (or the CI environment) so `sbx_fleet.py` can read them. It removes `GH_TOKEN` and
the `--secret-env` variable from the environment passed to sbx, then sends the credential on stdin; `--env NAME` is the separate,
plain-text-in-the-box route.

## A token for a service sbx does not list

`sbx secret set` knows a fixed list of services (seen on sbx 0.51.0: anthropic, copilot, cursor, devin, droid, github,
google, groq, mistral, nebius, openai, openrouter, xai). A package-index or API token for anything else has two routes.
Prefer the first.

1. **`sbx secret set-custom`** (marked experimental in its help; read from `--help` on sbx 0.50.1 and 0.51.0). The fleet's
   `--secret-service` accepts only one service, so a private token clone (`github`)
   and a custom API token cannot both use this route in one fleet run. Use a public clone, or run that job in CI where both
   credentials can be provided safely. The box
   sees a placeholder, and the proxy swaps in the real value on requests to the hosts you name, so the value never enters
   the box. `--host` names the destinations (without one, nothing is substituted: a breaking change in 0.51.0, see below),
   `--sandbox` scopes it to one box, and `--value-stdin` (0.51.0) keeps the value out of argv:
   `printf '%s' "$TOKEN" | sbx --cloud secret set-custom --sandbox <box> --host <exact.host> --env TOKEN --value-stdin`.
   Measured on a target project, not independently reproducible (sbx 0.51.0, 2 boxes, one run): this works with `--cloud`, set before `create`; the box sees `sbx-cs-<16 chars>` and the proxy sets the
   header, so the placeholder itself is not substituted. It outlives `rm`, so the fleet deletes it: [entry](../troubleshooting.md#scoped-secret-outlives-rm).
   Through the fleet (gate 8, 2026-11-05, sbx 0.51.0, one run, a fake value): `sbx_fleet.py --secret-service custom:<exact host>:<ENV> --secret-env <host variable>` sets it before `create`, allows the host for egress, and deletes it after `rm`. The box printed `ENV=sbx-cs-<16 chars>`, a request from the box to `httpbin.org` was echoed back with `Authorization: Bearer <the fake value>`, the value was in no environment variable of the box, a request to a host that is not allowed failed with 403, and `secret ls` was empty afterwards. List the whole `custom:<host>:<ENV>` string in `allowed_secrets`.
   On sbx 0.51.0 (measured 2026-11-06, cloud): with a custom secret, a scoped secret added to a running box did not reach it within 60 s (no header injected, variable not in environment); set before `create`, it did (header injected, placeholder in environment). Whether restarting a box picks it up was not measured.
   Seen on the way: a fake value for the `github` service scoped to a box made the public `git clone` in that box fail (`clone-failed`), because the proxy injected the bad credential. Use a real token for `github`, or a different service name.
   Limit: it works only in request headers. A tool that reads the token from a file or an environment variable and signs
   or encodes it itself (HTTP Basic auth, a signed URL) sends the placeholder. With `--cloud` the help says `--host`
   takes exact DNS names only and the proxy sets `--header` (default `Authorization: Bearer %s`; `--format` changes it).
2. **`sbx_fleet.py --env NAME`**, which passes `-e NAME` to `create` (the help for `-e`: a bare KEY takes the value from
   the current environment, so the value is never in argv). The value is then in the box's environment in plain text:
   every process in the box can read it, and send it to any host the box may reach. Use a read-only, short-lived token,
   `--allow` only the hosts it needs, and expect it to be gone when the box is removed (not measured). Seen on sbx 0.51.0 for `-e NAME=value`: the exec process saw the variable. The bare `-e NAME` form the fleet passes was seen working under `--cloud` (gate 8, sbx 0.51.0, one run). The fleet makes a miss loud: a box whose variable is empty goes red with the variable's name. This script never writes the value to a log, a script or an argument.
   Your command's own output returns as it is: a test that prints its environment puts the value in `$OUT`.

If neither fits, say so in your plan: the safe fallback is to run that step where the token already lives (CI), and leave
it out of the box.

| Fleet option | Value | Limit |
|---|---|---|
| `--secret-service` | `custom:<exact host>:<ENV>` | One service per fleet run; a private clone token and a custom API token cannot both use this option. |

For both credentials, use a public clone or run the job in CI. `export NAME=value` makes a host variable available to the fleet;
it strips that variable from sbx's environment and pipes the value to secret setup.

## Breaking changes by version

| Version | Change | What to do |
|---|---|---|
| 0.51.0 | A custom secret with no destination host no longer substitutes the credential | add explicit `--host` values, keeping the placeholder and other settings |
| 0.51.0 | `sbx cp` blocks symbolic links in mounted directories that escape to other host paths | copy real files, not links |
