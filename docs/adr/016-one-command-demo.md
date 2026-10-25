# ADR-016: A one-command, repeatable demo

Status: Accepted, 2026-10-25

Plan decisions: 30, 31, 32, 33

## Context

The demo has to run in front of people in a few minutes, survive a venue without network, and run again immediately.

## Decision

`scripts/demo.sh` wraps `scripts/demo.py`, written with the Python standard library on top of the phase check helpers already proven in P2–P4. Every run starts by rebuilding the `demo-budget` and `demo-ratelimit` keys from `org.toml`, which gives a fresh spend and rate-limit window, and by making sure Presidio is up; `scripts/reset.sh` does the same alone. A preflight checks services, policy mode, keys and warms both local models. Output is in English for a Canadian audience. Offline means api.anthropic.com:443 cannot be reached within 3 seconds, or there is no Anthropic key; then only scene 8 is skipped, with the reason on screen.

## Alternatives rejected

- **Bash with curl and jq.** Waiting, JSON handling and recovery are hard to write and test.
- **A manual reset step.** One forgotten command fails the live demo; a fresh key avoids waiting out a 60-second window or editing the database.
- **ping or DNS to detect offline.** ICMP is often blocked and DNS can hang; the check connects to the endpoint actually used, in a thread with a deadline.

## Consequences

Each run creates two new keys and leaves the old ones deleted; team spend keeps accumulating at a few hundredths of a cent per run. Scene 9 stops Presidio and always restarts it, including on Ctrl+C.

Evidence: [`docs/p5-results.md`](../p5-results.md)
