# ADR-005: The gateway is the only path to a model

Status: Accepted, 2026-10-21

Plan decisions: 8, 17

## Context

Many corporate gateways become optional in practice because applications can still call model endpoints directly. A local model runtime can also become a cloud exit: recent Ollama versions can forward requests to Ollama Cloud.

## Decision

Only LiteLLM publishes a port, bound to `127.0.0.1:4000`. Ollama, Postgres and Presidio have no host ports. Ollama runs with `OLLAMA_NO_CLOUD=1`. A bypass test checks host connections and a container on another Docker network, and the demo opens with it.

## Alternatives rejected

- **Keeping Ollama's port for convenience.** Any app could skip every control.
- **Default Ollama cloud settings.** The local layer could become a route around the residency policy.

## Consequences

The host can still route to container bridge IPs on Linux; that is recorded as a known boundary, because anyone who can run commands on the host is effectively in the docker group. Full network isolation is listed as a later enhancement.

Evidence: [`docs/p2-results.md`](../p2-results.md)
