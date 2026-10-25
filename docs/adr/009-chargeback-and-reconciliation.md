# ADR-009: Internal chargeback pricing and cloud reconciliation

Status: Accepted, 2026-10-21

Plan decisions: 13

## Context

With free local models there is nothing to budget, and enterprises do charge business units for shared compute.

## Decision

Price local models at an assumed $0.10 per CPU-hour of this laptop, converted with measured throughput: qwen3:0.6b at 72.4 tokens/s gives $0.40 per million output tokens, llama3.2:1b at 28.1 tokens/s gives $1.00; input is a quarter of output. The cloud model uses list price, and gateway token counts are reconciled with the Anthropic Console.

## Alternatives rejected

- **Zero-cost local models.** Budgets could not be demonstrated.

## Consequences

Reconciliation matched exactly (313 input / 957 output tokens, hour by hour). It also surfaced a bug: Ollama's short response IDs collided in the spend log's primary key and rows were dropped silently; the plugin now rewrites them. Budgets turned out to be soft caps: the call that crosses the cap completes and the next returns HTTP 422.

Evidence: [`docs/p3-results.md`](../p3-results.md)
