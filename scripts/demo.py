#!/usr/bin/env python3
"""One-command demo of the governed LLM gateway (P5). Standard library only.

  bash scripts/demo.sh               reset demo keys, warm up, run the 9 scenes, show the audit trail
  bash scripts/demo.sh --pace        pause before each scene (live presentation; press Enter to go on)
  bash scripts/demo.sh --offline     force offline mode: the cloud scene is skipped, everything else runs
  bash scripts/demo.sh --only 7,8,9  run selected scenes (reset and warm-up still run first)
  bash scripts/reset.sh              only reset the demo state

Scenes: 1 bypass · 2 routing · 3 fallback · 4 team allowlist · 5 rate limit · 6 budget ·
        7 PII rerouted away from DeepSeek · 8 PII redacted for the approved cloud model [cloud] · 9 fail-closed

Offline mode is automatic: if api.anthropic.com:443 cannot be reached in 3 seconds, or there is no Anthropic key,
scene 8 is skipped with the reason shown. Scene 8 is the only real cloud call (one Haiku request, under $0.001).
Scene 9 stops the Presidio container and always starts it again, even on Ctrl+C. If a run is killed hard, recover with
  docker compose unpause presidio-analyzer; docker compose start presidio-analyzer

Exit code 0 when every scene that ran passed (skipped scenes are fine), 1 otherwise. Keys are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402
import p2check as base  # noqa: E402
import p3check as p3  # noqa: E402
import p4check as p4  # noqa: E402
from p2check import GW, http, run, snip, tcp_open  # noqa: E402

PRESIDIO = p4.PRESIDIO
UW, MKT = p4.UW, p4.MKT
BUDGET_KEY, RL_KEY = "demo-budget", "demo-ratelimit"
SERVICES = ("ollama", "postgres", "presidio-analyzer", "litellm")
CLOUD_HOST = ("api.anthropic.com", 443)
LOCAL = p4.LOCAL
FAKE_SIN, FAKE_NAME = p4.FAKE_SIN, p4.FAKE_NAME
PLAIN = [{"role": "user", "content": "Write a one-line tagline for spring mortgage renewals."}]
PONG = [{"role": "user", "content": "Reply with one word: pong"}]
SHOW_IN_TRAIL = (2, 3, 7, 8, 9)      # scenes whose requests are listed in the audit trail; 5 and 6 are only counted

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if COLOR else s


def status_word(s: str) -> str:
    return c({"PASS": "1;32", "FAIL": "1;31", "SKIP": "1;33", "WARN": "33"}.get(s, "0"), s)


def key(alias: str) -> str:
    return p3.key_of(alias)


def chat(alias: str, who: str, messages: list, max_tokens: int = 24, **extra) -> base.Resp:
    return p4.chat(alias, key(who), messages, max_tokens=max_tokens, **extra)


def text_of(r: base.Resp) -> str:
    return base.answer(r)[0]


def clean(s: str) -> str:
    """Never echo the fake identifiers back verbatim on screen."""
    return s.replace(FAKE_SIN, "<SIN>").replace(FAKE_SIN.replace(" ", ""), "<SIN>")


def internet_ok(timeout: float = 3.0) -> bool:
    """TCP connect to the cloud provider, in a thread so a stuck DNS lookup cannot hang the demo."""
    res: dict = {}

    def probe() -> None:
        try:
            socket.create_connection(CLOUD_HOST, timeout=timeout).close()
            res["ok"] = True
        except OSError:
            res["ok"] = False

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout + 1)
    return res.get("ok", False)


def cloud_status(force_offline: bool) -> tuple[bool, str]:
    if force_offline or os.environ.get("DEMO_OFFLINE") == "1":
        return False, "offline mode forced (--offline)"
    if not p3.cloud_ready():
        return False, "no Anthropic key in .secrets/anthropic_api_key"
    if not internet_ok():
        return False, f"cannot reach {CLOUD_HOST[0]}:{CLOUD_HOST[1]} (offline)"
    return True, "online"


# ---------- reset ----------
def rebuild_key(alias: str) -> tuple[bool, str]:
    """Delete and re-create a demo key from governance/org.toml: fresh spend and a fresh rate-limit window."""
    org = p3.load_org()
    team = next((t for t in org.get("team", []) if any(k["alias"] == alias for k in t.get("key", []))), None)
    if not team:
        return False, f"{alias} is not defined in governance/org.toml"
    kdef = next(k for k in team["key"] if k["alias"] == alias)
    tid = p3.teams_by_alias().get(team["alias"], {}).get("team_id")
    if not tid:
        return False, f"team {team['alias']} not found in the gateway: run python3 scripts/p3check.py org"
    http("POST", f"{GW}/key/delete", p3.mk(), {"key_aliases": [alias]}, timeout=30)
    body = {"key_alias": alias, "team_id": tid,
            "metadata": {"note": kdef.get("note", ""), "managed_by": "governance/org.toml"}}
    for f in ("max_budget", "rpm_limit", "models"):
        if kdef.get(f) is not None:
            body[f] = kdef[f]
    r = http("POST", f"{GW}/key/generate", p3.mk(), body, timeout=30)
    new = r.json().get("key", "")
    if r.status != 200 or not new:
        return False, f"HTTP {r.status} {r.err_msg()}"
    keys = p3.load_keys()
    keys[alias] = {"key": new, "team": team["alias"]}
    p3.save_keys(keys)
    detail = ", ".join(x for x in (f"budget ${kdef['max_budget']}" if "max_budget" in kdef else "",
                                   f"{kdef['rpm_limit']} requests/minute" if "rpm_limit" in kdef else "") if x)
    return True, f"rebuilt ({detail}; spend 0, fresh window)"


def ensure_presidio(timeout: int = 120) -> float:
    run(["docker", "compose", "unpause", PRESIDIO], timeout=60)     # no-op unless a run was killed mid-scene 9
    run(["docker", "compose", "start", PRESIDIO], timeout=120)
    return p4.presidio_health(timeout=timeout)


def do_reset(quiet: bool = False) -> bool:
    out = []
    ok = True
    if p4.wait_gateway(timeout=120) < 0:
        print(f"  {status_word('FAIL')} gateway at {GW} is not up: docker compose ps")
        return False
    for alias in (BUDGET_KEY, RL_KEY):
        good, detail = rebuild_key(alias)
        ok &= good
        out.append((good, alias, detail))
    secs = ensure_presidio()
    ok &= secs >= 0
    out.append((secs >= 0, "Presidio", f"healthy ({secs:.0f} s)" if secs >= 0 else "not healthy after 120 s"))
    if not quiet or not ok:
        for good, what, detail in out:
            print(f"  {status_word('PASS' if good else 'FAIL')} {what:<15} {detail}")
    return ok


# ---------- the demo ----------
class Scene:
    def __init__(self, num: int, title: str, why: str, expect: str, cloud: bool = False):
        self.num, self.title, self.why, self.expect, self.cloud = num, title, why, expect, cloud
        self.status, self.lines, self.ids, self.secs, self.note = "FAIL", [], [], 0.0, ""


SCENES = [
    Scene(1, "Bypass: apps cannot reach a model directly",
          "If an app can call the model directly, every other control is optional.",
          "host connections to Ollama (11434) and Postgres (5432) are refused"),
    Scene(2, "Normal routing through the gateway",
          "Apps use one OpenAI-compatible endpoint and a logical model name.",
          "underwriting → chat-default: HTTP 200, served locally, policy pass (R1)"),
    Scene(3, "Fallback when the primary model fails",
          "A failing backend degrades service instead of breaking the app.",
          "chat-default forced to fail → answered by chat-fallback"),
    Scene(4, "Team allowlist",
          "Underwriting handles customer data, so it may only use local models.",
          "underwriting → chat-cloud: rejected by the gateway (401/403)"),
    Scene(5, "Rate limit",
          "One noisy app cannot starve the others.",
          "demo-ratelimit (5 requests/minute): requests 1–5 → 200, request 6 → 429"),
    Scene(6, "Budget cap",
          "Spend stops at the cap; nobody finds out from the invoice.",
          "demo-budget ($0.0002): allowed until the cap is crossed, then blocked with a budget error"),
    Scene(7, "Data residency: PII never reaches an unapproved vendor",
          "A SIN must not leave for a provider the bank has not approved.",
          "no PII → DeepSeek (mock) answers (R7); with a SIN → rerouted to a local model (R9)"),
    Scene(8, "Redaction for the approved cloud model",
          "General PII may go to the approved vendor only as placeholders.",
          "a name bound for Haiku is replaced by [PERSON_1] (R5); the app gets the real name back", cloud=True),
    Scene(9, "Fail-closed",
          "If the detector is down, assume the worst instead of letting data out.",
          "Presidio stopped → even a request without PII is rerouted from DeepSeek; restored afterwards"),
]


class Demo:
    def __init__(self, a):
        self.a = a
        self.cloud, self.cloud_reason = True, ""
        self.audit_ok: bool | None = None
        self.t0 = time.time()

    # ---- framing ----
    def banner(self, text: str) -> None:
        print("\n" + c("1;36", f"━━ {text} " + "━" * max(3, 70 - len(text))))

    def line(self, label: str, text: str) -> None:
        print(f"   {c('2', f'{label:<8}')}: {text}" if label else f"   {'':<8}  {text}")

    def pause(self) -> None:
        if self.a.pace and sys.stdin.isatty():
            try:
                input(c("2", "   (Enter to run) "))
            except EOFError:
                pass

    # ---- preflight ----
    def preflight(self) -> bool:
        self.banner("Preflight")
        ok = True
        secs = p4.wait_gateway(timeout=120)
        ok &= secs >= 0
        health = []
        for svc in SERVICES:
            cid = base.container_id(svc)
            h = base.inspect(cid, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}") if cid else "not running"
            health.append((svc, h))
        bad = [f"{s}={h}" for s, h in health if h != "healthy"]
        ok &= not bad
        self.line("Services", f"{len(health) - len(bad)}/{len(health)} healthy" + (f" ({', '.join(bad)})" if bad else "")
                  + f"; gateway {GW} " + ("up" if secs >= 0 else "DOWN"))
        pol = p4.policy()
        ok &= pol.enforcement == "full"
        self.line("Policy", f"governance/policy.toml version {pol.version}, enforcement {pol.enforcement}"
                  + ("" if pol.enforcement == "full" else c("31", "  (needs full: python3 scripts/p4check.py mode full)")))
        missing = [x for x in (UW, MKT, BUDGET_KEY, RL_KEY) if not key(x)]
        ok &= not missing
        self.line("Keys", "virtual keys present in .secrets/p3-keys.json" if not missing
                  else c("31", f"missing {', '.join(missing)}: run python3 scripts/p3check.py org"))
        if not ok:
            return False
        t = time.time()
        warm = [chat(m, UW, PONG, max_tokens=1).status for m in LOCAL]
        ok &= warm == [200, 200]
        self.line("Warm-up", f"chat-default and chat-fallback loaded in {time.time() - t:.1f} s" if warm == [200, 200]
                  else c("31", f"warm-up failed: HTTP {warm}"))
        self.cloud, self.cloud_reason = cloud_status(self.a.offline)
        self.line("Cloud", "online: scene 8 calls Claude Haiku (under $0.001)" if self.cloud
                  else c("33", f"{self.cloud_reason}: scene 8 will be skipped"))
        return ok

    # ---- scenes ----
    def s1(self, s: Scene) -> bool:
        o, pg = tcp_open("127.0.0.1", 11434, 2), tcp_open("127.0.0.1", 5432, 2)
        r = http("GET", "http://127.0.0.1:11434/api/tags", timeout=3)
        s.lines = [f"127.0.0.1:11434 Ollama   → {'OPEN' if o else 'refused'}",
                   f"127.0.0.1:5432  Postgres → {'OPEN' if pg else 'refused'}",
                   f"GET /api/tags on Ollama  → {('HTTP ' + str(r.status)) if r.status else 'no connection'}"]
        return not o and not pg and r.status != 200

    def s2(self, s: Scene) -> bool:
        r = chat("chat-default", UW, [{"role": "user", "content": "In one sentence, what does a mortgage underwriter check?"}],
                 max_tokens=60)
        g, grp = p4.gov(r), r.headers.get("x-litellm-model-group", "?")
        s.ids.append(p4.call_id(r))
        s.lines = [f"HTTP {r.status} in {r.secs:.1f} s · served by {grp} · policy {g.get('action')} {g.get('rule')}",
                   f"\"{snip(text_of(r), 90)}\""]
        return r.status == 200 and grp == "chat-default" and g.get("action") == "pass"

    def s3(self, s: Scene) -> bool:
        r = chat("chat-default", UW, PONG, max_tokens=8, mock_testing_fallbacks=True)
        grp = r.headers.get("x-litellm-model-group", "?")
        tries = r.headers.get("x-litellm-attempted-fallbacks", "?")
        s.ids.append(p4.call_id(r))
        s.lines = [f"HTTP {r.status} in {r.secs:.1f} s · served by {grp} · fallbacks attempted {tries}"]
        if r.status != 200:
            s.lines.append(snip(r.err_msg(), 100))
        return r.status == 200 and grp == "chat-fallback" and tries not in ("0", "?")

    def s4(self, s: Scene) -> bool:
        r = chat("chat-cloud", UW, PONG)
        s.lines = [f"HTTP {r.status}: {snip(r.err_msg(), 100)}"]
        return r.status in (401, 403)

    def s5(self, s: Scene) -> bool:
        codes, last = [], None
        for _ in range(6):
            last = chat("chat-default", RL_KEY, PONG, max_tokens=4)
            codes.append(last.status)
            if last.status == 200:
                s.ids.append(p4.call_id(last))
        s.lines = ["requests 1–6 → " + " ".join(str(x) for x in codes)]
        if last is not None and last.status == 429:
            s.lines.append(f"429: {snip(last.err_msg(), 90)}")
        ok = codes[:5] == [200] * 5 and codes[5] == 429
        if not ok and 429 in codes[:5]:
            s.note = "window still open from an earlier run: bash scripts/reset.sh, then retry"
        return ok

    def s6(self, s: Scene) -> bool:
        allowed, cost, last = 0, 0.0, None
        for _ in range(12):
            last = chat("chat-default", BUDGET_KEY, [{"role": "user", "content": "Count from 1 to 60, separated by spaces."}],
                        max_tokens=200)
            if last.status != 200:
                break
            allowed += 1
            s.ids.append(p4.call_id(last))
            try:
                cost += float(last.headers.get("x-litellm-response-cost") or 0)
            except ValueError:
                pass
        msg = last.err_msg() if last is not None and last.status != 200 else ""
        spent = f" (≈${cost:.6f})" if cost else ""
        s.lines = [f"allowed {allowed} call(s){spent}, then HTTP {last.status if last else '?'}",
                   snip(msg, 100) if msg else "never blocked within 12 calls"]
        if allowed == 0 and "budget" in msg.lower():
            s.note = "budget already used up by an earlier run: bash scripts/reset.sh, then retry"
        return bool(msg) and "budget" in msg.lower() and allowed >= 1

    def s7(self, s: Scene) -> bool:
        r1 = chat("chat-deepseek", MKT, PLAIN)
        g1 = p4.gov(r1)
        r2 = chat("chat-deepseek", MKT, [{"role": "user", "content":
                  f"Applicant SIN: {FAKE_SIN}. Summarize the employment letter in one line."}], max_tokens=40)
        g2 = p4.gov(r2)
        s.ids += [p4.call_id(r1), p4.call_id(r2)]
        t2 = text_of(r2)
        s.lines = [f"no PII : HTTP {r1.status} · {g1.get('action')} {g1.get('rule')} · \"{snip(text_of(r1), 60)}\"",
                   f"SIN    : HTTP {r2.status} · {g2.get('action')} {g2.get('rule')} · pii={g2.get('pii')} · "
                   f"routed to {g2.get('routed-model')}",
                   f"         local answer: \"{snip(clean(t2), 60)}\""]
        ok1 = r1.status == 200 and g1.get("action") == "pass" and "mock DeepSeek" in text_of(r1)
        ok2 = (r2.status == 200 and g2.get("action") == "reroute" and g2.get("rule") == "R9"
               and g2.get("routed-model") in LOCAL and "mock DeepSeek" not in t2)
        return ok1 and ok2

    def s8(self, s: Scene) -> bool:
        r = chat("chat-cloud", MKT, [{"role": "user", "content": p4.REDACT_PROMPT}], max_tokens=512)
        g, text = p4.gov(r), text_of(r)
        s.ids.append(p4.call_id(r))
        lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
        first = lines[0].upper() if lines else ""
        s.lines = [f"HTTP {r.status} · {g.get('action')} {g.get('rule')} · pii={g.get('pii')}",
                   f"Haiku's line 1: {first[:12] or '(empty)'}  (YES = it only saw a [placeholder])",
                   f"app receives  : \"{snip(lines[-1] if lines else '', 70)}\""]
        restored = FAKE_NAME in text and "[PERSON_" not in text
        if r.status == 200 and not first.startswith("YES"):
            s.note = "Haiku did not answer YES this time; the redaction headers and restored text still prove the path"
        return r.status == 200 and g.get("action") == "redact" and g.get("rule") == "R5" and restored

    def s9(self, s: Scene) -> bool:
        ok = True
        t = time.time()
        run(["docker", "compose", "stop", "-t", "3", PRESIDIO], timeout=60)
        try:
            r1 = chat("chat-deepseek", MKT, PLAIN)
            g1 = p4.gov(r1)
            r2 = chat("chat-default", UW, PLAIN)
            g2 = p4.gov(r2)
            s.ids += [p4.call_id(r1), p4.call_id(r2)]
            s.lines = [f"Presidio stopped ({time.time() - t:.1f} s)",
                       f"no PII → chat-deepseek : {g1.get('action')} {g1.get('rule')} · reason {g1.get('reason')}",
                       f"no PII → chat-default  : {g2.get('action')} {g2.get('rule')} (local stays available)"]
            ok &= (r1.status == 200 and g1.get("action") == "reroute"
                   and g1.get("reason") == p4.pii_policy.REASON_DETECTOR)
            ok &= r2.status == 200 and g2.get("action") == "pass"
        finally:
            secs = ensure_presidio()
        r3 = chat("chat-deepseek", MKT, PLAIN)
        g3 = p4.gov(r3)
        s.ids.append(p4.call_id(r3))
        s.lines.append(f"Presidio back in {secs:.0f} s → chat-deepseek: {g3.get('action')} {g3.get('rule')}"
                       if secs >= 0 else "Presidio did not come back within 120 s")
        return ok and secs >= 0 and g3.get("action") == "pass"

    # ---- audit trail ----
    def trail(self, done: list[Scene]) -> None:
        ids = [i for s in done for i in s.ids if i]
        if not ids:
            return
        self.banner("Audit trail for this run (governance.pii_audit + spend log)")
        p4.audit_rows(ids, wait=20)               # wait for the success callback to fill in the served model
        try:
            rows = audit.fetch_rows(ids=ids, limit=len(ids) + 5)
        except audit.QueryError as e:
            print(f"   {status_word('FAIL')} {e}")
            self.audit_ok = False
            return
        shown = {i for s in done if s.num in SHOW_IN_TRAIL for i in s.ids}
        table = sorted((r for r in rows if r["call_id"] in shown), key=lambda r: r.get("ts") or "")
        if table:
            print("\n".join("   " + x for x in audit.render_rows(table).splitlines()))
        hidden = len(rows) - len(table)
        if hidden:
            print(c("2", f"   (+ {hidden} more rows from the rate-limit and budget scenes: python3 scripts/audit.py --since 10m)"))
        by_id = {r["call_id"]: r for r in rows}
        checks = []
        for s in done:
            if s.num == 7 and len(s.ids) >= 2:
                r = by_id.get(s.ids[1], {})
                checks.append(r.get("rule") == "R9" and r.get("served_model") in LOCAL)
            if s.num == 8 and s.ids:
                r = by_id.get(s.ids[0], {})
                checks.append(r.get("rule") == "R5" and (r.get("redacted") or 0) >= 1 and r.get("served_model") == "chat-cloud")
            if s.num == 9 and s.ids:
                r = by_id.get(s.ids[0], {})
                checks.append(r.get("reason") == p4.pii_policy.REASON_DETECTOR)
        dump = json.dumps(rows)
        no_text = FAKE_SIN not in dump and FAKE_NAME not in dump and all(
            all(isinstance(v, int) for v in (r.get("pii_counts") or {}).values()) for r in rows)
        self.audit_ok = all(checks) and no_text and len(rows) == len(set(ids))
        print(f"\n   {status_word('PASS' if self.audit_ok else 'FAIL')} {len(rows)}/{len(set(ids))} requests audited; "
              f"PII stored as types and counts only{'' if no_text else ' — RAW TEXT FOUND'}. "
              "Spend shows … until the batched spend log lands.")

    # ---- main ----
    def run(self) -> int:
        print(c("1", "LLM Gateway & Governance — live demo") + c("2", "   (Demo Mortgage Co., fictional)"))
        if not self.a.no_reset:
            self.banner("Reset demo state")
            if not do_reset():
                return 1
        if not self.preflight():
            print("\n" + status_word("FAIL") + " preflight failed; fix the line above and run again")
            return 1
        only = {int(x) for x in self.a.only.split(",") if x.strip()} if self.a.only else None
        done = []
        for s in SCENES:
            if only and s.num not in only:
                continue
            self.banner(f"Scene {s.num}/9 · {s.title}" + ("  [cloud]" if s.cloud else ""))
            self.line("Why", c("2", s.why))
            self.line("Expect", s.expect)
            if s.cloud and not self.cloud:
                s.status, s.note = "SKIP", self.cloud_reason
                self.line("Result", f"{status_word('SKIP')}  {s.note}")
                done.append(s)
                continue
            self.pause()
            t = time.time()
            try:
                good = getattr(self, f"s{s.num}")(s)
            except Exception as e:  # noqa: BLE001  one broken scene must not stop the show
                good, s.lines = False, s.lines + [f"{type(e).__name__}: {e}"]
            s.secs = time.time() - t
            s.status = "PASS" if good else "FAIL"
            for i, x in enumerate(s.lines):
                self.line("Actual" if i == 0 else "", x)
            if s.note:
                self.line("Note", c("33", s.note))
            self.line("Result", f"{status_word(s.status)}  ({s.secs:.1f} s)")
            done.append(s)
        self.trail([s for s in done if s.status != "SKIP"])
        return self.summary(done)

    def summary(self, done: list[Scene]) -> int:
        n = {k: sum(1 for s in done if s.status == k) for k in ("PASS", "FAIL", "SKIP")}
        total = time.time() - self.t0
        audit_txt = {True: "PASS", False: "FAIL", None: "n/a"}[self.audit_ok]
        self.banner("Summary")
        print(f"   {len(done)} scenes · {status_word('PASS')} {n['PASS']} · {status_word('FAIL')} {n['FAIL']} · "
              f"{status_word('SKIP')} {n['SKIP']} · audit trail {status_word(audit_txt) if self.audit_ok is not None else 'n/a'} · "
              f"{total:.0f} s total")
        failed = n["FAIL"] or self.audit_ok is False
        if self.a.json_summary:
            Path(self.a.json_summary).write_text(json.dumps({
                "pass": n["PASS"], "fail": n["FAIL"], "skip": n["SKIP"], "audit": audit_txt, "seconds": round(total, 1),
                "cloud": self.cloud, "cloud_reason": self.cloud_reason,
                "scenes": [{"num": s.num, "status": s.status, "secs": round(s.secs, 1), "note": s.note} for s in done]},
                indent=2) + "\n", encoding="utf-8")
        return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the demo")
    r.add_argument("--pace", action="store_true", help="pause before each scene")
    r.add_argument("--offline", action="store_true", help="skip the cloud scene even when online")
    r.add_argument("--only", default="", help="comma-separated scene numbers, e.g. 7,8,9")
    r.add_argument("--no-reset", action="store_true", help="do not rebuild the demo keys first")
    r.add_argument("--json-summary", default="", help=argparse.SUPPRESS)
    sub.add_parser("reset", help="rebuild demo-budget and demo-ratelimit, make sure Presidio is up")
    a = ap.parse_args()
    if a.cmd == "reset":
        print(c("1", "Reset demo state"))
        ok = do_reset()
        print(("\n" + status_word("PASS") + " ready for bash scripts/demo.sh") if ok else ("\n" + status_word("FAIL")))
        return 0 if ok else 1
    demo = Demo(a)
    try:
        return demo.run()
    except KeyboardInterrupt:
        print("\n" + c("33", "interrupted: making sure Presidio is running …"))
        ensure_presidio(timeout=60)
        return 130


if __name__ == "__main__":
    sys.exit(main())
