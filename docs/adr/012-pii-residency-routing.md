# ADR-012: PII data-residency routing, fail-closed

Status: Accepted, 2026-10-24

Plan decisions: 21, 24

## Context

Requests containing PII must not reach a vendor the bank has not approved; they may only go to local models or an approved cloud model. Detection can fail.

## Decision

Each model alias carries a jurisdiction (`local`, `US`, `CN`) mapped to a class (local, approved, unapproved; unlabelled counts as unapproved). A nine-cell matrix of class × sensitivity (none, general, high) gives rules R1–R9: pass, redact or reroute to `chat-default`. If the reroute target is not on the caller's allowlist, the request is blocked (R10). Detector timeout (3 s), error or absence counts as high sensitivity. Local targets are also scanned and audited, and pass when the detector fails. DeepSeek is a mock deployment: jurisdiction CN, no network call, zero cost.

## Alternatives rejected

- **A real DeepSeek account.** It is in daily personal use and cannot be paused for a comparison; proof that PII never reached DeepSeek comes from the audit and spend logs, whatever the backend.
- **Skipping detection for local targets.** Audit needs complete PII usage statistics.

## Consequences

On the real gateway, 65 corpus requests matched the policy 65/65 and every reroute was answered locally. With Presidio stopped, requests were rerouted in 0.3 s; with it paused, after the 3 s timeout.

Evidence: [`docs/p4-results.md`](../p4-results.md)
