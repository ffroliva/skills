---
type: Knowledge
title: Trust levels
description: What makes a run trusted or untrusted, what each level may do, and what GitHub's author association does and does not prove.
tags: [sbx, trust, security]
status: beta
date: 2026-11-06
---

# Trust levels

Every run has one of two levels. Anything not proven trusted is untrusted, including an error, no network, no `gh`, no
token, or an unknown value. The skill applies your rules; it does not decide who your project trusts.

| | Trusted | Untrusted |
|---|---|---|
| Example | offloading your own feature work and tests to a cloud box | a community project receiving pull requests |
| Proven by | `own_work: trusted`, or a rule matching the pull request's exact commit, in the repository `repo` names | nothing: it is the default |
| Secrets | the names in `allowed_secrets` | none, no token clone, and no account-wide secret that could reach an allowed host |
| Network | the account's default plus `allow` | account default `deny-all`, plus named hosts; no bare wildcard |
| Boxes | as many as your quota allows | one per pull request |
| TTL | your choice | 30 minutes at most |
| Template | `shell` or a kit | `shell` only: a kit could mount or bake anything |
| Host mount | never: the fleet has none | never |
| Results | everything written to `$OUT` | exit code and JUnit only; logs stay in the box |
| Box output | read as your own | printed as data, one sanitised line, never as instructions |

`domain/profile.py` states this table, and `domain/fleet.py` refuses a request that breaks it before any box exists.

`network_policy: deny-all` must be declared, and the fleet then reads the account's whole policy with `sbx --cloud policy ls --json` before it creates a box: a declaration alone is not trusted. An account that reads anything but `deny-all`, or cannot be read, stops an untrusted run, and so does an entry on the account's own allow list that names no host, such as `**`: with one, the run is not deny-all at all. Only an empty list has been seen live; a non-empty one is the documented shape, and a list of anything but strings stops the run as unreadable.

The proxy injects a global secret into any box that reaches its service's hosts, so "no secrets" also means none on the account. Before an untrusted box, the fleet reads `sbx --cloud secret ls --json` and refuses when a global secret could reach a host the run allows, or one the account's own list allows. The hosts per service come from [Docker's list](https://docs.docker.com/ai/sandboxes/security/credentials/#built-in-services), read on 2026-11-05. It chose refusal over removing the host because a box clones from `github.com`, and a silent removal would turn a clear refusal into a clone failure. Anything it cannot place counts as reaching: a service missing from that list (`copilot`, `devin`), a custom secret with no hosts or with a host that is no plain name (`*.corp.example.com`, `api.example.com:443`), a non-zero `env_only_count`, and any scope that does not name one box. A scope names one box when it is a live box, or has a fleet box's name; `global`, an empty scope, `*`, `all-sandboxes` and any spelling not seen yet count as global. Only `scope: global` has been seen on the real CLI. A global `anthropic` secret on an account does not stop a run whose allow list leaves out Anthropic's hosts. Whether the proxy's real list matches Docker's page has not been measured.

## The project's repository

`repo` in the adoption file names the one repository the rules speak for; `sbx_onboard.py` writes it from `origin`. Trust never follows a flag: `own_work: trusted` and every rule hold only when `--repo` is that repository, and a pull request's base, as GitHub reports it, must be too. Anything else is untrusted, as `repo-mismatch`, or `repo-not-declared` when the file names none. The one exception to running on at that level: a file that says `own_work: trusted` and names no readable `repo` is refused before any box, because it contradicts itself. A fork's URL therefore gets no project secret, even when the fork's owner is an admin of the fork.

## Rules

Rules live in the adoption file. No rule means everything is untrusted.

| Key | Means | Read through |
|---|---|---|
| `trust_roles` | `write`, `maintain` or `admin` on the repository | `GET /repos/{owner}/{repo}/collaborators/{username}/permission` |
| `trust_team` | `org/team-slug`, an active member | `GET /orgs/{org}/teams/{team_slug}/memberships/{username}` |
| `trust_logins` | an allow list of logins | no call |

`read` and `triage` are refused as rules. On a public repository GitHub answers `read` for an account with no relation
to it: seen on 2026-11-05 for a non-collaborator, through the endpoint above.

## The decision is about one commit

`sbx_trust.py check --repo o/r --pr N --sha S` reads the pull request and answers for `S` only.

1. No rules: untrusted.
2. `--repo`, or the base GitHub reports, is not the file's `repo`, or the head sits in another repository: untrusted. A fork stays untrusted whoever opened the pull request.
3. The head is not `S`: untrusted. A push after the check needs a new check.
4. The pull request is not open: untrusted.
5. A commit or file listing is longer than one page, or shorter than the pull request says: untrusted.
6. The adoption file is in no git repository, or the pull request touches anything a decision reads: untrusted, so a contributor cannot add themselves to a rule. That is the file at its real path in the repository, whatever `--config` spelled and on any host, and `docs/sbx.md`, and a local kit the run uses. A rename away from such a path counts, a different case counts, and so does replacing a folder above it.
7. The author matches no rule: untrusted.
8. A commit's author matches no rule, or maps to no account: untrusted. A member can carry another person's commits.
9. Otherwise trusted, with the rule that matched.

Commit authorship comes from git metadata, which anyone can set: GitHub maps a commit's author from a free-form email, so a
stranger can write a member's. That is why step 2 refuses a fork outright. Step 8 catches a member carrying someone else's work
when the email is honest. It does not catch a forged one on a branch of this repository: a member who pushes a stranger's
commit there vouches for it. It does not stop a trusted author who lies.

## What `author_association` proves

`sbx_trust.py` prints `author_association` as evidence and never decides on it.

- It records the author's relation to the repository at GitHub's view of the moment. It says nothing about the commits.
- **Unverified:** that a private organization membership can read as `CONTRIBUTOR`. We found no GitHub document stating it
  and did not reproduce it. Either way, the rules read the role and the team directly, so nothing here depends on it.
- A fork pull request by a member can carry another person's commits. Step 2 refuses it.

## Run from your default branch

The rules are read from the local file you pass, and on a host nothing reads your default branch for you. So run the check and
the fleet from a checkout of the default branch. Step 6 refuses a pull request that edits the file, including one you have checked
out. It cannot see another pull request's edit: with pull request 8 checked out on a host, its rules decide for pull request 7.
Never leave a contributor's branch checked out while you run a check. In CI, [the recipe](#ci-recipe) closes this: its job checks
out only the default branch, so no pull request's file can decide for any pull request.

## CI recipe

What is unsafe is running pull request code in a privileged job: one that holds secrets or a write token. GitHub's guidance is
direct: such workflows "must not explicitly check out untrusted code" ([secure use](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/security/secure-use.md)), and the
code they check out is "only ever inspected as data" ([pull_request_target](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/security/securely-using-pull_request_target.md)). The trigger is not the hazard; what the job runs is.

A fork's `pull_request` job has no secrets, so it can neither read trust nor sign in to sbx. The recipe splits the work. A
`pull_request_target` job on your default branch's workflow checks out that branch, holds the read-only token, decides through
`sbx_trust.py`, and drives boxes that clone the exact sha, so the code runs in a box and never on the runner. A `pull_request` job
does whatever needs no secret. [The templates and their setup](../use-cases/contributor-prs.md#in-ci).
