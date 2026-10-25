# Presenter guide

The demo runs in a few minutes and needs no typing beyond one command. This page is the checklist, the talk track and the admin UI tour. Scene numbers match the output of `bash scripts/demo.sh`.

## Before you start

1. Laptop on power, Windows Focus Assist on, terminal font large enough for a room or a recording.
2. Keep WSL alive so closing a window cannot stop the gateway (Windows PowerShell):
   `powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\keepalive.ps1 start`
3. In Ubuntu: `cd ~/projects/llm-gateway-governance && docker compose ps` shows four services `healthy`.
4. Dry run without the cloud: `bash scripts/demo.sh --offline --only 1,2`.
5. Open the admin UI at http://127.0.0.1:4000/ui/ and sign in as `gateway-admin` in a browser tab you can switch to.

No network at the venue? Nothing to change: the demo detects it and skips scene 8 with the reason on screen.

## Running it

`bash scripts/demo.sh --pace` pauses before each scene; press Enter when you have said your line. Without `--pace` it runs straight through, which is what the recording uses.

## Talk track

| # | Say | Point at |
| --- | --- | --- |
| 1 | "Every control below is worthless if an app can talk to the model directly. Here it cannot: the model and the database have no ports." | `refused` on both lines |
| 2 | "Apps use one OpenAI-compatible endpoint and a logical name. Swapping the model behind `chat-default` changes no application code." | `served by chat-default`, `policy pass R1` |
| 3 | "When the primary model fails, the gateway falls back to a second model family instead of failing the app." | `served by chat-fallback` |
| 4 | "Underwriting handles customer files, so it is only allowed local models. The gateway refuses before any data moves." | HTTP 401/403 |
| 5 | "One chatty app cannot starve the others: five requests a minute, the sixth is turned away." | `200 200 200 200 200 429` |
| 6 | "Budgets stop spend at the cap, not at month-end. It is a soft cap: the call that crosses it completes, the next one is refused." | the budget error |
| 7 | "Marketing may use DeepSeek for copy. The moment a SIN appears, the request never leaves the laptop: same app, same model name, answered locally." | `reroute R9`, `pii=CA_SIN:1` |
| 8 | "The approved US vendor may see general PII only as placeholders. Haiku says YES, it saw a placeholder; the app still gets the real name back." | `redact R5`, line 1 `YES`, restored sentence |
| 9 | "If the detector is down we assume the worst. Even a harmless request is kept away from DeepSeek until Presidio is back." | `reason detector_unavailable` |
| Trail | "Every decision is audited: types and counts only, never the text, joined to the spend log by call ID." | the audit table |

## Admin UI tour (about one minute)

- **Logs**: each request with team, key alias, model and spend. There is no prompt or response column content: message logging is off by design.
- **Teams**: underwriting, marketing, it-ops with their model allowlists and budgets.
- **Virtual Keys**: `demo-budget` and `demo-ratelimit` were just recreated by the reset; their spend starts at zero.
- **Usage**: spend by team, including internal chargeback for local CPU time.

The policy audit table is not in the UI; show it with `python3 scripts/audit.py --summary --since 1h`.

## If something goes wrong

| Symptom | Fix |
| --- | --- |
| Preflight says a service is not healthy | `docker compose up -d`, wait a minute, rerun |
| Scene 5 or 6 fails with "window still open" or "budget already used up" | `bash scripts/reset.sh`, rerun (only happens with `--no-reset`) |
| A run was killed during scene 9 | `docker compose unpause presidio-analyzer && docker compose start presidio-analyzer` |
| Scene 8 skipped although you are online | `.secrets/anthropic_api_key` is empty, or the venue blocks port 443 to api.anthropic.com |
| Everything is stuck | Play the recording: `asciinema play docs/demo/demo.cast` |

## Recording

Terminal: `asciinema rec docs/demo/demo.cast --cols 120 --rows 40 -c "bash scripts/demo.sh"` (the cast file is text and is committed). Admin UI: Windows Snipping Tool, Record, saved as MP4 outside the repo. Neither shows a key: the demo never prints one.
