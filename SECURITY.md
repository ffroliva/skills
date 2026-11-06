# Security policy

This is an independent community project. It is not made or endorsed by Docker, and a flaw in Docker Sandboxes itself belongs
with Docker.

## Reporting

Report a vulnerability in this repository privately, with "Report a vulnerability" on its Security tab. Please do not open a public
issue. Say what you ran, which sbx version and which commit of this repository. There is one maintainer and no response time is promised.

## What counts

The safety promises are in [trust levels](skills/sandbox-runbook/docs/reference/trust.md). A way to break one is a vulnerability:

- an input not proven trusted that comes back trusted
- a secret reaching a run that may not hold it, or a box that was not handed it
- a box, or an archive it returns, reaching the host
- a secret value in a log, a verdict or printed output

## What does not

A box running what you told it to; `sudo` inside a box; anything a run does while trusted by your own rules. What is measured, and
what is not, is listed in [evidence and versions](skills/sandbox-runbook/docs/reference/evidence.md).

## Supported versions

Only the latest commit on the default branch.
