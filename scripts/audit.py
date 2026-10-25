#!/usr/bin/env python3
"""Policy audit query (P5). Shows the governance plugin's decisions from governance.pii_audit,
joined with LiteLLM spend logs. The admin UI cannot see this table; this is its command-line view.

  python3 scripts/audit.py                          # last 20 decisions, newest first
  python3 scripts/audit.py --since 1h --action reroute
  python3 scripts/audit.py --team marketing --limit 50
  python3 scripts/audit.py --summary --since 24h    # counts by action, rule, reason, team; detector health
  python3 scripts/audit.py --ids <call_id>,<call_id>
  python3 scripts/audit.py --json                   # machine-readable rows

The table holds only types, counts and rule IDs: no prompt, response or PII value is stored, so none can be shown.
Standard library only; it reads Postgres through `docker compose exec postgres psql` (the database has no host port).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p2check import psql  # noqa: E402

ACTIONS = ("pass", "redact", "reroute", "block")
UNITS = {"m": "minutes", "h": "hours", "d": "days"}
COLUMNS = ("ts", "call_id", "team", "key_alias", "requested_model", "routed_model", "served_model", "outcome",
           "pii_counts", "level", "reason", "action", "rule", "detector_status", "language", "detect_ms",
           "redacted", "stream", "policy_version")


SPEND_JOIN = 'join "LiteLLM_SpendLogs" s on s.litellm_call_id = a.call_id'


class QueryError(ValueError):
    pass


def since_sql(since: str) -> str:
    """'15m' / '2h' / '7d' -> a safe SQL interval literal."""
    m = re.fullmatch(r"(\d{1,4})([mhd])", since.strip())
    if not m:
        raise QueryError(f"--since must look like 15m, 2h or 7d, got {since!r}")
    return f"interval '{int(m.group(1))} {UNITS[m.group(2)]}'"


def where_clause(since: str | None = None, action: str | None = None, team: str | None = None,
                 ids: list[str] | None = None) -> str:
    """Every filter is validated or reduced to a safe character set before it reaches SQL."""
    parts = []
    if since:
        parts.append(f"a.ts >= now() - {since_sql(since)}")
    if action:
        if action not in ACTIONS:
            raise QueryError(f"--action must be one of {', '.join(ACTIONS)}")
        parts.append(f"a.action = '{action}'")
    if team:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", team):
            raise QueryError("--team takes a team alias such as marketing")
        parts.append(f"a.team = '{team}'")
    if ids:
        clean = [re.sub(r"[^0-9a-f-]", "", i.lower()) for i in ids]
        clean = [i for i in clean if i]
        if not clean:
            raise QueryError("--ids takes LiteLLM call IDs (the x-litellm-call-id response header)")
        parts.append("a.call_id in (" + ",".join(f"'{i}'" for i in clean) + ")")
    return ("where " + " and ".join(parts)) if parts else ""


def rows_sql(where: str, limit: int) -> str:
    cols = ", ".join(f"a.{c}" for c in COLUMNS)
    return ("select coalesce(json_agg(row_to_json(t)), '[]') from ("
            f"select {cols}, (select sum(s.spend) from \"LiteLLM_SpendLogs\" s where s.litellm_call_id = a.call_id) as spend "
            f"from governance.pii_audit a {where} order by a.ts desc limit {int(limit)}) t")


def summary_sql(where: str) -> str:
    def src(join: str = "", extra: str = "") -> str:
        cond = " and ".join(x for x in (where[len("where "):] if where else "", extra) if x)
        return f"from governance.pii_audit a {join} " + (f"where {cond}" if cond else "")

    def counts(col: str) -> str:
        return f"(select coalesce(json_object_agg(k, n), '{{}}') from (select {col} k, count(*) n {src()} group by 1) x)"

    return ("select json_build_object("
            f"'total', (select count(*) {src()}), "
            f"'first', (select min(a.ts) {src()}), 'last', (select max(a.ts) {src()}), "
            f"'by_action', {counts('a.action')}, 'by_rule', {counts('a.rule')}, 'by_reason', {counts('a.reason')}, "
            f"'by_outcome', {counts('a.outcome')}, 'by_detector', {counts('a.detector_status')}, "
            f"'by_team', (select coalesce(json_agg(x), '[]') from (select coalesce(a.team, '-') team, a.action, count(*) n "
            f"{src()} group by 1, 2 order by 1, 2) x), "
            f"'pii_types', (select coalesce(json_object_agg(k, n), '{{}}') from (select e.key k, sum(e.value::int) n "
            f"{src('cross join lateral jsonb_each_text(a.pii_counts) e')} group by 1) x), "
            f"'detect_ms', (select json_build_object('p50', percentile_disc(0.5) within group (order by a.detect_ms), "
            f"'p95', percentile_disc(0.95) within group (order by a.detect_ms), 'max', max(a.detect_ms)) "
            f"{src(extra='a.detect_ms is not null')}), "
            f"'spend', (select coalesce(sum(s.spend), 0) "
            f"{src(SPEND_JOIN)})"
            ")")


def query(sql: str):
    code, out = psql(sql)
    out = out.strip()
    if code != 0 or not out or out[0] not in "[{":
        raise QueryError(f"psql failed (exit {code}): {out[:300]}")
    return json.loads(out)


def fetch_rows(since=None, action=None, team=None, ids=None, limit: int = 20) -> list[dict]:
    return query(rows_sql(where_clause(since, action, team, ids), limit))


def fetch_summary(since=None, action=None, team=None) -> dict:
    return query(summary_sql(where_clause(since, action, team)))


# ---------- rendering ----------
def local_time(ts: str | None, fmt: str = "%m-%d %H:%M:%S") -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromisoformat(ts).astimezone().strftime(fmt)
    except ValueError:
        return ts[:19]


def pii_text(counts) -> str:
    if not counts:
        return "-"
    return ",".join(f"{k}:{v}" for k, v in sorted(counts.items()))


def money(v) -> str:
    if v is None:
        return "…"            # spend log is written in batches; it shows up a few seconds later
    return f"${float(v):.6f}"


def route_text(r: dict) -> str:
    req, served = r.get("requested_model") or "-", r.get("served_model")
    if r.get("outcome") == "blocked":
        return f"{req} → (blocked)"
    if not served:
        return f"{req} → …"
    return req if served == req else f"{req} → {served}"


def render_rows(rows: list[dict], wide: bool = False) -> str:
    head = ["TIME", "TEAM", "REQUESTED → SERVED", "ACTION", "RULE", "REASON", "PII", "SPEND"]
    if wide:
        head += ["KEY", "DETECTOR", "MS", "LANG", "CALL ID"]
    table = [head]
    for r in rows:
        line = [local_time(r.get("ts")), r.get("team") or "-", route_text(r), r.get("action") or "-",
                r.get("rule") or "-", r.get("reason") or "-", pii_text(r.get("pii_counts")), money(r.get("spend"))]
        if wide:
            line += [r.get("key_alias") or "-", r.get("detector_status") or "-",
                     str(r.get("detect_ms") if r.get("detect_ms") is not None else "-"), r.get("language") or "-",
                     r.get("call_id") or "-"]
        table.append(line)
    if len(table) == 1:
        return "(no audit rows match)"
    widths = [max(len(str(row[i])) for row in table) for i in range(len(head))]
    out = []
    for n, row in enumerate(table):
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def _pct(n: int, total: int) -> str:
    return f"{n:>5}  {n / total:6.1%}" if total else f"{n:>5}"


def render_summary(s: dict) -> str:
    total = int(s.get("total") or 0)
    if not total:
        return "(no audit rows match)"
    lines = [f"Policy decisions: {total}   from {local_time(s.get('first'), '%Y-%m-%d %H:%M')} "
             f"to {local_time(s.get('last'), '%Y-%m-%d %H:%M')}   spend ${float(s.get('spend') or 0):.6f}", ""]

    def block(title: str, d: dict, order: tuple = ()) -> None:
        lines.append(title)
        keys = [k for k in order if k in d] + sorted(k for k in d if k not in order)
        for k in keys:
            lines.append(f"  {k:<22}{_pct(int(d[k]), total)}")
        lines.append("")

    block("By action", s.get("by_action") or {}, ACTIONS)
    block("By rule", s.get("by_rule") or {}, tuple(f"R{i}" for i in range(1, 11)))
    block("By reason", s.get("by_reason") or {}, ("none", "detected", "detector_unavailable", "language_unsupported"))
    block("Outcome", s.get("by_outcome") or {}, ("success", "failure", "blocked", "pending"))
    block("Detector status", s.get("by_detector") or {}, ("ok", "timeout", "error", "unavailable", "skipped"))
    pii = s.get("pii_types") or {}
    lines.append("PII entities detected (instances)")
    lines += [f"  {k:<22}{int(v):>5}" for k, v in sorted(pii.items(), key=lambda kv: -int(kv[1]))] or ["  (none)"]
    lines.append("")
    teams: dict[str, dict] = {}
    for x in s.get("by_team") or []:
        teams.setdefault(x["team"], {})[x["action"]] = x["n"]
    lines.append("By team          " + "".join(f"{a:>9}" for a in ACTIONS))
    for t, d in sorted(teams.items()):
        lines.append(f"  {t:<15}" + "".join(f"{d.get(a, 0):>9}" for a in ACTIONS))
    ms = s.get("detect_ms") or {}
    if ms.get("p50") is not None:
        lines += ["", f"Detection latency  p50 {ms['p50']} ms   p95 {ms['p95']} ms   max {ms['max']} ms"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="time window, e.g. 15m, 2h, 7d")
    ap.add_argument("--action", choices=ACTIONS)
    ap.add_argument("--team", help="team alias, e.g. marketing")
    ap.add_argument("--ids", help="comma-separated LiteLLM call IDs")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--summary", action="store_true", help="aggregate counts instead of rows")
    ap.add_argument("--wide", action="store_true", help="also show key alias, detector, latency, language, call ID")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args(argv)
    ids = [x for x in (a.ids or "").split(",") if x.strip()] or None
    try:
        if a.summary:
            data = fetch_summary(a.since, a.action, a.team)
            print(json.dumps(data, indent=2, default=str) if a.json else render_summary(data))
        else:
            data = fetch_rows(a.since, a.action, a.team, ids, max(1, min(a.limit, 1000)))
            print(json.dumps(data, indent=2, default=str) if a.json else render_rows(data, a.wide))
    except QueryError as e:
        print(f"audit: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:      # piped into head / less and closed early
        sys.exit(0)
