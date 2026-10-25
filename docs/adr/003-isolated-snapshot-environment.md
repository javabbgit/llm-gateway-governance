# ADR-003: An isolated, snapshot-able build environment

Status: Accepted, 2026-10-21

Plan decisions: 3, 4, 7

## Context

Coding agents run commands on the machine. An earlier experiment let an agent work directly on Windows and left the environment in a mess. Every phase must be reversible.

## Decision

Use a dedicated laptop with a local administrator account; all work happens in WSL2 Ubuntu. Docker Engine is installed inside Ubuntu, and every component, Ollama included, runs in one Docker Compose project. Each phase ends with `wsl --export` of the whole distro through `scripts/snapshot.ps1`, which refuses to run unless the tree is clean and the stage tag is pushed.

## Alternatives rejected

- **Working directly on Windows.** No whole-machine rollback.
- **Docker Desktop.** Its images and volumes live in a separate distro and are not in the Ubuntu export, so a restore would be incomplete.
- **Ollama installed on the host.** Docker is a common job requirement, and one compose file keeps the whole stack in one place.

## Consequences

Snapshots are large (17.8 GB after P4) because they include the model and image layers; P5 removes unreferenced images before the final export. Restores were verified for P0, P1 and P2.
