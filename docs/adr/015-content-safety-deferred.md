# ADR-015: Content-safety model deferred past v1.0

Status: Accepted, 2026-10-24

Plan decisions: 28

## Context

`llama-guard3:1b` was pulled in P1 as an optional content-safety check.

## Decision

Leave content-safety review out of v1.0.

## Alternatives rejected

- **Implementing it in P4.** Residency routing came first, and each check adds about one second per request on this CPU (0.93 s measured).

## Consequences

The model is already on disk; adding the check later is a plugin change plus a policy entry.
