# ADR-013: Redaction inside the plugin, streaming by buffer and replay

Status: Accepted, 2026-10-24

Plan decisions: 22, 23

## Context

General PII may go to the approved cloud model only as placeholders, and the application must still get a usable answer, streaming included.

## Decision

The plugin replaces each detected span with a placeholder such as `[PERSON_1]`, consistently across all messages, and restores the answer. The mapping lives only in plugin memory, keyed by call ID for ten minutes, never in metadata (which reaches the spend log). Restore also accepts `PERSON_1` without brackets and never confuses `PERSON_10` with `PERSON_1`. For streaming requests that need restoring, the plugin buffers the whole upstream stream, restores it and replays it as standard SSE chunks.

## Alternatives rejected

- **Presidio's anonymizer container.** `replace` cannot be reversed and `encrypt` would put ciphertext into the prompt; one container fewer.
- **Forcing non-streaming responses, or rerouting.** Clients would see a different protocol, which costs more in support than it saves.

## Consequences

Time to first token for a redacted streaming request equals the full generation time. Streaming restore without buffering is a later enhancement.

Evidence: [`docs/p4-results.md`](../p4-results.md)
