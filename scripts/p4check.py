#!/usr/bin/env python3
"""P4 安全护栏检查工具，只用 Python 标准库。复用 p2check / p3check 的报告、HTTP、psql 与 key 工具。

子命令（按子阶段排列；【计费】= 会产生真实的 Anthropic 费用，每次不到 $0.001）
  P4a  infra       Presidio 容器：镜像锁定、无对外端口、健康、识别器已加载、内存；LiteLLM 容器依赖齐全
                   --coldstart 额外重启 Presidio 并计时到健康
       detect      不经网关：在 LiteLLM 容器里用插件同一份检测代码跑测试语料，出检测率报告
  P4b  unit        离线单元测试（tests/test_pii.py）：处置矩阵每一格、兜底、白名单阻断、脱敏还原
  P4c  mode        【人工】切换 policy.toml 的 enforcement（off / route / full）并重启 LiteLLM
       audit-init  建 governance schema 与审计表（可重复运行），验证约束挡得住原文
       allowlist    最先验证：静态白名单 + 改道目标白名单（R10 阻断）
       route       语料逐条发往 chat-deepseek（模拟）、chat-default、chat-cloud（只发会被改道的），核对处置
       audit       审计行与费用日志一一对应；审计表里查不到语料中的任何 PII 原文
  P4d  redact      【计费】chat-cloud 非流式：一般敏感被脱敏，回答还原
       stream      【计费】chat-cloud 流式：缓存还原后仍是标准 SSE 流；未脱敏的流式不受影响
  P4e  failclosed  停掉、暂停 Presidio：发往 DeepSeek 与云端的请求被改道，审计原因为“检测器不可用”
       lang        中文、法语、西语、俄语发往 DeepSeek 被改道，原因“无法检测”
       nolog       【计费】标记串 + 假 PII：整库导出与四个容器日志都搜不到
       persist     --save 重启前存快照；不带参数在重启后比对审计行数、策略模式、Presidio 状态
       record      把一段文本写进 docs/p4-results.md 的指定小节

结果写入 docs/p4-results.md 对应小节（重跑覆盖）。有 FAIL 时退出码为 1。任何输出里都不打印命中的 PII 原文。
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2check as base  # noqa: E402
import p3check as p3  # noqa: E402  （导入时它把报告文件指向 p3，下面再改回 p4）
from p2check import GW, Report, http, psql, run, snip  # noqa: E402

ROOT = base.ROOT
base.RESULTS = ROOT / "docs" / "p4-results.md"
POLICY_FILE = ROOT / "governance" / "policy.toml"
AUDIT_SQL = ROOT / "governance" / "audit.sql"
CORPUS = ROOT / "tests" / "pii_corpus.jsonl"
STATE = ROOT / ".secrets" / "p4-state.json"
sys.path.insert(0, str(ROOT / "litellm"))
import pii_policy  # noqa: E402

PRESIDIO = "presidio-analyzer"
LOCAL = ("chat-default", "chat-fallback")
MKT, UW, OPS, CLOUD_ONLY = "mkt-copywriter", "uw-loan-assistant", "ops-runbook-bot", "demo-cloud-only"
FAKE_SIN = "193 456 787"          # 能通过 Luhn 的假 SIN（语料 H01），不是任何人的号码
FAKE_NAME = "Emily Tremblay"      # 语料里的假名字


def header() -> None:
    if not base.RESULTS.exists():
        base.RESULTS.parent.mkdir(parents=True, exist_ok=True)
        base.RESULTS.write_text("# P4 实测结果\n\n由 scripts/p4check.py 自动写入，各小节重跑时覆盖。"
                                "表格里只有类型、数量与规则编号，不含任何 PII 原文。\n", encoding="utf-8")


def policy() -> pii_policy.Policy:
    return pii_policy.load_policy(POLICY_FILE)


def corpus() -> list[dict]:
    return [json.loads(x) for x in CORPUS.read_text(encoding="utf-8").splitlines() if x.strip()]


def messages_of(case: dict) -> list[dict]:
    return case.get("messages") or [{"role": "user", "content": case["text"]}]


def key(alias: str) -> str:
    return p3.key_of(alias)


def gov(r: base.Resp) -> dict:
    return {k[len("x-governance-"):]: v for k, v in r.headers.items() if k.startswith("x-governance-")}


def call_id(r: base.Resp) -> str:
    return r.headers.get("x-litellm-call-id", "")


def chat(alias: str, k: str, messages: list, max_tokens: int = 16, **extra) -> base.Resp:
    body = {"model": alias, "messages": messages, "max_tokens": max_tokens}
    body.update(extra)
    return http("POST", f"{GW}/v1/chat/completions", k, body, timeout=180)


def stream_chat(alias: str, k: str, content: str, max_tokens: int = 512) -> tuple[int, dict, int, str]:
    """流式调用：返回 (状态码, 响应头, 数据块数, 拼起来的文本)。"""
    body = json.dumps({"model": alias, "messages": [{"role": "user", "content": content}],
                       "max_tokens": max_tokens, "stream": True}).encode()
    req = urllib.request.Request(f"{GW}/v1/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            hdr = {a.lower(): b for a, b in r.headers.items()}
            n, parts, done = 0, [], False
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if line == "data: [DONE]":
                    done = True
                elif line.startswith("data: "):
                    n += 1
                    for ch in json.loads(line[6:]).get("choices", []):
                        c = (ch.get("delta") or {}).get("content")
                        if c:
                            parts.append(c)
            return r.status, hdr, n if done else -n, "".join(parts)
    except urllib.error.HTTPError as e:
        return e.code, {}, 0, e.read().decode("utf-8", "replace")[:200]


def audit_rows(ids: list[str], wait: int = 30) -> dict[str, dict]:
    """按 call_id 取审计行；served_model 由成功回调异步回填，最多等 wait 秒。"""
    if not ids:
        return {}
    in_list = ",".join("'" + re.sub(r"[^0-9a-f-]", "", i) + "'" for i in ids)
    sql = ("select coalesce(json_agg(row_to_json(a)), '[]') from (select call_id, team, key_alias, requested_model, "
           "routed_model, served_model, outcome, pii_counts, level, reason, action, rule, detector_status, language, "
           f"detect_ms, redacted, stream from governance.pii_audit where call_id in ({in_list})) a")
    rows: dict = {}
    for _ in range(max(1, wait // 3)):
        code, out = psql(sql)
        rows = {r["call_id"]: r for r in (json.loads(out) if code == 0 and out.strip().startswith("[") else [])}
        if len(rows) >= len(ids) and all(r["outcome"] != "pending" for r in rows.values()):
            break
        time.sleep(3)
    return rows


def in_litellm(code: str, timeout: float = 60) -> tuple[int, str]:
    return run(["docker", "compose", "exec", "-T", "litellm", "python3", "-c", code], timeout=timeout)


def presidio_health(timeout: int = 180) -> float:
    """从 LiteLLM 容器里探测 Presidio 健康（宿主机没有端口）。返回秒数，超时返回 -1。"""
    t0 = time.time()
    code = ("import urllib.request,sys\n"
            "try:\n urllib.request.urlopen('http://presidio-analyzer:3000/health',timeout=3); print('ok')\n"
            "except Exception as e: print(type(e).__name__)")
    while time.time() - t0 < timeout:
        rc, out = in_litellm(code, timeout=20)
        if rc == 0 and out.strip().endswith("ok"):
            return time.time() - t0
        time.sleep(3)
    return -1


def wait_gateway(timeout: int = 240) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if http("GET", f"{GW}/health/liveliness", timeout=5).status == 200:
            return time.time() - t0
        time.sleep(3)
    return -1


def state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(**kw) -> None:
    s = state()
    s.update(kw)
    STATE.parent.mkdir(mode=0o700, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    STATE.chmod(0o600)


def need_mode(rep: Report, *modes: str) -> bool:
    m = policy().enforcement
    if m not in modes:
        rep.add("FAIL", "策略模式", f"当前 enforcement={m}，本检查需要 {' 或 '.join(modes)}（python3 scripts/p4check.py mode …）")
        return False
    rep.add("PASS", "策略模式", f"enforcement={m}")
    return True


def last_policy_line() -> str:
    lines = [x for x in base.logs("30m", "litellm").splitlines() if "policy_check:" in x or "policy_error" in x]
    return lines[-1] if lines else ""


# ---------- P4a ----------
def cmd_infra(a) -> int:
    rep = Report("infra", "P4a 基础设施：Presidio 与 LiteLLM 依赖")
    img = base.compose_images().get("presidio", "")
    rep.add("PASS" if re.search(r":\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$", img) else "FAIL", "Presidio 镜像锁定版本与摘要",
            img or "compose 里没有 presidio-analyzer 的 image 行")
    cid = base.container_id(PRESIDIO)
    if not cid:
        rep.add("FAIL", "Presidio 容器", "没有运行：docker compose up -d")
        return rep.finish()
    rep.add("PASS" if base.inspect(cid, "{{.State.Health.Status}}") == "healthy" else "FAIL", "Presidio 健康检查",
            base.inspect(cid, "{{.State.Health.Status}}"))
    ports = base.inspect(cid, "{{json .NetworkSettings.Ports}}")
    published = re.findall(r'"HostPort":"(\d+)"', ports)
    rep.add("FAIL" if published else "PASS", "Presidio 不映射宿主机端口", ", ".join(published) or "无")
    rep.add("FAIL" if base.tcp_open("127.0.0.1", 3000) else "PASS", "宿主机连不上 127.0.0.1:3000", "")
    code = ("import urllib.request,json\n"
            "r=json.load(urllib.request.urlopen('http://presidio-analyzer:3000/supportedentities?language=en',timeout=10))\n"
            "print(json.dumps(sorted(r)))")
    rc, out = in_litellm(code)
    try:
        ents = set(json.loads(out.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        ents = set()
    need = set(policy().entities)
    miss = sorted(need - ents)
    rep.add("PASS" if rc == 0 and not miss else "FAIL", "策略里的实体 Presidio 都支持",
            f"缺 {', '.join(miss)}" if miss else f"{len(need)} 种齐全（含 CA_SIN、CA_BANK_ACCOUNT、CA_POSTAL_CODE、STREET_ADDRESS）")
    rc, out = in_litellm("import sys,tomllib,psycopg,httpx;print(sys.version.split()[0],psycopg.__version__,httpx.__version__)")
    rep.add("PASS" if rc == 0 else "FAIL", "LiteLLM 容器：tomllib、psycopg、httpx 可用", snip(out, 80))
    rc, out = in_litellm("import os;print(os.path.exists('/app/governance/policy.toml'),os.environ.get('PRESIDIO_URL'))")
    rep.add("PASS" if out.strip().startswith("True http://presidio-analyzer") else "FAIL", "策略文件与 PRESIDIO_URL 已挂进 LiteLLM", snip(out, 80))
    _, stats = run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"], timeout=30)
    mem = [x for x in stats.splitlines() if PRESIDIO in x]
    rep.add("INFO", "Presidio 内存", mem[0].split(" ", 1)[1] if mem else "取不到")
    rep.add("INFO", "策略模式", f"enforcement={policy().enforcement}；日志最后一行：{snip(last_policy_line()[25:], 90)}")
    if a.coldstart:
        run(["docker", "compose", "restart", PRESIDIO], timeout=120)
        secs = presidio_health()
        rep.add("PASS" if secs >= 0 else "FAIL", "Presidio 冷启动到健康", f"{secs:.0f} 秒" if secs >= 0 else "180 秒内未就绪")
    return rep.finish()


def cmd_detect(_a) -> int:
    rep = Report("detect", "P4a 检测率（不经网关，插件同一份检测代码）")
    cases = corpus()
    rc, out = run(["docker", "compose", "exec", "-T", "-e", "DETECT_TIMEOUT=30", "litellm", "python3",
                   "/app/config/pii_detect.py"], timeout=300, input_text=CORPUS.read_text(encoding="utf-8"))
    got = {}
    for line in out.splitlines():
        if line.startswith("{"):
            r = json.loads(line)
            got[r["id"]] = r
    if rc != 0 or len(got) != len(cases):
        rep.add("FAIL", "运行检测", f"退出码 {rc}，{len(got)}/{len(cases)} 条有结果：{snip(out, 160)}")
        return rep.finish()
    rows = ["| 用例 | 语言判定 | 预期 | 检测到 | 结果 | 耗时 |", "| --- | --- | --- | --- | --- | --- |"]
    exp_n = hit_n = fp_n = 0
    per: dict[str, list[int]] = {}
    status_bad = [c["id"] for c in cases if got[c["id"]]["status"] != "ok"]
    for c in cases:
        g = got[c["id"]]
        found = sorted(g["counts"])
        if c["expect"] is None:
            verdict = "不计（非英文）"
        else:
            e = sorted(c["expect"])
            miss = [x for x in e if x not in found]
            extra = [x for x in found if x not in e]
            exp_n += len(e)
            hit_n += len(e) - len(miss)
            fp_n += len(extra)
            for x in e:
                per.setdefault(x, [0, 0])[0] += 1
                per[x][1] += x not in miss
            verdict = "一致" if not miss and not extra else "；".join(
                ([f"漏检 {', '.join(miss)}"] if miss else []) + ([f"误报 {', '.join(extra)}"] if extra else []))
        rows.append(f"| {c['id']} | {g['lang']} | {', '.join(c['expect'] or []) or '—'} | "
                    f"{', '.join(f'{k}:{v}' for k, v in sorted(g['counts'].items())) or '—'} | {verdict} | {g['ms']} ms |")
    lang_ok = all(got[c["id"]]["lang"] == {"en": "en", "zh": "script", "ru": "script"}.get(c["lang"], c["lang"]) for c in cases)
    rate = hit_n / exp_n if exp_n else 0
    rep.add("PASS" if not status_bad else "FAIL", "Presidio 每条都返回结果", "、".join(status_bad) or f"{len(cases)} 条")
    rep.add("PASS" if rate == 1 else "WARN", "英文用例检测率（实体实例）", f"{hit_n}/{exp_n} = {rate:.0%}")
    rep.add("PASS" if fp_n == 0 else "WARN", "英文用例误报", f"{fp_n} 个")
    rep.add("PASS" if lang_ok else "FAIL", "语言判定（中文、俄语、法语、西语）全部正确", "")
    ms = sorted(got[c["id"]]["ms"] for c in cases)
    rep.add("INFO", "单次检测耗时", f"中位数 {ms[len(ms) // 2]} ms，最大 {ms[-1]} ms（第一条含预热）")
    per_rows = ["| 实体 | 预期 | 检出 |", "| --- | --- | --- |"] + [f"| {k} | {v[0]} | {v[1]} |" for k, v in sorted(per.items())]
    return rep.finish("\n".join(rows) + "\n\n" + "\n".join(per_rows) +
                      "\n\n漏检与误报如实保留，写进 P4 文档的检测率报告；非英文用例按决策 25 由语言判定处理，不计入检测率。")


# ---------- P4b ----------
def cmd_unit(_a) -> int:
    rep = Report("unit", "P4b 处置矩阵单元测试（离线）")
    rc, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], timeout=120)
    m = re.search(r"Ran (\d+) tests?", out)
    cells = len(re.findall(r"test_every_cell", out))
    rep.add("PASS" if rc == 0 else "FAIL", "单元测试", f"{m.group(1) if m else '?'} 个，{'全部通过' if rc == 0 else '有失败'}")
    rep.add("PASS" if cells else "FAIL", "处置矩阵九格逐格测试", "test_every_cell 覆盖 R1–R9；另有 R10 阻断、故障与非英文兜底")
    if rc != 0:
        print(out[-3000:])
    return rep.finish()


# ---------- P4c ----------
def cmd_mode(a) -> int:
    rep = Report("mode", "策略模式切换")
    text = POLICY_FILE.read_text(encoding="utf-8")
    new = re.sub(r'^enforcement = "[a-z]+"', f'enforcement = "{a.mode}"', text, count=1, flags=re.M)
    if new != text:
        with POLICY_FILE.open("r+", encoding="utf-8") as f:     # 原地改写，保持同一个文件
            f.seek(0)
            f.write(new)
            f.truncate()
    rep.add("PASS", "policy.toml", f"enforcement = \"{a.mode}\"" + ("（未变）" if new == text else ""))
    rc, out = run(["docker", "compose", "restart", "litellm"], timeout=180)
    rep.add("PASS" if rc == 0 else "FAIL", "docker compose restart litellm", snip(out, 80))
    secs = wait_gateway()
    rep.add("PASS" if secs >= 0 else "FAIL", "网关恢复", f"{secs:.0f} 秒" if secs >= 0 else "240 秒内未恢复")
    r = chat("chat-default", key(UW), [{"role": "user", "content": "Reply with one word: pong"}])
    line = last_policy_line()
    rep.add("PASS" if r.status == 200 and f"(p4-{a.mode})" in line else "FAIL", "插件以新模式运行", snip(line[25:], 100))
    return rep.finish("记得把 policy.toml 的这次改动和本小节一起提交：模式切换本身是需要审计的策略变更。")


def cmd_audit_init(_a) -> int:
    rep = Report("audit-init", "审计表")
    code, out = psql(AUDIT_SQL.read_text(encoding="utf-8"))
    rep.add("PASS" if code == 0 else "FAIL", "执行 governance/audit.sql", snip(out, 80))
    code, out = psql("select count(*) from governance.pii_audit")
    rep.add("PASS" if code == 0 else "FAIL", "governance.pii_audit 可查询", f"{out.strip()} 行")
    code, out = psql("begin; insert into governance.pii_audit (call_id, requested_model, routed_model, level, reason, "
                     "action, rule, detector_status, language, policy_version, pii_counts) values ('constraint-test', "
                     "'m', 'm', 'none', 'none', 'pass', 'R1', 'ok', 'en', 'test', '{\"PERSON\": \"x\"}'); rollback;")
    rep.add("PASS" if code != 0 and "pii_counts_types_only" in out else "FAIL", "约束拒绝把文本写进 pii_counts", snip(out, 90))
    return rep.finish()


def cmd_allowlist(_a) -> int:
    rep = Report("allowlist", "P4c 最先验证：白名单与改道")
    if not need_mode(rep, "route", "full"):
        return rep.finish()
    sin = [{"role": "user", "content": f"Applicant SIN: {FAKE_SIN}. Please verify the employment letter."}]
    plain = [{"role": "user", "content": "Write a one-line tagline for spring mortgage renewals."}]
    ids = []
    r = chat("chat-deepseek", key(UW), plain)
    rep.add("PASS" if r.status in (401, 403) else "FAIL", "静态层：审批团队调用 chat-deepseek 被 LiteLLM 拒绝",
            f"HTTP {r.status}：{snip(r.err_msg(), 90)}")
    r = chat("chat-deepseek", key(MKT), plain)
    ok = r.status == 200 and gov(r).get("action") == "pass" and "mock DeepSeek" in base.answer(r)[0]
    rep.add("PASS" if ok else "FAIL", "市场团队无 PII → chat-deepseek 放行（模拟部署回答）", f"{r.status} {gov(r)}")
    r = chat("chat-deepseek", key(MKT), sin)
    g = gov(r)
    ok = r.status == 200 and g.get("action") == "reroute" and g.get("routed-model") == "chat-default"
    rep.add("PASS" if ok else "FAIL", "市场团队含 SIN → 改道到 chat-default（R9）", f"{r.status} rule={g.get('rule')} pii={g.get('pii')}")
    ids.append(call_id(r))
    rows = p3.spend_rows([call_id(r)], 1)
    grp = rows[0]["group"] if rows else "（无）"
    rep.add("PASS" if grp in LOCAL else "FAIL", "费用日志里实际模型是本地", f"model_group={grp}")
    r = chat("chat-deepseek", key(CLOUD_ONLY), sin)
    rep.add("PASS" if r.status == 403 and "R10" in r.err_msg() else "FAIL",
            "只有云端模型的 key 含 SIN → 无处改道，阻断（R10）", f"HTTP {r.status}：{snip(r.err_msg(), 100)}")
    blocked = call_id(r) or ""
    r = chat("chat-deepseek", key(CLOUD_ONLY), plain)
    rep.add("PASS" if r.status == 200 and gov(r).get("action") == "pass" else "FAIL", "同一个 key 无 PII 照常放行", f"{r.status}")
    code, out = psql("select action, rule, outcome from governance.pii_audit where key_alias = 'demo-cloud-only' "
                     "and action = 'block' order by ts desc limit 1")
    rep.add("PASS" if out.strip().startswith("block|R10|blocked") else "FAIL", "阻断写进审计表", out.strip() or "无")
    return rep.finish(
        "结论：LiteLLM 只在鉴权时查一次模型白名单（源码 auth_checks.can_key_call_model），钩子里改写目标模型不会再查；"
        "所以插件在改道前自己核对 key 与团队白名单，目标不在白名单就按 R10 阻断。白名单配置因此不用为改道放宽："
        "每个能用云端或 DeepSeek 的团队本来就有 chat-default。" + (f" 阻断请求的 call_id：{blocked}" if blocked else ""))


def expected_action(p: pii_policy.Policy, case: dict, jurisdiction: str) -> str:
    lang_ok = case["lang"] == "en"
    counts = {e: 1 for e in (case["expect"] or [])}
    return pii_policy.decide(p, requested="x", jurisdiction=jurisdiction, counts=counts, detector_ok=True,
                             language_ok=lang_ok, allowed_models=None).action


def cmd_route(_a) -> int:
    rep = Report("route", "P4c 驻留路由：语料逐条核对")
    if not need_mode(rep, "route", "full"):
        return rep.finish()
    p = policy()
    plan = [("chat-deepseek", MKT, "CN"), ("chat-default", UW, "local"), ("chat-cloud", OPS, "US")]
    rows = ["| 用例 | 目标 | 预期 | 实际 | 规则 | 原因 | 检测到 | 实际模型 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    ids, results = [], []
    for alias, who, jur in plan:
        for c in corpus():
            exp = expected_action(p, c, jur)
            if alias == "chat-cloud" and exp != "reroute":
                continue    # 只发会被改道的（零费用）；放行与脱敏在 P4d 用真实云端单独测
            r = chat(alias, key(who), messages_of(c))
            cid = call_id(r)
            ids.append(cid)
            results.append((c, alias, exp, r, cid))
    audit = audit_rows(ids, wait=60)
    mismatch_policy = mismatch_expect = 0
    for c, alias, exp, r, cid in results:
        g = gov(r)
        row = audit.get(cid, {})
        served = row.get("served_model") or "—"
        act = g.get("action", f"HTTP {r.status}")
        # 1) 插件的决定必须与“它实际检测到的类型”按策略算出的一致（这是纵深防御的核心，不一致即 FAIL）
        counts = row.get("pii_counts") or {}
        should = pii_policy.decide(p, requested=alias, jurisdiction={"chat-deepseek": "CN", "chat-cloud": "US"}.get(alias, "local"),
                                   counts=counts, detector_ok=row.get("detector_status") == "ok",
                                   language_ok=row.get("language") == "en", allowed_models=None).action
        bad_policy = r.status != 200 or act != should or (act == "reroute" and served not in LOCAL)
        mismatch_policy += bad_policy
        # 2) 与语料预期比：不一致多半是检测漏检或误报，记 WARN，如实写进报告
        mismatch_expect += act != exp
        rows.append(f"| {c['id']} | {alias} | {exp} | {act}{' ✗' if bad_policy else ''} | {g.get('rule', '—')} | "
                    f"{g.get('reason', '—')} | {g.get('pii', '—')} | {served} |")
    rep.add("PASS" if not mismatch_policy else "FAIL", "插件决定与策略一致，改道的都由本地模型回答",
            f"{len(results) - mismatch_policy}/{len(results)} 条")
    rep.add("PASS" if not mismatch_expect else "WARN", "与语料标注的预期处置一致",
            f"{len(results) - mismatch_expect}/{len(results)} 条（不一致见下表，通常是漏检或误报）")
    rep.add("PASS" if len(audit) == len(ids) else "FAIL", "每个请求都有审计行", f"{len(audit)}/{len(ids)}")
    save_state(route_call_ids=ids)
    return rep.finish("\n".join(rows))


def cmd_audit(_a) -> int:
    rep = Report("audit", "P4c 审计表：能对上费用日志，查不到原文")
    ids = state().get("route_call_ids", [])
    if not ids:
        rep.add("FAIL", "route 的 call_id", "没有记录，先运行 python3 scripts/p4check.py route")
        return rep.finish()
    audit = audit_rows(ids)
    spend = {x["call_id"]: x for x in p3.spend_rows(ids, len(ids), wait=90)}
    ok = [i for i in ids if i in audit and audit[i]["outcome"] == "success" and i in spend]
    rep.add("PASS" if len(ok) == len(ids) else "FAIL", "审计行 ↔ 费用日志一一对应（litellm_call_id）", f"{len(ok)}/{len(ids)}")
    same = [i for i in ok if spend[i]["group"] == audit[i]["served_model"]]
    rep.add("PASS" if len(same) == len(ok) else "FAIL", "审计的实际模型 = 费用日志的 model_group", f"{len(same)}/{len(ok)}")
    p = policy()
    bad = [i for i in ids if any(k not in p.entity_level or not isinstance(v, int) for k, v in (audit.get(i, {}).get("pii_counts") or {}).items())]
    rep.add("PASS" if not bad else "FAIL", "pii_counts 只有策略里的实体类型与整数", f"{len(bad)} 行异常")
    rc, dump = run(["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "litellm", "--data-only",
                    "--schema=governance", "litellm"], timeout=120)
    secrets_list = sorted({v for c in corpus() for v in c.get("pii", [])})
    leaked = [v for v in secrets_list if v in dump]
    rep.add("PASS" if rc == 0 and not leaked else "FAIL", "governance schema 导出里搜不到语料中的任何 PII",
            f"搜索 {len(secrets_list)} 个假 PII 值，命中 {len(leaked)} 个（导出 {len(dump) // 1024} KB）")
    code, out = psql("select action, count(*) from governance.pii_audit group by action order by action")
    rep.add("INFO", "审计表按处置汇总", out.replace("\n", "；"))
    return rep.finish()


# ---------- P4d ----------
REDACT_PROMPT = ("Answer on two lines. Line 1: YES if the sentence below contains a placeholder in square brackets, "
                 f"otherwise NO. Line 2: repeat the sentence exactly.\nSentence: Please mail the renewal letter to {FAKE_NAME}.")


def cmd_redact(_a) -> int:
    rep = Report("redact", "P4d 脱敏（非流式）【计费】")
    if not need_mode(rep, "full") or not p3.cloud_ready():
        rep.add("FAIL" if not p3.cloud_ready() else "INFO", "Anthropic key", "为空" if not p3.cloud_ready() else "")
        return rep.finish()
    r = chat("chat-cloud", key(MKT), [{"role": "user", "content": REDACT_PROMPT}], max_tokens=512)
    g, text = gov(r), base.answer(r)[0]
    rep.add("PASS" if r.status == 200 and g.get("action") == "redact" and g.get("rule") == "R5" else "FAIL",
            "一般敏感发往 chat-cloud → 脱敏（R5）", f"{r.status} pii={g.get('pii')}")
    rep.add("PASS" if FAKE_NAME in text and "[PERSON_" not in text else "FAIL", "回答里的占位符已还原成原文",
            "含原名、无残留占位符" if FAKE_NAME in text else snip(text.replace(FAKE_NAME, "<名字>"), 80))
    first = text.strip().splitlines()[0].upper() if text.strip() else ""
    rep.add("PASS" if first.startswith("YES") else "WARN", "云端模型看到的是占位符（它回答 YES）", first[:20] or "空")
    row = audit_rows([call_id(r)]).get(call_id(r), {})
    rep.add("PASS" if row.get("redacted", 0) >= 1 and row.get("served_model") == "chat-cloud" else "FAIL",
            "审计：redacted≥1，实际模型 chat-cloud", f"redacted={row.get('redacted')} served={row.get('served_model')}")
    return rep.finish("云端拿不到原文的直接证据：它回答 YES，说明收到的句子里是 [PERSON_1]；单元测试另外断言发出的 messages 里没有原文。")


def cmd_stream(_a) -> int:
    rep = Report("stream", "P4d 脱敏（流式）【计费】")
    if not need_mode(rep, "full") or not p3.cloud_ready():
        return rep.finish()
    st, hdr, n, text = stream_chat("chat-cloud", key(MKT), REDACT_PROMPT)
    g = {k[len("x-governance-"):]: v for k, v in hdr.items() if k.startswith("x-governance-")}
    rep.add("PASS" if st == 200 and g.get("action") == "redact" else "FAIL", "流式请求同样脱敏（R5）", f"{st} pii={g.get('pii')}")
    rep.add("PASS" if n > 0 else "FAIL", "仍是标准 SSE：多个 data 块并以 [DONE] 结束", f"{abs(n)} 块" + ("" if n > 0 else "，没有 [DONE]"))
    rep.add("PASS" if FAKE_NAME in text and "[PERSON_" not in text else "FAIL", "拼起来的回答已还原",
            "含原名、无残留占位符" if FAKE_NAME in text else snip(text.replace(FAKE_NAME, "<名字>"), 80))
    st, hdr, n, text = stream_chat("chat-default", key(UW), "Count from 1 to 10, separated by commas.", max_tokens=64)
    rep.add("PASS" if st == 200 and n > 3 else "FAIL", "不需要还原的流式照常逐块输出（本地，零费用）", f"{abs(n)} 块")
    return rep.finish("需要还原的流式请求要等云端生成完才开始输出（决策 23 的代价），协议本身不变。")


# ---------- P4e ----------
def _probe(rep: Report, label: str, expect_reason: str) -> None:
    plain = [{"role": "user", "content": "Write a one-line tagline for spring mortgage renewals."}]
    t0 = time.time()
    r = chat("chat-deepseek", key(MKT), plain)
    g = gov(r)
    rep.add("PASS" if r.status == 200 and g.get("action") == "reroute" and g.get("reason") == expect_reason else "FAIL",
            f"{label}：无 PII 发往 chat-deepseek 也被改道", f"{r.status} rule={g.get('rule')} reason={g.get('reason')} {time.time() - t0:.1f}s")
    r2 = chat("chat-default", key(UW), plain)
    g2 = gov(r2)
    rep.add("PASS" if r2.status == 200 and g2.get("action") == "pass" else "FAIL", f"{label}：本地请求照常放行",
            f"{r2.status} rule={g2.get('rule')} reason={g2.get('reason')}")
    row = audit_rows([call_id(r)]).get(call_id(r), {})
    rep.add("PASS" if row.get("reason") == expect_reason and row.get("detector_status") != "ok" else "FAIL",
            f"{label}：审计原因为“检测器不可用”", f"reason={row.get('reason')} detector={row.get('detector_status')}")


def cmd_failclosed(_a) -> int:
    rep = Report("failclosed", "P4e fail-closed")
    if not need_mode(rep, "route", "full"):
        return rep.finish()
    try:
        run(["docker", "compose", "stop", PRESIDIO], timeout=120)
        _probe(rep, "Presidio 停止", pii_policy.REASON_DETECTOR)
        run(["docker", "compose", "start", PRESIDIO], timeout=120)
        secs = presidio_health()
        rep.add("PASS" if secs >= 0 else "FAIL", "Presidio 重新启动到健康", f"{secs:.0f} 秒")
        run(["docker", "compose", "pause", PRESIDIO], timeout=60)
        _probe(rep, "Presidio 无响应（暂停）", pii_policy.REASON_DETECTOR)
    finally:
        run(["docker", "compose", "unpause", PRESIDIO], timeout=60)
        run(["docker", "compose", "start", PRESIDIO], timeout=120)
    presidio_health()
    r = chat("chat-deepseek", key(MKT), [{"role": "user", "content": "Write a one-line tagline for spring mortgage renewals."}])
    rep.add("PASS" if gov(r).get("action") == "pass" else "FAIL", "恢复后无 PII 请求重新放行", f"{r.status} {gov(r).get('rule')}")
    return rep.finish("暂停时请求要等满超时（policy.toml 的 timeout_seconds）才改道；停止时连接被拒，立即改道。")


def cmd_lang(_a) -> int:
    rep = Report("lang", "P4e 非英文按无法检测处理")
    if not need_mode(rep, "route", "full"):
        return rep.finish()
    for c in corpus():
        if c["lang"] == "en" and c["id"] != "N02":
            continue
        r = chat("chat-deepseek", key(MKT), messages_of(c))
        g = gov(r)
        want = ("pass", "none") if c["lang"] == "en" else ("reroute", pii_policy.REASON_LANGUAGE)
        rep.add("PASS" if (g.get("action"), g.get("reason")) == want else "FAIL", f"{c['id']}（{c['lang']}）→ chat-deepseek",
                f"{g.get('action')} {g.get('rule')} {g.get('reason')}")
    return rep.finish()


def cmd_nolog(_a) -> int:
    rep = Report("nolog", "P4e 不存原文：标记串 + 假 PII【计费】")
    if not need_mode(rep, "full") or not p3.cloud_ready():
        return rep.finish()
    canary = "CANARY-" + secrets.token_hex(6)
    needles = [canary, FAKE_NAME, FAKE_SIN, "emily.tremblay@example.com"]
    r1 = chat("chat-cloud", key(MKT), [{"role": "user", "content":
              f"Repeat exactly: Mail the letter to {FAKE_NAME} at emily.tremblay@example.com, ref {canary}."}], max_tokens=512)
    rep.add("PASS" if r1.status == 200 and gov(r1).get("action") == "redact" else "FAIL", "脱敏路径（云端）", f"{r1.status} {gov(r1).get('pii')}")
    r2 = chat("chat-cloud", key(MKT), [{"role": "user", "content": f"Applicant SIN: {FAKE_SIN}, ref {canary}. Reply OK."}])
    rep.add("PASS" if r2.status == 200 and gov(r2).get("action") == "reroute" else "FAIL", "改道路径（本地）", f"{r2.status} {gov(r2).get('rule')}")
    audit_rows([call_id(r1), call_id(r2)])
    p3.spend_rows([call_id(r1), call_id(r2)], 2)
    rc, dump = run(["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "litellm", "--data-only", "litellm"], timeout=180)
    hit = [n for n in needles if n in dump]
    rep.add("PASS" if rc == 0 and not hit else "FAIL", "整库导出（含 governance 审计表）搜不到", f"{len(hit)} 个命中，导出 {len(dump) // 1024} KB")
    logs = base.logs("15m", None)
    hit = [n for n in needles if n in logs]
    rep.add("PASS" if not hit else "FAIL", "四个容器（含 Presidio）的日志搜不到", f"{len(hit)} 个命中，日志 {len(logs) // 1024} KB")
    return rep.finish(f"搜索 {len(needles)} 个值：标记串、假名字、假邮箱、假 SIN。")


def cmd_persist(a) -> int:
    rep = Report("persist", "P4e 重启后保持")
    code, out = psql("select count(*) from governance.pii_audit")
    n = int(out.strip() or 0) if code == 0 else -1
    if a.save:
        save_state(persist={"audit_rows": n, "mode": policy().enforcement, "ts": datetime.now().isoformat()})
        rep.add("PASS" if n >= 0 else "FAIL", "已保存", f"审计 {n} 行，enforcement={policy().enforcement}；现在运行 wsl --shutdown 或 docker compose restart")
        return rep.finish()
    saved = state().get("persist")
    if not saved:
        rep.add("FAIL", "没有保存的快照", "先运行 python3 scripts/p4check.py persist --save")
        return rep.finish()
    rep.add("PASS" if n >= saved["audit_rows"] else "FAIL", "审计行数没有减少", f"{saved['audit_rows']} → {n}")
    rep.add("PASS" if wait_gateway() >= 0 else "FAIL", "网关恢复", "")
    secs = presidio_health()
    rep.add("PASS" if secs >= 0 else "FAIL", "Presidio 自动恢复健康", f"{secs:.0f} 秒")
    r = chat("chat-deepseek", key(MKT), [{"role": "user", "content": f"Applicant SIN: {FAKE_SIN}. Reply OK."}])
    rep.add("PASS" if gov(r).get("action") == "reroute" else "FAIL", "重启后驻留路由仍生效", f"{r.status} {gov(r).get('rule')}")
    return rep.finish()


def cmd_record(a) -> int:
    header()
    base.write_section(a.section, a.title or a.section, a.text)
    print(f"已写入 {base.RESULTS.relative_to(ROOT)} 的 {a.section} 小节")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("detect", "unit", "audit-init", "allowlist", "route", "audit", "redact", "stream", "failclosed", "lang", "nolog"):
        sub.add_parser(name)
    p = sub.add_parser("infra")
    p.add_argument("--coldstart", action="store_true")
    p = sub.add_parser("mode")
    p.add_argument("mode", choices=pii_policy.MODES)
    p = sub.add_parser("persist")
    p.add_argument("--save", action="store_true")
    p = sub.add_parser("record")
    p.add_argument("section")
    p.add_argument("--title", default="")
    p.add_argument("--text", required=True)
    a = ap.parse_args()
    header()
    return globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    sys.exit(main())
