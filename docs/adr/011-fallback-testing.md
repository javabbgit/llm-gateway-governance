# ADR-011: Testing fallback with mock request parameters

Status: Accepted, 2026-10-23

Plan decisions: 18, 19

## Context

Fallback from `chat-default` to `chat-fallback` must be shown on demand, without breaking a model.

## Decision

Use LiteLLM's `mock_testing_fallbacks` request parameter, which requires `dangerously_allow_mock_testing_request_params: true`. Fallback runs only between local models, never between local and cloud. Production should turn the setting off.

## Alternatives rejected

- **A demo alias pointing at a missing model.** Tests that alias, not the real chain of `chat-default`.
- **Decision 18, superseded:** a zero-cost cloud alias through GitHub Models. The service had been retired on 2026-07-30; LiteLLM's `github_copilot/` route was also rejected because it impersonates an IDE client. Cloud validation moved to Anthropic in P3.

## Consequences

Anyone with a key could force a fallback while the setting is on; acceptable for a demo, not for production.
