# ADR-002: Official images only, pinned by version and digest

Status: Accepted, 2026-10-21

Plan decisions: 2

## Context

An LLM gateway holds provider keys and sees every prompt, which makes it a high-value supply-chain target. In March 2026 LiteLLM 1.82.7 and 1.82.8 on PyPI were found compromised while the official container image was not affected, and a v1.107.0 release was reported compromised on 2026-10-21.

## Decision

Run LiteLLM only from the official `ghcr.io/berriai/litellm` image, and pin every image in `docker-compose.yml` as `version@sha256:digest`. `scripts/pin-image.sh` resolves and writes pins; agents may not edit digests by hand. Presidio is pinned by the tags that actually exist on the Microsoft registry, which lags PyPI (2.2.362 there versus 2.2.364 on PyPI in October 2026).

## Alternatives rejected

- **`pip install litellm`.** Exposed to exactly the PyPI incidents above.
- **Floating tags such as `latest`.** A rebuild could silently pull different code.

## Consequences

The project stayed on v1.106.2 throughout and was untouched by the October incident. Upgrades are deliberate: re-pin, re-run the phase checks, commit.
