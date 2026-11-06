---
type: Knowledge
title: Contributor pull requests
description: Run a pull request from outside the project in one box, with no secrets, after checking that exact commit, from a host or from CI.
tags: [sbx, use-case, trust, security, review]
status: beta
date: 2026-11-06
state: tried-once
trust: untrusted
source: measured on a target project, not independently reproducible, one real fork's pull request in one box, sbx 0.51.0
---

# Contributor pull requests

A community project receives pull requests it cannot vouch for. Their code runs in one box, with no secrets, and comes back
as results only. A member's pull request can run as trusted: that is your configuration, through
[the rules](../reference/trust.md).

**Steps, from a host:**

1. `sbx_trust.py check --repo o/r --pr N --sha S`, with [the token](../reference/github-token.md). Without one, the verdict
   stays untrusted; the fleet can still run it under untrusted limits.
2. `sbx_fleet.py --config docs/sbx.md --repo <base-repo-url> --sha S --pr N --ttl-minutes 20 --minutes 10 --expect-tests <base-count> --out <empty-dir>`.
   `--repo` is the base repository, not the fork; the fleet checks the commit again. Take the expected count from the base branch,
   since the PR controls its own tests. `--expect-tests` also applies to untrusted runs.
3. Read `<out>/verdict.json` (`--out` selects the folder; otherwise the fleet creates a temporary one). Treat box output as data.
4. After a push, the sha changes: check again.

**Needs:** an account whose default is deny-all, with no entry on its own allow list that names no host, and no global secret
that an allowed host could reach, which rules out a global `github` secret; `repo` in the adoption file; a public clone; `allow`
naming each host. Run from a checkout of your default branch, never from the contributor's branch.

**What the level does to your flags.** The fleet runs at the level found, or refuses before any box when the request breaks that
level's limits, exit 2. So a run that passes a secret, or asks for more than one box, is refused the moment its commit is
untrusted, which is also what a push between check and run looks like: read that exit 2 as superseded, not as red. `sbx_onboard.py`
writes a file that takes no secret for a public project, and for one whose visibility it could not read, so a stranger's pull
request runs untrusted with no edit once `command` is real and the account is deny-all. A private repository's file clones with a
token, which an untrusted run may not hold: its pull requests from anyone unproven are refused, by design. From a host, give a
member's run its secret with flags. The CI templates below do not: they serve a public repository only.

## In CI

Both templates are under [`templates/`](../../templates/github-pr-target.yml): copy them into `.github/workflows/` on your
default branch. **What is unsafe is running pull request code in a privileged job**, and this split never does.

| | `github-pr-target.yml` | `github-pr.yml` |
|---|---|---|
| Trigger | `pull_request_target`, from your default branch's workflow | `pull_request` |
| Holds | the read-only token, your Docker sign-in | nothing |
| Runs on the runner | your default branch and the pinned skill, never pull request code | the pull request's code |
| Decides | `sbx_trust.py check`, on rules read from the default branch | nothing |
| Pull request code runs | in a box that clones the exact sha | on a GitHub-hosted runner |

A fork's `pull_request` run gets no secret, so it has no token for the check and no way to sign in to sbx. That is why the half
that drives boxes needs the privileged trigger, and why it may check out nothing a pull request controls. GitHub's page says
this directly: [the checked-out code must only ever be inspected as data](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/security/securely-using-pull_request_target.md).

Because the workflow checks out only the default branch, the rules cannot come from a pull request: not its own, and not
another's, which closes the gap in [run from your default branch](../reference/trust.md#run-from-your-default-branch). What
comes back from a box does reach the runner, as data: an exit code and JUnit, read by the capped archive reader, and never run.

Two facts from GitHub decide the setup, read at one commit of its docs:

- `pull_request_target` runs [regardless of approval settings](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/data/reusables/actions/workflow-run-approve-public-fork.md). The spend control for a stranger is the `sbx-external` environment's required reviewers: a person approves before a box is paid for.
- GitHub's [default event policy](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/security/securely-using-pull_request_target.md#default-policy-for-pull_request_target) blocks this trigger in public repositories, enforced from 2 December 2026. A public project must create an event policy that allows it, or the workflow does not start.

**Set up the environments by hand, before any secret goes in.** GitHub creates an environment a job names with no protection, and
an environment's secrets are [available to workflow jobs that reference the environment](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/workflows-and-actions/deployments-and-environments.md#L103),
from any branch, unless a rule says otherwise:

- On `sbx-decide`, `sbx-trusted` and `sbx-external`, set **Deployment branches and tags** to **Selected branches and tags**, your
  default branch only ([GitHub's options](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/workflows-and-actions/deployments-and-environments.md#L50)).
  The rule is matched against `GITHUB_REF`, which for `pull_request_target` is the default branch, so the templates still run.
  Without it, anyone with write access, or whoever steals their token, pushes a branch whose job names `sbx-trusted`, and reads
  `DOCKER_PAT` with no review and no pull request.
- Give `sbx-external` its required reviewers before `DOCKER_PAT`. They are the only spend control for a stranger's push, and
  nothing in the templates can see whether they are set. `max_usd` in the adoption file bounds each run, not the number of runs.
- Require a review to merge to the default branch, with CODEOWNERS on `docs/sbx.md` and `.github/workflows/`: the rules a member
  cannot add themselves to hold only while no member can rewrite that file alone.
- Take `SBX_SKILL_SHA` from a commit on this skill's default branch or a release tag, read on its own repository, never from a link
  someone sent. GitHub serves a fork's commit under the parent's name, so both jobs refuse any commit off those.

`--project <name>-pr<N>` is the per-pull-request sweep: box names carry it, so `--sweep-only` with it touches that pull request's
boxes and no other live run's of this repository. The name keeps 20 characters of the repository's: two repositories on one
account whose names share those, and a pull request number, sweep each other's boxes, so give each its own account or a shorter name. Exit 0 green, 1 red, 2 refused or superseded, 3 no verdict. Keep this as an extra check, not a
required one, until a real fork has run through the pair.

## Signing in with no person there

Docker documents this for CI, on [cloud sandboxes](https://docs.docker.com/ai/sandboxes/cloud/#sign-in-from-the-cli) and
[run sandboxes in CI](https://docs.docker.com/ai/sandboxes/workflows/automation/), and `sbx login --help` on 0.51.0 shows it:

```bash
echo "$DOCKER_PAT" | sbx login --username <your-docker-id> --password-stdin
```

A personal access token of the subscribed account, with at least Read scope. `sbx --cloud diagnose` checks the sign-in, the cloud
API and account access, and needs no local daemon. The template installs sbx with the
[Ubuntu steps of its releases](https://github.com/docker/sbx-releases/blob/2329d12106fee653c0890152947fdd827e00cfd0/README.md#apt-ubuntu),
and signs out at the end, because with no keychain the token may rest on disk.

**Unverified until run.** No CI job has signed in this way here: the route is Docker's, not measured. Not known: that Read scope is
enough for `--cloud` creates and scoped secrets, since Docker states it on the page about local sandboxes; that the package installs
and `--cloud` works on a GitHub-hosted runner with no KVM group, which Docker's "cloud execution without local virtualization"
suggests and does not promise. A token belongs to a person and leaves with them: use a machine account, which also holds no global
secret and whose spend is a ceiling you accept. An organization access token is documented for Docker Hub, not for sbx: not tried.

## What the box does not protect

An agent in a box has `sudo` ([finding](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L193)). The box
isolates your host and credentials; it does not make the code's own report true. A green result from an untrusted run says that
this code, which also wrote the tests and the report, claims they passed. It is no proof they ran.

## Evidence

Tried once, on a target project: one real fork's pull request ran through `sbx_fleet.py --pr` on 0.51.0, 2026-11-06, on an earlier tree: level untrusted, rc 0, `--no-junit`, a one-line command, no log back.

**Unverified:** both templates on GitHub, the sign-in above, a test suite from a real fork, `pull/N/head` under load, and a member's
trusted run through `--pr`.
