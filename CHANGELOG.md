# Changelog

One heading per version. `scripts/check_versions.py` holds every manifest to the newest one, and a tag to it.

## Unreleased

- Rename the plugin and skill to `ffroliva-skills` and `sandbox-runbook`; keep the `sbx` CLI interface.

## 0.1.0

Not tagged or released yet.

- The skill: a runbook of trusted and untrusted scenarios, each with steps, checks and an evidence state.
- Scripts: `sbx_detect`, `sbx_onboard`, `sbx_check`, `sbx_trust`, `sbx_shard`, `sbx_fleet`, `sbx_drift`, `validate_skill`.
- The fleet: one verdict from every box, refusals before any box exists, trust levels enforced in code, a ledger and a cost ceiling, and a final proof that
  nothing is left billing.
- `verdict.json`, a public interface: `sha`, `exit`, `ok`, `lines`, `level`, `rule`, `evidence`, `left_behind`,
  `possibly_left_behind`, `box_seconds`, `estimated_usd`, `means`, `complete`, `expect_tests`, `tests`, `ran`, `skipped` and `boxes`.
- `--expect-tests` and `sbx_shard.py check --expect` count unique tests that ran: skipped ones are not counted. Boxes that share a
  command are shards of one suite, and boxes with their own commands add up.
- Two CI templates for fork pull requests, `templates/github-pr-target.yml` and `templates/github-pr.yml`, never yet run on GitHub.
- Install from one copy of `skills/sandbox-runbook`, with thin manifests for Claude Code, Codex, Antigravity and Gemini CLI.
