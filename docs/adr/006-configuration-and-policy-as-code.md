# ADR-006: Configuration and policy as code

Status: Accepted, 2026-10-21

Plan decisions: 9, 29

## Context

The open-source edition has no configuration audit log, and regulators ask who changed what and when. IT and compliance also own different things.

## Decision

Models, routes, fallbacks and prices live in `litellm/config.yaml`; model editing in the UI is off. Teams, keys, budgets and rate limits live in `governance/org.toml` and are applied by an idempotent script. The residency policy lives separately in `governance/policy.toml`, owned by compliance, with an `enforcement` switch (`off`, `route`, `full`) used to roll it out in stages. Switching is human-only and committed. Git history is the change log.

## Alternatives rejected

- **Editing models in the admin UI.** No history.
- **A YAML policy file.** Host scripts and the plugin read TOML with the standard library (`tomllib`), the same format as `org.toml`, so agents need no extra package.
- **Turning the whole policy on at once.** The staged switch let routing go live and be verified before redaction.

## Consequences

Runtime changes made outside the files (for example deleting a team in the UI) are not undone automatically and must be logged.
