---
type: Knowledge
title: The GitHub token for trust checks
description: Create the read-only fine-grained token that resolves whether a pull request is trusted, and where it may live.
tags: [sbx, trust, github, token]
status: stable
date: 2026-11-05
---

# The GitHub token for trust checks

`sbx_trust.py` needs a read-only token to tell an internal pull request from an external one. With no token every
verdict is untrusted, which is safe. Create one when you want members' pull requests to run as trusted.

The token stays on the host or in CI. It never enters a box and no box needs it: the check runs outside the sandbox that
runs contributor code. It is read-only, so it is not a CI write token.

## Create it

Prefer a fine-grained personal access token. `sbx_trust.py doctor --repo <owner/name>`, run with no token, prints this
link with your owner filled in:

```text
https://github.com/settings/personal-access-tokens/new?name=sbx-trust-check&target_name=<owner>&expires_in=90&pull_requests=read&metadata=read
```

1. Open the link. GitHub prefills the name, expiry and permissions ([URL parameters](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens.md)). The default expiry is 30 days; the link asks for 90.
2. Under **Resource owner**, pick the account or organization that owns the repository.
3. Under **Repository access**, pick **Only select repositories**, then this repository.
4. Check the permissions below, generate, and copy the value once.

## Repository access

The token must cover the repository, and its resource owner must be the repository's owner. A 404 on a repository you can
see in a browser usually means this ([GitHub's troubleshooting page](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/rest/using-the-rest-api/troubleshooting-the-rest-api.md)).

## Permissions

These are the endpoints the helper calls, and no more.

| Rule | Endpoint | Permission, from GitHub's docs |
|---|---|---|
| always | [`GET /repos/{owner}/{repo}/pulls/{n}`](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#get-a-pull-request) | Pull requests read (Contents read also works) |
| always | [`GET .../pulls/{n}/commits`](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-commits-on-a-pull-request) | Pull requests read |
| always | [`GET .../pulls/{n}/files`](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests-files) | Pull requests read |
| `trust_roles` | [`GET .../collaborators/{username}/permission`](https://docs.github.com/en/rest/collaborators/collaborators?apiVersion=2022-11-28#get-repository-permissions-for-a-user) | Metadata read |
| `trust_team` | [`GET /orgs/{org}/teams/{slug}/memberships/{username}`](https://docs.github.com/en/rest/teams/members?apiVersion=2022-11-28#get-team-membership-for-a-user) | organization Members read, only with a team rule |
| doctor | [`GET /repos/{owner}/{repo}`](https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#get-a-repository) | Metadata read |

Add `&members=read` to the link for a team rule. The organization must be the resource owner.

**What was verified, on 2026-11-05:** `sbx_trust.py check` and `doctor` ran against a real public pull request with an OAuth
token, and each repository endpoint answered with the fields the helper reads. The team endpoint answered 404 for a team that does not exist. The permission
column comes from GitHub's docs for each endpoint and the
[permissions table](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
**Unverified:** a real fine-grained token against `doctor`, including how it reports a missing Members permission. A
missing team membership and a missing Members permission both read as 404 here, so `doctor` names the permission as the
likely cause, and the verdict stays untrusted either way.

## Organization approval

If the organization requires approval of fine-grained tokens, a new token is `pending` until an organization owner
approves it, and until then it reads public resources only. Tokens made by organization owners are approved
automatically. Requiring approval is the default ([policy](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization.md)).

## Where it lives

- `GH_TOKEN` in the environment, or a CI secret mapped to `GH_TOKEN`. Only that variable: with none set, the helper makes
  no call, so your own `gh auth login` never stands in for this token.
- Read by the adapter behind the port, and passed to `gh` through the environment. Never in argv, never in the adoption
  file, never logged, never in the JSON output.
- In the CI templates, in the `sbx-decide` and `sbx-trusted` environments. Set **Deployment branches and tags** on both to
  **Selected branches and tags**, your default branch only
  ([GitHub's options](https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/actions/reference/workflows-and-actions/deployments-and-environments.md#L50)).
  With no rule, any job on any pushed branch that names the environment gets its secrets: this token, and in `sbx-trusted` the
  Docker one. The rest of the setup is in [contributor pull requests](../use-cases/contributor-prs.md#in-ci).

## Check it

```bash
GH_TOKEN=... python <skill>/scripts/sbx_trust.py doctor --repo <owner/name> --pr <n>
```

It checks the token is present, works, reaches this repository, and can read what your rules need, and it names the
missing permission with a link here. `sbx_check.py` includes the result as a warning.

## Expired token

A `401` or `Bad credentials` means it expired or was revoked. Create a new one the same way, and replace the secret.
