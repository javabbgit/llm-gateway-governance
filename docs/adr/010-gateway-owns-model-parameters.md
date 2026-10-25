# ADR-010: The gateway owns model parameters

Status: Accepted, 2026-10-22

Plan decisions: 16, 20

## Context

qwen3 emits a reasoning section by default, which is slow on CPU. Applications can also send parameters that change cost or behaviour.

## Decision

Keep `qwen3:0.6b` and have the gateway force `reasoning_effort: none` (4.8 s to 0.2 s). For controlled parameters the plugin drops what the application sent, so the configured value applies: reasoning on `chat-default`; sampling parameters and thinking on `chat-cloud`, whose reasoning is fixed at `low`. After a reroute, parameters are dropped according to the final model.

## Alternatives rejected

- **Switching to qwen2.5:0.5b.** Not needed once thinking could be switched off.
- **The prompt switch `/no_think`.** Ineffective in Ollama 0.40.8.
- **Defaults in the deployment only.** A request value overrides a deployment default in LiteLLM, measured in P2.
- **Rewriting values instead of dropping them.** A rewritten value would follow a fallback to llama3.2.

## Consequences

Parameter control is itself a governance demo point: applications cannot raise cost by asking for more reasoning.
