# ADR-008: Observability without an enterprise licence

Status: Accepted, 2026-10-21

Plan decisions: 11

## Context

The demo needs to show who used what and what the policy decided. LiteLLM's Prometheus metrics are an enterprise feature.

## Decision

Use the LiteLLM admin UI for requests, spend, teams and keys, and `scripts/audit.py` for the governance audit table, which the UI cannot see. The audit query lists decisions, filters by time, action, team or call ID, joins spend by call ID, and summarises by action, rule, reason, team and detector health.

## Alternatives rejected

- **Prometheus and Grafana.** Licence-gated in LiteLLM and more moving parts than a demo needs.

## Consequences

There is no time-series alerting. A web view of the audit table is listed as a later enhancement.
