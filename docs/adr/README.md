# Architecture decision records

Each record states what was decided, what was rejected and why. `Plan decisions` refers to the numbered decision log in the project plan (36 decisions, number 18 superseded); the records group them by topic.

| ADR | Decision | Plan decisions | Date |
| --- | --- | --- | --- |
| [ADR-001](001-litellm-gateway-one-plugin.md) | LiteLLM Proxy as the gateway, governance in one plugin | 1, 12 | 2026-10-21 |
| [ADR-002](002-pinned-official-images.md) | Official images only, pinned by version and digest | 2 | 2026-10-21 |
| [ADR-003](003-isolated-snapshot-environment.md) | An isolated, snapshot-able build environment | 3, 4, 7 | 2026-10-21 |
| [ADR-004](004-ai-assisted-delivery.md) | AI-assisted delivery under human review | 5, 6, 14, 15 | 2026-10-21 |
| [ADR-005](005-gateway-only-path.md) | The gateway is the only path to a model | 8, 17 | 2026-10-21 |
| [ADR-006](006-configuration-and-policy-as-code.md) | Configuration and policy as code | 9, 29 | 2026-10-21 |
| [ADR-007](007-no-content-logging.md) | Never store prompts or responses | 10 | 2026-10-21 |
| [ADR-008](008-observability-without-enterprise.md) | Observability without an enterprise licence | 11 | 2026-10-21 |
| [ADR-009](009-chargeback-and-reconciliation.md) | Internal chargeback pricing and cloud reconciliation | 13 | 2026-10-21 |
| [ADR-010](010-gateway-owns-model-parameters.md) | The gateway owns model parameters | 16, 20 | 2026-10-22 |
| [ADR-011](011-fallback-testing.md) | Testing fallback with mock request parameters | 18, 19 | 2026-10-23 |
| [ADR-012](012-pii-residency-routing.md) | PII data-residency routing, fail-closed | 21, 24 | 2026-10-24 |
| [ADR-013](013-redaction-in-plugin.md) | Redaction inside the plugin, streaming by buffer and replay | 22, 23 | 2026-10-24 |
| [ADR-014](014-detection-scope.md) | Detection scope: English only, explicit entities | 25, 26, 27 | 2026-10-24 |
| [ADR-015](015-content-safety-deferred.md) | Content-safety model deferred past v1.0 | 28 | 2026-10-24 |
| [ADR-016](016-one-command-demo.md) | A one-command, repeatable demo | 30, 31, 32, 33 | 2026-10-25 |
| [ADR-017](017-demo-day-operations.md) | Demo-day operations: keep-alive, snapshot slimming, recordings | 34, 35, 36 | 2026-10-25 |
