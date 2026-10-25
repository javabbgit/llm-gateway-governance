# ADR-001: LiteLLM Proxy as the gateway, governance in one plugin

Status: Accepted, 2026-10-21

Plan decisions: 1, 12

## Context

The demo needs an OpenAI-compatible endpoint with virtual keys, teams, budgets, rate limits, fallbacks and an admin UI, plus data-residency logic that no off-the-shelf gateway provides. Review time is the scarce resource: every line written is a line that must be read and debugged.

## Decision

Use the open-source LiteLLM Proxy for everything it already does, and put all custom logic in a single plugin, `litellm/governance.py`, hooked before routing. PII detection, the residency decision, redaction, audit and parameter locks all live there, so every governance judgement is made in one place.

## Alternatives rejected

- **A gateway written from scratch (FastAPI).** More code to review and debug for features that already exist; less like what enterprises actually deploy.
- **LiteLLM's built-in Presidio guardrail.** It masks text but makes no residency decision, and per-team guardrails are an enterprise feature. Using it next to the plugin would also run detection twice.

## Consequences

The project depends on LiteLLM's hook semantics. One surfaced in P4: the model allowlist is checked only at authentication, so a model rewritten in the hook is never re-checked; the plugin therefore checks the caller's allowlist itself before rerouting and blocks with rule R10. Upgrading LiteLLM means re-running the check suites.

Evidence: [`docs/p2-results.md`](../p2-results.md), [`docs/p4-results.md`](../p4-results.md)
