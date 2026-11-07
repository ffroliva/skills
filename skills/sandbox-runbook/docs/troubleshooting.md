---
type: Knowledge
title: Troubleshooting
description: One entry per failure, searchable by its exact error text, with cause, fix, how to confirm, and the sbx version it was seen on.
tags: [sbx, troubleshooting, errors]
status: stable
date: 2026-11-05
---

# Troubleshooting

Search this page for the error text. `sbx_check.py` and `sbx_fleet.py` print the entry's anchor when they recognise an
error. "Measured" below means a run on a target project, not independently reproducible.

## Templates and kits

### shell-docker-unknown-agent

- **Symptom:** `sbx --cloud create shell-docker` fails at once.
- **Error:** `error: unknown agent "shell-docker"`
- **Cause:** `shell-docker` is not an agent.
- **Fix:** use `template: shell`, which runs Docker on 0.51.0.
- **Confirm:** `docker ps` answers in a `shell` box.
- **Seen on:** sbx 0.51.0, measured.

### shell-docker-unknown-template

- **Symptom:** `sbx --cloud create -t shell-docker` is refused.
- **Error:** `invalid_argument: unknown template: shell-docker`
- **Cause:** `-t` takes a template already in the cloud registry, and this one is not there.
- **Fix:** use `template: shell`.
- **Confirm:** the create prints `shell now ships as a kit; resolving docker.io/sbx/shell:latest`.
- **Seen on:** sbx 0.51.0, measured.

### kit-pull-limit

- **Symptom:** creating from the `sbx/shell-docker-image` kit fails during the pull.
- **Error:** `artifact graph exceeds the 276824064 byte pull limit`
- **Cause:** that kit's artifact is larger than the pull limit.
- **Fix:** use `template: shell`.
- **Confirm:** a `shell` create takes seconds, 8.6 s in the run measured.
- **Seen on:** sbx 0.51.0, measured.

## Network

### create-allow-network-prompt

- **Symptom:** an interactive `sbx --cloud create ... --allow-network <host>` without `--no-input` hangs or times out waiting on stdin in a headless run, while `sbx --cloud ls` prints `No sandboxes found`.
- **Error:** `NETWORK POLICY` followed by `Proceed? (y/N)` on stderr when `--no-input` is omitted. On sbx 0.51.0, passing global `--no-input` before `--cloud` with explicit `--allow-network` flags succeeds (`CREATE_RC=0`) and applies the allowlist only to the created sandbox without changing account-wide policy. `--no-input` is not a general auto-answer: a command that truly requires an interactive response fails with remediation.
- **Cause:** when the account's global network policy is `deny-all` with an empty allow list (`allow_networks: []`), an interactive `sbx --cloud create ... --allow-network <host>` without `--no-input` prompts for confirmation before creating the box. Because no box was created, an empty `sbx --cloud ls` (`No sandboxes found` or `[]` with `--json`, exit 0) means only an empty inventory, not an authentication failure ([#not-signed-in](#not-signed-in)), service outage ([#settings-platform](#settings-platform)), or quota refusal ([#vcpu-quota](#vcpu-quota)).
- **Fix:**
  1. Run bounded read-only diagnostics (`sbx diagnose --json`, `sbx --cloud policy ls --json`, `sbx --cloud ls --json`) and act only on actual errors (`status: fail` or non-zero exit).
  2. If a background `create` is stuck on the prompt, inspect the recorded PID and confirm its exact commandline or job record before stopping that PID ([Windows background stop](#windows-background-stop), [Windows host pitfalls](pitfalls/windows-host.md)); never kill by process name (`taskkill /IM`, `Stop-Process -Name`, `pkill`).
  3. Preferred on sbx 0.51.0: pass global `--no-input` before `--cloud` with explicit `--allow-network` flags, a unique `--name`, and `--ttl` (`sbx --no-input --cloud create shell --allow-network <host1> --allow-network <host2> --name <box> --cpus <n> --memory <mem> --ttl <ttl> --on-timeout delete --no-progress`). On sbx 0.51.0 this applies the allowlist to `<box>` only and leaves the account-level `deny-all` policy unchanged.
  4. Verified two-step per-sandbox fallback if a command or another `sbx` version reports that a required interactive response is missing under `--no-input`:
     - Create the box without `--allow-network`: `sbx --no-input --cloud create shell --name <box> --cpus <n> --memory <mem> --ttl <ttl> --on-timeout delete --no-progress`
     - Add the box-scoped allow list: `sbx --no-input --cloud policy allow network --sandbox <box> "<host1>,<host2>"`
  5. On cleanup, remove only the exact owned box and its scoped rules or secrets (`sbx --no-input --cloud rm -f <box>`, `sbx --cloud secret rm <secret> --sandbox <box> --force`); never run `sbx --cloud rm --all`, `sbx prune`, `sbx reset`, or `policy init allow-all`.
- **Confirm:** `sbx --cloud policy ls <box> --format json` (or `--json`) exits 0 and lists the allowed hosts under `allow_networks` with `"mode": "deny-all"` on `<box>`, while account-level `sbx --cloud policy ls --format json` (or `--json`) remains `"mode": "deny-all"` with empty `allow_networks` and `deny_networks`; after `sbx --no-input --cloud rm -f <box>`, `sbx --cloud ls` prints `No sandboxes found` (or `[]` with `--json`).
- **Seen on:** sbx 0.51.0, measured (2026-11-07 probes: interactive `sbx --cloud create ...` without `--no-input` and six `--allow-network` flags timed out at `NETWORK POLICY ... Proceed? (y/N)` with `No sandboxes found`; `sbx --no-input --cloud create ...` with all six `--allow-network` flags returned `CREATE_RC=0`, `policy ls <box> --format json` showed all six rules on `<box>` only while account-level `policy ls --format json` remained `deny-all` with empty allow/deny lists, and `rm -f <box>` returned 0 with `No sandboxes found`; the two-step `--no-input` create without `--allow-network` plus `policy allow network --sandbox <box>` was also separately verified on 0.51.0).

### deny-all-403

- **Symptom:** `curl`, a package install or a pull fails in the box; other hosts work.
- **Error:** `CONNECT tunnel failed, response 403`
- **Cause:** the account's default is deny-all and the host is not allowed.
- **Fix:** add the host to `allow` in the adoption file, from [the egress table](reference/network-policy.md).
- **Confirm:** rerun; `sbx policy log` names the host as allowed.
- **Seen on:** sbx 0.51.0, measured.

## Account

### not-signed-in

- **Symptom:** every cloud command fails, and `sbx_check.py` reports `account`.
- **Error:** `not signed in to Docker`
- **Cause:** no login, or a TLS filter breaking it. This exact text was not captured in a log here. An exit-0 `sbx --cloud ls` printing `No sandboxes found` (or `[]` with `--json`) is an authenticated empty inventory, not a sign-in or service failure ([#create-allow-network-prompt](#create-allow-network-prompt)).
- **Fix:** check `sbx diagnose --json` (`Authentication` and `Global network policy` checks) first; if not signed in, run `sbx login`. Behind a TLS filter, set `GODEBUG=tlsmlkem=0` first. With no person there, [sign in with a token](use-cases/contributor-prs.md#signing-in-with-no-person-there).
- **Confirm:** `sbx diagnose --json` reports `Authentication: pass` (`authenticated`) and `sbx --cloud ls --json` prints a JSON list (`[]` when no boxes exist).
- **Seen on:** sbx 0.50.1; `sbx diagnose --json` verified on sbx 0.51.0 (2026-11-07).

### concurrent-create-429

- **Symptom:** one of several parallel creates fails.
- **Error:** `status code: 429`
- **Cause:** concurrent creates hit a rate limit, and the CLI does not retry.
- **Fix:** `sbx_fleet.py` staggers creates and retries a real 429 up to five times. Raise `stagger_s` if it persists.
- **Confirm:** the fleet reports every box.
- **Seen on:** sbx 0.50.0.

### vcpu-quota

- **Symptom:** a create is refused, or a fleet stops part-way.
- **Error:** `Maximum running vCPU quota reached`
- **Cause:** live boxes plus this run exceed the account's limit. It is per account.
- **Fix:** wait for or remove live boxes, or lower `boxes`. Never retry in a loop: exit 3 says nothing about the code.
- **Confirm:** `sbx_check.py` passes `quota`.
- **Seen on:** sbx 0.50.0.

### settings-platform

- **Symptom:** a kit create fails now and then.
- **Error:** `settings platform construction failed`
- **Cause:** unknown; a transient failure of the service.
- **Fix:** `sbx_fleet.py` retries it.
- **Confirm:** the fleet reports every box.
- **Seen on:** sbx 0.50.0, measured.

## Lifecycle

### create-killed-still-billing

- **Symptom:** a box shows up in `sbx --cloud ls` after its `create` was killed or timed out.
- **Error:** no error: the client is gone.
- **Cause:** the server finishes a create whose client died.
- **Fix:** `sbx_fleet.py` looks again before exiting. After a hard kill, run `sbx_fleet.py --project <name> --sweep-only`.
- **Confirm:** `sbx --cloud ls --json` prints `[]`.
- **Seen on:** sbx 0.50.0.

### scoped-secret-outlives-rm

- **Symptom:** a secret scoped to a removed box is still listed.
- **Error:** no error: `sbx --cloud secret ls --json` still shows the box's name in `scope`.
- **Cause:** with `--cloud`, `rm` leaves scoped secrets, and the next box with that name receives them.
- **Fix:** `sbx --cloud secret rm <name> --sandbox <box> --force`, or `--sweep-only`.
- **Confirm:** `sbx --cloud secret ls --json` prints `{"secrets": []}`.
- **Seen on:** sbx 0.50.1 and 0.51.0, measured.

### box-name-in-use

- **Symptom:** the fleet refuses to start, naming a box or a leftover secret.
- **Error:** `a live box is already named` or `leftover secret`
- **Cause:** the run's random part repeated, or an earlier run left a scoped secret. Reusing the name would hand that secret to a new box.
- **Fix:** for a leftover, run `--sweep-only`; for a live box of another run, wait and rerun, which draws a new hash.
- **Confirm:** the fleet starts.
- **Seen on:** sbx 0.51.0, by design of this script.

### sbx-ls-shows-nothing

- **Symptom:** `sbx ls` shows nothing while a cloud box is billing, so a proof that nothing is left proves nothing.
- **Error:** `No sandboxes found`
- **Cause:** with no `--cloud`, `sbx ls` lists local sandboxes only. `sbx secret ls` is the same.
- **Fix:** use `sbx --cloud ls` and `sbx --cloud secret ls`.
- **Confirm:** `sbx --cloud ls --json` prints `[]`.
- **Seen on:** sbx 0.51.0, measured.

### red-in-box-green-on-ci

- **Symptom:** tests fail in a box and pass on CI at the same sha.
- **Error:** your project's own: 40 failures on a target project read `uncommitted changes`, from a throwaway git repository the tests built in a temporary folder.
- **Cause:** a box is not your CI image: it runs a hardened Debian 13 kit on sbx 0.51.0, with its own git config, user, filesystem and environment. On that project the root cause was not found: treat the failure as a finding about the environment, not as a flaky test, and never rerun to clear it.
- **Fix:** read the same facts in both places and diff them. Run the same lines as a step on CI and as a box's command, writing to `$OUT`: `id`, `umask`, `git --version`, `git config --list --show-origin`, `df -T .`, and the variable names only, `env | cut -d= -f1 | sort`: a value can be a token, and the log keeps it ([entry](#test-printed-the-environment)). Then run one failing test with its temporary folder kept. Look first at what the test assumes: a global git setting such as `core.fileMode` or `core.autocrlf`, a tracked file's mode on that filesystem, a home directory, the `CI=true` the box script sets, and the git version (measured once: a test that copies a linked worktree and runs `git worktree repair` left its template dirty on git 2.47.3, the box's; CI had 2.56.0). Do not read a red box as a verdict on the code until this is explained, and do not hide it with a skip.
- **Confirm:** the same test passes in a box after one change, and fails again without it. Until then CI stays the verdict for those tests.
- **Seen on:** sbx 0.51.0 with Debian 13, 5 boxes, one run, on a target project, not independently reproducible. Root cause not found.

### test-printed-the-environment

- **Symptom:** a failing test's output, in a terminal, a box's `$OUT` or a CI log, holds every environment variable, a token among them.
- **Error:** your test runner's own, for example pytest's `where None = <bound method Mapping.get of environ({...})>` under an `assert`.
- **Cause:** the assertion held an expression on `os.environ`, such as `assert os.environ.get("X") == "1"`. A failing assert prints the objects it compared, so pytest printed the whole mapping. `print(os.environ)` and `env | sort` do the same.
- **Fix:** a test never prints the environment. Bind the one value you check to a name, `value = os.environ.get("X")`, then assert on `value`. Print variable names, never values. Treat the leaked value as exposed: rotate it, and scrub the log.
- **Confirm:** the test fails once on purpose and its output holds no other variable. This repository's own tests are held to it by a scan in `tests/test_field_log.py`.
- **Seen on:** a target project's speed run, 2026-11-06, one red test, caught in a local log before any push.

### custom-secret-no-host

- **Symptom:** a custom secret stopped working after an upgrade.
- **Error:** no error: the box sends its placeholder.
- **Cause:** from 0.51.0 a custom secret with no destination host substitutes nothing.
- **Fix:** add `--host`; with `--cloud` it takes exact DNS names.
- **Confirm:** `sbx --cloud secret ls --json` lists `hosts`, and the request is authorised.
- **Seen on:** sbx 0.51.0 release notes.

### stale-snapshot

- **Symptom:** `sbx_check.py` warns `drift`, or a weekly issue opens.
- **Error:** `version: the snapshot and sbx differ; read the release notes between the versions`
- **Cause:** sbx moved on from the CLI snapshot.
- **Fix:** follow "When this skill goes stale" in SKILL.md.
- **Confirm:** `sbx_drift.py check` exits 0.
- **Seen on:** sbx 0.51.0, by design of this script.

### windows-background-stop

- **Symptom:** a backgrounded fleet was stopped, and its boxes keep billing.
- **Error:** no error: nothing ran.
- **Cause:** on Windows a background stop or a closed terminal is `TerminateProcess`, which runs no clean-up.
- **Fix:** run the fleet in a foreground terminal where possible, stop it with Ctrl+C or Ctrl+Break, and after a hard kill run `--sweep-only`. When running detached or in the background on Windows, start the process hidden (`CREATE_NO_WINDOW` or `-WindowStyle Hidden`) with an explicit timeout and stdout/stderr redirected to a log file, and record the exact PID and box names at launch ([Windows host pitfalls](pitfalls/windows-host.md)). Before stopping or restarting a stalled background job (such as a `create` blocked on [#create-allow-network-prompt](#create-allow-network-prompt)), inspect the recorded PID and verify its matching commandline or job record; stop only that exact owned PID and remove only the exact owned boxes (`sbx --no-input --cloud rm -f <box>`), never killing by image name (`taskkill /IM`, `Stop-Process -Name`, `pkill`). The TTL with `--on-timeout delete` is the only other guard. The fleet prints `the box is gone`, goes red and leaves nothing when a running box is removed (sbx 0.51.0, one run).
- **Confirm:** the recorded PID has exited, `sbx --cloud ls --json` prints `[]`, and `sbx --cloud secret ls --json` shows no leftover scoped secret for the owned box.
- **Seen on:** sbx 0.50.1 on Windows 11, measured. Again on 0.51.0 (gate 6, one run): `taskkill /F` on the fleet left the box running and its scoped secret in place; the box was deleted by its own TTL (4 minutes, `--on-timeout delete`) about 4 minutes after create; the secret stayed until `--sweep-only` removed it. CTRL_BREAK to the fleet's process group ended it with exit 130, the boxes removed within 9 s and an empty account. A bare CTRL_BREAK used to end it with no clean-up (fixed).

## Trust

### untrusted-asked-for-secret

- **Symptom:** the fleet refuses with exit 2 and creates nothing.
- **Error:** `an untrusted run takes no secrets`
- **Cause:** the commit is not proven trusted, and the untrusted profile takes no secrets.
- **Fix:** an untrusted PR that needs `API_TOKEN` cannot run those tests in the box. Rerun with no secret; report the dependent
  tests as **not run**, not red. Never paste a token into the command. Add a trust rule only when the author and exact commit
  qualify as trusted.
- **Confirm:** with no secret flag, the run proceeds at level `untrusted`; secret-dependent tests remain unrun.
- **Seen on:** this script.

### pr-changed-after-check

- **Symptom:** a member's pull request comes back untrusted.
- **Error:** `"rule": "sha-changed"`
- **Cause:** the decision is about one exact commit, and the head moved.
- **Fix:** check again with the new sha.
- **Confirm:** `sbx_trust.py check` prints the new sha as `head_sha`.
- **Seen on:** this script.

### adoption-file-changed

- **Symptom:** a member's pull request comes back untrusted.
- **Error:** `"rule": "adoption-file-changed"`
- **Cause:** the pull request edits, renames or replaces the file that holds the trust rules, its folder, or a local kit the run uses, so it cannot vouch for itself.
- **Fix:** review the edit, merge it, and check the next commit.
- **Confirm:** the rule changes on a pull request that leaves those paths alone.
- **Seen on:** this script.

### adoption-file-not-in-repo

- **Symptom:** a member's pull request comes back untrusted.
- **Error:** `"rule": "adoption-file-not-in-repo"`
- **Cause:** the `--config` file sits in no git repository, so nothing can show the pull request left its rules alone.
- **Fix:** pass the adoption file from a clone of the project.
- **Confirm:** the rule changes to one about the pull request.
- **Seen on:** this script.

### repo-mismatch

- **Symptom:** a run you expected to be trusted comes back untrusted, and a secret is refused.
- **Error:** `"rule": "repo-mismatch"`, or `repo-not-declared`
- **Cause:** trust belongs to the repository named by `repo` in the adoption file. `--repo` names another one, such as a fork, or the file names none.
- **Fix:** pass the project's own URL, or rerun `sbx_onboard.py`, which adds `repo` from `origin`. A fork's code stays untrusted: that is the point.
- **Confirm:** `verdict.json` shows the rule you expected.
- **Seen on:** this script.

### own-work-needs-repo

- **Symptom:** the fleet refuses with exit 2 and creates nothing, on a file that says `own_work: trusted`.
- **Error:** `own_work: trusted needs `repo: <owner/name>``
- **Cause:** with no readable `repo`, nothing is trusted. Running on as untrusted would be safe, and would spend money on a run that brings back no log and takes no secret, which is never what that file meant.
- **Fix:** add `repo: <owner/name>` to the sbx-config block, or rerun `sbx_onboard.py`, which adds it from `origin`.
- **Confirm:** `sbx_check.py` passes `fleet-plan`, and the run starts at level `trusted`.
- **Seen on:** sbx 0.51.0, measured once: a box billed 76 s before anyone read the level line.

### global-secret-exposed

- **Symptom:** an untrusted run stops with exit 2 and creates nothing.
- **Error:** `global secret github can reach a host this box may reach`
- **Cause:** the proxy injects a global secret into every box, on requests to its service's hosts. The box's code could act as that identity on a host the run allows.
- **Fix:** remove the secret from the account (`sbx --cloud secret rm <name>`), scope it to the boxes that need it, or run on an account that holds none. Removing the host is no way out for `github`: the box clones from it.
- **Confirm:** `sbx --cloud secret ls --json` shows no such global row, and `sbx_check.py` passes `global-secrets`.
- **Seen on:** this script; the injection itself on sbx 0.50.0.

### token-missing-permission

- **Symptom:** `sbx_trust.py` reports `host-error:403` or `host-error:404`, and everything is untrusted.
- **Error:** `Resource not accessible by personal access token`
- **Cause:** the token lacks a permission, or does not cover this repository. GitHub answers 404 as well as 403 for this.
- **Fix:** run `sbx_trust.py doctor`, then add what it names: [the guide](reference/github-token.md#permissions).
- **Confirm:** `doctor` exits 0.
- **Seen on:** GitHub's docs; not exercised with a fine-grained token.

### token-expired

- **Symptom:** `sbx_trust.py` reports `host-error:401`.
- **Error:** `Bad credentials`
- **Cause:** the token expired or was revoked.
- **Fix:** create a new one: [the guide](reference/github-token.md#expired-token).
- **Confirm:** `doctor` exits 0.
- **Seen on:** GitHub's docs; not exercised with a fine-grained token.

### token-org-approval

- **Symptom:** a new token reads public data, and private data answers 403 or 404.
- **Error:** the token is marked `pending` in the organization's settings.
- **Cause:** an organization can require approval of fine-grained tokens, and until then the token reads public resources only.
- **Fix:** ask an organization owner to approve it: [the guide](reference/github-token.md#organization-approval).
- **Confirm:** `doctor` exits 0.
- **Seen on:** GitHub's docs; not exercised.
