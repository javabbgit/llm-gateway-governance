# ADR-017: Demo-day operations: keep-alive, snapshot slimming, recordings

Status: Accepted, 2026-10-25

Plan decisions: 34, 35, 36

## Context

WSL stops a distro seconds after its last window closes, taking the gateway with it. Snapshots had grown to 17.8 GB. A live demo needs a fallback.

## Decision

`scripts/keepalive.ps1` starts a hidden `wsl --exec sleep infinity` and records its PID; it is started for demos and stopped afterwards. Snapshot slimming removes only images not referenced by `docker-compose.yml`, dangling images and build cache, never volumes, and is run by a human (`p5check.py slim`). Recordings: the terminal with asciinema (the `.cast` text file is committed), the admin UI with the Windows Snipping Tool (MP4, not committed).

## Alternatives rejected

- **`vmIdleTimeout=-1` in `.wslconfig`.** It governs the VM, not the distro; reported ineffective for this case.
- **`docker system prune -a`, or a slimmer Ollama image.** The first can delete what is in use; the second changes a verified component.
- **OBS or other third-party recorders.** Nothing to install for what the built-in tools already do.

## Consequences

The keep-alive ends with `wsl --shutdown`, including the one in `snapshot.ps1`, and has to be started again.
