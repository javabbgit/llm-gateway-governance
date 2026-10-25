# ADR-007: Never store prompts or responses

Status: Accepted, 2026-10-21

Plan decisions: 10

## Context

A log database that keeps prompts becomes the largest concentration of PII in the organization, and auditors ask about it every year.

## Decision

Keep LiteLLM's message logging off (`turn_off_message_logging`, `store_prompts_in_spend_logs: false`). The policy audit table stores PII types and counts only, never values and never hashes: a nine-digit SIN has only a billion possibilities, so a hash can be reversed by brute force. A database constraint rejects anything but type → integer.

## Alternatives rejected

- **Storing content for troubleshooting.** Convenient, and the main way gateways leak.

## Consequences

Troubleshooting relies on metadata, response headers and the call ID. Every phase repeats a canary test: a marker string and fake PII are sent, then searched for in a full database dump and all container logs, for local, rerouted, redacted and cloud requests. None has ever been found.

Evidence: [`docs/p4-results.md`](../p4-results.md)
