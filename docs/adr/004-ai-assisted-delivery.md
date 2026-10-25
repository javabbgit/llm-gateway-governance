# ADR-004: AI-assisted delivery under human review

Status: Accepted, 2026-10-21

Plan decisions: 5, 6, 14, 15

## Context

The project is built by one person paying for AI usage personally, with coding agents as the workforce. The work must stay legal, affordable and reviewable.

## Decision

Use official channels only: GitHub Copilot CLI first, Claude Code on a Pro subscription as backup. Tier the models: Opus for planning documents, Sonnet for troubleshooting, Haiku for routine execution. From P1 on, the planning conversation writes and sandbox-tests the code; a human runs the scripts on the laptop, and agents step in only when a check fails. Rules for every agent are in `AGENTS.md`: no secrets, no installs, no policy changes, no push or tag, no volume deletion. Claude Code traffic is not routed through the gateway for the billing demo.

## Alternatives rejected

- **A reverse proxy to Copilot, or a non-Claude coding backend.** Against GitHub's terms and could cost the education account.
- **One model for everything.** Either too expensive or too weak for terminal troubleshooting.
- **Agents implementing step by step from the documents.** P1 passed first time with zero agent credits when a human ran the scripts.
- **Billing demo with Claude Code traffic.** It signs in with a subscription; there is no metered API to reconcile.

## Consequences

Agent usage stayed small (P1: zero credits; P2: about 5). Gaps between plan and reality are recorded in `docs/progress.md` and folded back into the phase documents.
