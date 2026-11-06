---
type: Knowledge
title: Network policy
description: What egress a box needs per toolchain, how the proxy treats TLS, and how to read a block.
tags: [sbx, network, policy]
status: stable
date: 2026-11-05
---

# Network policy

Set an account's default with `sbx --cloud policy init <allow-all|balanced|deny-all>` and read it with `sbx --cloud policy ls`
(sbx 0.51.0 `--help`). `policy ls --json` prints `{"mode": "deny-all", "allow_networks": [...], "deny_networks": [...]}`, and with a box name it prints that box's effective policy: the `--allow-network` hosts appear in `allow_networks`. An untrusted run requires `network_policy: deny-all` in the adoption file **and** the fleet reads the account's policy before creating anything; any other mode, an account `allow_networks` entry that names no host, a global secret one of its hosts reaches, or an unreadable answer stops the run (exit 2, or 3 when unreadable). `sbx --cloud policy rm network --resource <pattern>` removes an entry. In a pattern, `*` matches one label and `**` matches any depth.

Measured on sbx 0.51.0 in a live box under a deny-all account with the allow list above: pypi.org answered 200, and example.com failed with `Could not resolve host` (no proxy tunnel for a host that is not allowed, `CONNECT tunnel failed, response 403` when a proxy is used). One account, one run.

| Toolchain | Allow |
|---|---|
| git | `github.com`, `**.githubusercontent.com` |
| uv, pip | `pypi.org`, `files.pythonhosted.org`, `astral.sh`, `**.astral.sh` |
| Maven | `repo.maven.apache.org`, `repo1.maven.org` |
| Docker pulls | [`**.docker.com`](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L439), `**.docker.io` |
| Playwright | [`storage.googleapis.com`](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L443), `*.playwright.dev` |

## What the proxy does

[Measured](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L181) on 0.50: `forward` terminates TLS to inject a credential, `forward-bypass` is an
untouched tunnel, and `transparent` is traffic that ignored the proxy settings. This is how a key reaches a provider
without existing in the VM.

The 403 body names the blocked host. `sbx policy log` is the truth.

An agent's "the network is blocked" is a symptom. In one run the [policy log said allowed](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/bench/README.md#L44): a firewall was
dropping post-quantum TLS. Set `GODEBUG=tlsmlkem=0` in the shell that restarts the daemon, and classic groups in the
VM ([sbx-releases#773](https://github.com/docker/sbx-releases/issues/773)).

Allowing `host.docker.internal:3001` [does not match](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/FINDINGS.md#L178): the proxy evaluates it as `localhost:3001`.

Boxes cannot reach each other. Use a [host inbox](https://github.com/ffroliva/sbx-team-kit/blob/b25e1d28a135bcc2d6f643b3b95f129bc53008b1/orchestrator/README.md) or git for messages.
