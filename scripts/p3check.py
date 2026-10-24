#!/usr/bin/env python3
"""P3 治理检查工具，只用 Python 标准库（tomllib 需 Python 3.11+）。复用 p2check.py 的报告与 HTTP 工具。

子命令
  secrets    密钥改用 Compose secrets：文件、权限、忽略、历史，docker inspect 与 compose config 无明文
  infra      P2 的基础设施检查 + P3：包装入口生效、云端别名已配置、云端 key 已挂载
  admin      【人工】创建有独立密码的界面管理员（交互输入密码，执行器不运行）
  login      管理员已完成首次改密；env 登录按 config 开关生效；Master Key 仍能调管理 API
  org        按 governance/org.toml 创建或更新团队与 key（幂等），key 存 .secrets/p3-keys.json
  access     团队白名单：每个 key 只看到本团队模型；审批团队调用云端被拒；市场团队可以
  pricing    内部结算价：本地调用按 config.yaml 单价计费；费用日志 N 次请求正好 N 行；降级按实际模型计价
  budget     预算：重建 demo-budget key，连续调用直到被阻断
  ratelimit  限流：demo-ratelimit 连发 7 次，第 6 次起返回 429
  cloud      云端：Haiku 5.5 真实调用，应用传的采样参数被丢弃，费用 = token × 官方单价，云端无降级链
  nolog      云端请求同样不存原文（标记串搜整库导出与容器日志）
  reconcile  对账：汇总网关记录的云端 token 与费用；--console-in/--console-out 与 Console 比对
  persist    --save 重启前存快照；不带参数在重启后比对团队、key、预算、已用额度
  record     把一段文本写进 docs/p3-results.md 的指定小节

结果写入 docs/p3-results.md 对应小节（重跑覆盖）。有 FAIL 时退出码为 1。任何输出里密钥只显示前 6 位。
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import secrets
import sys
import time
import tomllib
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2check as base  # noqa: E402
from p2check import GW, Report, answer, http, mask, psql, run, snip  # noqa: E402

ROOT = base.ROOT
base.RESULTS = ROOT / "docs" / "p3-results.md"   # 复用 P2 的报告类，结果写到 P3 文件
ORG_FILE = ROOT / "governance" / "org.toml"
CONFIG = ROOT / "litellm" / "config.yaml"
SECRETS = ROOT / ".secrets"
KEYS_FILE = SECRETS / "p3-keys.json"
STATE_FILE = SECRETS / "p3-persist.json"
SECRET_NAMES = ["litellm_master_key", "litellm_salt_key", "postgres_password", "anthropic_api_key"]
ADMIN_ID = "gateway-admin"
ADMIN_EMAIL = "admin@demo-mortgage.example"
CLOUD = "chat-cloud"
# Haiku 5.5 官方单价（提示 ≤10 万 token 档），与镜像自带价格表一致；对账用
CLOUD_PRICE = {"in": 0.10e-6, "out": 0.50e-6}


def ensure_results_header() -> None:
    if not base.RESULTS.exists():
        base.RESULTS.parent.mkdir(parents=True, exist_ok=True)
        base.RESULTS.write_text("# P3 实测结果\n\n由 scripts/p3check.py 自动写入，各小节重跑时覆盖。\n", encoding="utf-8")


# ---------- 读取配置 ----------
def load_org() -> dict:
    return tomllib.loads(ORG_FILE.read_text(encoding="utf-8"))


def config_prices() -> dict:
    """从 config.yaml 读每个逻辑名的自定义单价（不依赖 PyYAML，按行解析本仓库的固定格式）。"""
    prices, cur = {}, None
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*-\s*model_name:\s*(\S+)", line)
        if m:
            cur = m.group(1)
            prices[cur] = {}
            continue
        m = re.match(r"\s*(input|output)_cost_per_token:\s*([0-9.eE+-]+)", line)
        if m and cur:
            prices[cur]["in" if m.group(1) == "input" else "out"] = float(m.group(2))
    return prices


def config_flag(name: str) -> str:
    m = re.search(rf"^\s*{name}:\s*(\S+)", CONFIG.read_text(encoding="utf-8"), re.M)
    return m.group(1).lower() if m else ""


def load_keys() -> dict:
    return json.loads(KEYS_FILE.read_text(encoding="utf-8")) if KEYS_FILE.exists() else {}


def save_keys(keys: dict) -> None:
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    KEYS_FILE.chmod(0o600)


def key_of(alias: str) -> str:
    return load_keys().get(alias, {}).get("key", "")


def secret_file(name: str) -> str:
    f = SECRETS / name
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def mk() -> str:
    return base.master_key()


def cloud_ready() -> bool:
    return bool(secret_file("anthropic_api_key"))


def chat(alias: str, key: str, content: str, max_tokens: int = 64, **extra) -> base.Resp:
    body = {"model": alias, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
    body.update(extra)
    return http("POST", f"{GW}/v1/chat/completions", key, body)


def usage(r: base.Resp) -> tuple[int, int]:
    u = r.json().get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def spend_rows(call_ids: list[str], want: int, wait: int = 90) -> list[dict]:
    """按 litellm_call_id 取费用日志行；费用日志批量写入，最多等 wait 秒直到行数达到 want。"""
    if not call_ids:
        return []
    ids = ",".join("'" + re.sub(r"[^0-9a-f-]", "", c) + "'" for c in call_ids)
    sql = ("select coalesce(json_agg(json_build_object('request_id', request_id, 'call_id', litellm_call_id, "
           "'spend', spend, 'pt', prompt_tokens, 'ct', completion_tokens, 'model', model, 'group', model_group, "
           f"'team', team_id)), '[]') from \"LiteLLM_SpendLogs\" where litellm_call_id in ({ids})")
    rows: list = []
    for _ in range(max(1, wait // 5)):
        code, out = psql(sql)
        rows = json.loads(out) if code == 0 and out.strip().startswith("[") else []
        if len(rows) >= want:
            break
        time.sleep(5)
    return rows


def key_info(key: str) -> dict:
    r = http("GET", f"{GW}/key/info?key={urllib.parse.quote(key)}", mk(), timeout=20)
    return r.json().get("info", {}) if r.status == 200 else {}


def teams_by_alias() -> dict:
    r = http("GET", f"{GW}/team/list", mk(), timeout=30)
    data = r.json() if r.status == 200 else []
    if isinstance(data, dict):
        data = data.get("teams", [])
    return {t.get("team_alias"): t for t in data if isinstance(t, dict) and t.get("team_alias")}


def logs_since(minutes: int = 5) -> str:
    return base.logs(f"{minutes}m", "litellm")


# ---------- secrets ----------
def cmd_secrets(_a) -> int:
    rep = Report("secrets", "密钥：Compose secrets")
    d = SECRETS
    rep.add("PASS" if d.exists() and (d.stat().st_mode & 0o777) == 0o700 else "WARN", ".secrets/ 目录权限 700",
            oct(d.stat().st_mode & 0o777) if d.exists() else "不存在")
    vals = {}
    for n in SECRET_NAMES:
        f = d / n
        if not f.exists():
            rep.add("FAIL", f".secrets/{n}", "不存在，人工运行 bash scripts/gen-secrets.sh")
            continue
        v = f.read_text(encoding="utf-8").strip()
        mode = f.stat().st_mode & 0o777
        empty_ok = n == "anthropic_api_key"
        st = "PASS" if mode == 0o600 and (v or empty_ok) else "FAIL"
        if not v and empty_ok:
            st = "WARN"
        rep.add(st, f".secrets/{n}", f"{oct(mode)}，{mask(v) if v else '空'}")
        code, _ = run(["git", "check-ignore", "-q", f".secrets/{n}"])
        if code != 0:
            rep.add("FAIL", f".secrets/{n} 被 .gitignore 忽略", "没有！")
        if len(v) >= 12:
            vals[n] = v
    if (ROOT / ".env").exists():
        env = base.read_env()
        left = [k for k in ("LITELLM_MASTER_KEY", "LITELLM_SALT_KEY", "POSTGRES_PASSWORD") if env.get(k)]
        rep.add("FAIL" if left else "PASS", ".env 不再保存密钥", ", ".join(left))
    else:
        rep.add("PASS", ".env 不再保存密钥", ".env 已删除")
    bak = ROOT / ".env.p2-backup"
    if bak.exists():
        old = {k: v for k, v in (l.split("=", 1) for l in bak.read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))}
        for var, n in (("LITELLM_SALT_KEY", "litellm_salt_key"), ("POSTGRES_PASSWORD", "postgres_password")):
            if old.get(var):
                rep.add("PASS" if old[var].strip() == secret_file(n) else "FAIL", f"{n} 与迁移前 .env 逐字一致", "")
        rep.add("INFO", ".env.p2-backup 仍在", "P3 验收通过后删除（步骤 12）")
    code, cfg = run(["docker", "compose", "config"])
    if code == 0:
        hits = [n for n, v in vals.items() if v in cfg]
        rep.add("FAIL" if hits else "PASS", "docker compose config 不含密钥明文", ", ".join(hits))
    else:
        rep.add("FAIL", "docker compose config", snip(cfg, 160))
    for svc in ("litellm", "postgres"):
        cid = base.container_id(svc)
        if not cid:
            rep.add("FAIL", f"{svc} 容器", "未运行")
            continue
        env_json = base.inspect(cid, "{{json .Config.Env}}")
        hits = [n for n, v in vals.items() if v in env_json]
        rep.add("FAIL" if hits else "PASS", f"docker inspect {svc} 的环境变量不含密钥明文", ", ".join(hits))
        mounts = base.inspect(cid, "{{json .Mounts}}")
        rep.add("PASS" if "/run/secrets/" in mounts else "FAIL", f"{svc} 以 /run/secrets 挂载密钥", "")
    code, names = run(["git", "log", "--all", "--name-only", "--pretty=format:"], timeout=120)
    bad = sorted({n for n in names.splitlines() if n.startswith(".secrets/") or n == ".env" or n.startswith(".env.p")})
    rep.add("FAIL" if bad else "PASS", "历史中从未提交 .env、.secrets/、.env 备份", ", ".join(bad))
    code, hist = run(["git", "log", "--all", "-p", "--no-color", "--no-ext-diff"], timeout=300)
    for n, v in vals.items():
        rep.add("FAIL" if v in hist else "PASS", f"git 历史中没有 {n} 的值", "")
    for alias, rec in load_keys().items():
        if rec.get("key") and rec["key"] in hist:
            rep.add("FAIL", f"git 历史中出现 {alias} 的 key", mask(rec["key"]))
    for pat, label in base.TOKEN_PATTERNS:
        hits = sorted({m for m in re.findall(pat, hist) if not m.startswith(("sk-1234", "sk-xxxx"))})
        rep.add("FAIL" if hits else "PASS", f"git 历史中没有{label}格式的字符串", ", ".join(mask(h) for h in hits[:5]))
    home = Path.home()
    prof = [p.name for p in (home / ".bashrc", home / ".profile", home / ".bash_profile", Path("/etc/environment"))
            if p.exists() and "ANTHROPIC_API_KEY" in p.read_text(encoding="utf-8", errors="ignore")]
    import os
    rep.add("FAIL" if prof or os.environ.get("ANTHROPIC_API_KEY") else "PASS",
            "Anthropic key 没有设成 Ubuntu 全局环境变量（否则 Claude Code 改用 API 计费）", ", ".join(prof))
    return rep.finish("密钥只以文件形式挂进容器；容器内进程环境里仍有明文，只有容器 root 可见，这是已知边界。")


# ---------- infra ----------
def cmd_infra(a) -> int:
    code = base.cmd_infra(a)
    rep = Report("infra-p3", "基础设施（P3 增项）")
    cid = base.container_id("litellm")
    ep = base.inspect(cid, "{{json .Config.Entrypoint}}") if cid else ""
    rep.add("PASS" if "/app/config/entrypoint.sh" in ep else "FAIL", "LiteLLM 用包装入口读取 secrets", ep)
    r = http("GET", f"{GW}/v1/models", mk(), timeout=15)
    ids = [m.get("id") for m in r.json().get("data", [])]
    rep.add("PASS" if CLOUD in ids else "FAIL", f"/v1/models 含 {CLOUD}", ", ".join(map(str, ids)))
    rep.add("PASS" if cloud_ready() else "WARN", "Anthropic key 已配置", "" if cloud_ready() else "为空：chat-cloud 不可用")
    out = logs_since(30)
    rep.add("FAIL" if "缺少密钥文件" in out else "PASS", "入口脚本没有报缺少密钥", "")
    return max(code, rep.finish())


# ---------- admin / login ----------
def _policy_problems(pw: str) -> list[str]:
    p = []
    if len(pw) < 12:
        p.append("至少 12 位")
    if not re.search(r"[A-Z]", pw):
        p.append("大写字母")
    if not re.search(r"[a-z]", pw):
        p.append("小写字母")
    if not re.search(r"\d", pw):
        p.append("数字")
    if not re.search(r"[^A-Za-z0-9]", pw):
        p.append("特殊字符")
    return p


def cmd_admin(a) -> int:
    rep = Report("admin", "界面管理员账号")
    if not sys.stdin.isatty():
        rep.add("FAIL", "需要人工在终端运行", "这一步要输入密码，执行器不运行")
        return rep.finish()
    email = a.email
    r = http("GET", f"{GW}/user/info?user_id={ADMIN_ID}", mk(), timeout=20)
    exists = r.status == 200 and (r.json().get("user_info") or {}).get("user_id") == ADMIN_ID
    if not exists:
        body = {"user_id": ADMIN_ID, "user_email": email, "user_role": "proxy_admin", "auto_create_key": False,
                "user_alias": "Gateway Admin"}
        r = http("POST", f"{GW}/user/new", mk(), body, timeout=30)
        if r.status != 200:
            rep.add("FAIL", "创建管理员", f"{r.status} {r.err_msg()}")
            return rep.finish()
        rep.add("PASS", "创建管理员", f"user_id {ADMIN_ID}，登录名 {email}，角色 proxy_admin")
    else:
        rep.add("INFO", "管理员已存在", f"user_id {ADMIN_ID}；本次只重设临时密码")
    print("设置临时密码（≥12 位，含大小写、数字、特殊字符；首次登录界面会要求改成正式密码）")
    while True:
        pw = getpass.getpass("临时密码：")
        probs = _policy_problems(pw)
        if probs:
            print("不符合要求，缺：" + "、".join(probs))
            continue
        if getpass.getpass("再输一次：") != pw:
            print("两次不一致")
            continue
        break
    r = http("POST", f"{GW}/user/update", mk(), {"user_id": ADMIN_ID, "password": pw}, timeout=30)
    rep.add("PASS" if r.status == 200 else "FAIL", "设置临时密码", "已设置，首次登录须改密" if r.status == 200 else f"{r.status} {r.err_msg()}")
    rep.add("INFO", "下一步", f"浏览器打开 {GW}/ui/，用 {email} 和临时密码登录并改密，然后运行 p3check.py login")
    return rep.finish()


def cmd_login(_a) -> int:
    rep = Report("login", "界面登录方式")
    r = http("GET", f"{GW}/user/info?user_id={ADMIN_ID}", mk(), timeout=20)
    rep.add("PASS" if r.status == 200 else "FAIL", "Master Key 仍能调用管理 API", f"/user/info → {r.status}")
    info = r.json().get("user_info") or {}
    if not info:
        rep.add("FAIL", "管理员账号", f"找不到 {ADMIN_ID}，先人工运行 p3check.py admin")
        return rep.finish()
    rep.add("PASS" if info.get("user_role") == "proxy_admin" else "FAIL", "管理员角色", str(info.get("user_role")))
    reset = info.get("password_reset_required")
    rep.add("PASS" if reset is False else "WARN", "管理员已完成首次登录改密",
            "是" if reset is False else f"password_reset_required={reset}：先在浏览器登录并改密，再关闭 env 登录")
    flag = config_flag("disable_env_credential_login")
    r = http("POST", f"{GW}/login", None, {"username": "admin", "password": mk()}, timeout=20, form=True)
    if flag == "true":
        rep.add("PASS" if r.status in (401, 403) else "FAIL", "admin + Master Key 不能再登录界面",
                f"HTTP {r.status or r.error}" + ("" if r.status in (401, 403) else "：开关未生效？docker compose restart litellm"))
    else:
        rep.add("INFO", "env 登录仍开启", f"config 中 disable_env_credential_login={flag or '未写'}；admin + Master Key 登录 → HTTP {r.status}")
    return rep.finish()


# ---------- org ----------
def cmd_org(_a) -> int:
    rep = Report("org", "组织：团队与 key")
    org = load_org()
    teams = teams_by_alias()
    keys = load_keys()
    for t in org.get("team", []):
        body = {"team_alias": t["alias"], "models": t["models"], "max_budget": t.get("max_budget"),
                "budget_duration": t.get("budget_duration"), "rpm_limit": t.get("rpm_limit"),
                "metadata": {"org": org.get("org"), "note": t.get("note", ""), "managed_by": "governance/org.toml"}}
        body = {k: v for k, v in body.items() if v is not None}
        if t["alias"] in teams:
            body["team_id"] = teams[t["alias"]]["team_id"]
            r = http("POST", f"{GW}/team/update", mk(), body, timeout=30)
            verb = "更新"
        else:
            r = http("POST", f"{GW}/team/new", mk(), body, timeout=30)
            verb = "创建"
        if r.status != 200:
            rep.add("FAIL", f"{verb}团队 {t['alias']}", f"{r.status} {r.err_msg()}")
            continue
        j = r.json()
        team_id = body.get("team_id") or j.get("team_id") or (j.get("data") or {}).get("team_id")
        rep.add("PASS", f"{verb}团队 {t['alias']}",
                f"模型 {','.join(t['models'])}；预算 ${t.get('max_budget')}/{t.get('budget_duration')}；{t.get('rpm_limit')} RPM")
        for k in t.get("key", []):
            kb = {"key_alias": k["alias"], "team_id": team_id, "max_budget": k.get("max_budget"),
                  "rpm_limit": k.get("rpm_limit"), "models": k.get("models"),
                  "metadata": {"note": k.get("note", ""), "managed_by": "governance/org.toml"}}
            kb = {x: v for x, v in kb.items() if v is not None}
            cur = keys.get(k["alias"], {}).get("key")
            if cur and key_info(cur):
                r = http("POST", f"{GW}/key/update", mk(), {"key": cur, **kb}, timeout=30)
                rep.add("PASS" if r.status == 200 else "FAIL", f"  更新 key {k['alias']}",
                        mask(cur) if r.status == 200 else f"{r.status} {r.err_msg()}")
                continue
            http("POST", f"{GW}/key/delete", mk(), {"key_aliases": [k["alias"]]}, timeout=30)  # 文件丢失时清掉同名旧 key
            r = http("POST", f"{GW}/key/generate", mk(), kb, timeout=30)
            newk = r.json().get("key", "")
            if r.status != 200 or not newk:
                rep.add("FAIL", f"  创建 key {k['alias']}", f"{r.status} {r.err_msg()}")
                continue
            keys[k["alias"]] = {"key": newk, "team": t["alias"]}
            save_keys(keys)
            limits = ", ".join(f"{x}={kb[x]}" for x in ("max_budget", "rpm_limit") if x in kb) or "继承团队"
            rep.add("PASS", f"  创建 key {k['alias']}", f"{mask(newk)}；{limits}；存 .secrets/p3-keys.json")
    extra = [a for a, t in teams_by_alias().items()
             if (t.get("metadata") or {}).get("managed_by") == "governance/org.toml" and a not in {x["alias"] for x in org.get("team", [])}]
    if extra:
        rep.add("WARN", "网关里有 org.toml 已删除的团队", ", ".join(extra))
    return rep.finish()


# ---------- access ----------
def cmd_access(_a) -> int:
    rep = Report("access", "团队模型白名单")
    org = load_org()
    for t in org.get("team", []):
        for k in t.get("key", []):
            key = key_of(k["alias"])
            if not key:
                rep.add("FAIL", f"{k['alias']}", "没有 key，先运行 p3check.py org")
                continue
            r = http("GET", f"{GW}/v1/models", key, timeout=15)
            seen = sorted(m.get("id") for m in r.json().get("data", []))
            want = sorted(k.get("models") or t["models"])
            rep.add("PASS" if seen == want else "FAIL", f"{k['alias']}（{t['alias']}）只看到本团队模型", ", ".join(seen))
    uw, mkt = key_of("uw-loan-assistant"), key_of("mkt-copywriter")
    r = chat("chat-default", uw, "Reply with one word: pong")
    rep.add("PASS" if r.status == 200 else "FAIL", "审批团队调用本地 chat-default", f"{r.status} {snip(answer(r)[0]) or r.err_msg()}")
    r = chat(CLOUD, uw, "Reply with one word: pong")
    msg = r.err_msg()
    rep.add("PASS" if r.status in (401, 403) else "FAIL", "审批团队调用云端 chat-cloud 被拒", f"HTTP {r.status}：{snip(msg, 120)}")
    if cloud_ready():
        r = chat(CLOUD, mkt, "Reply with one word: pong", max_tokens=512)
        rep.add("PASS" if r.status == 200 else "FAIL", "市场团队调用云端 chat-cloud", f"{r.status} {snip(answer(r)[0]) or r.err_msg()}")
    else:
        rep.add("WARN", "市场团队调用云端 chat-cloud", "跳过：Anthropic key 为空")
    return rep.finish("纵深防御的静态层：只有白名单挡不住把客户资料粘进市场团队的请求，那由 P4 的动态 PII 检测负责。")


# ---------- pricing ----------
def cmd_pricing(a) -> int:
    rep = Report("pricing", "内部结算价与费用日志")
    prices = config_prices()
    key = key_of("uw-loan-assistant")
    before = float(key_info(key).get("spend") or 0)
    ids, total = [], 0.0
    for i in range(a.n):
        r = chat("chat-default", key, f"Count from 1 to {10 + i}, separated by spaces.", max_tokens=60)
        cid = r.headers.get("x-litellm-call-id", "")
        if r.status == 200 and cid:
            ids.append(cid)
        else:
            rep.add("FAIL", f"第 {i + 1} 次调用", f"{r.status} {r.err_msg()}")
    rows = spend_rows(ids, len(ids))
    rep.add("PASS" if len(rows) == len(ids) else "FAIL", f"连续 {len(ids)} 次请求，费用日志正好 {len(ids)} 行",
            f"实际 {len(rows)} 行" + ("" if len(rows) == len(ids) else "：撞号丢行，检查插件 async_logging_hook 是否加载"))
    rids = [x["request_id"] for x in rows]
    ok_ids = len(set(rids)) == len(rids) and all(re.match(r"^chatcmpl-[0-9a-f-]{36}$", x) for x in rids)
    rep.add("PASS" if ok_ids else "FAIL", "费用日志主键唯一（chatcmpl-<litellm_call_id>）", snip(", ".join(rids[:2]), 90))
    p = prices.get("chat-default", {})
    bad = []
    for x in rows:
        want = x["pt"] * p.get("in", 0) + x["ct"] * p.get("out", 0)
        total += x["spend"]
        if abs(x["spend"] - want) > 1e-12:
            bad.append(f"{x['pt']}/{x['ct']} tok 记 {x['spend']:.3e}，应为 {want:.3e}")
    rep.add("PASS" if rows and not bad else "FAIL", "每行费用 = 输入 × $0.10/1M + 输出 × $0.40/1M",
            "; ".join(bad[:3]) or f"{len(rows)} 行合计 ${total:.8f}")
    after = before
    for _ in range(12):  # key 的已用额度异步累加
        after = float(key_info(key).get("spend") or 0)
        if after - before >= total - 1e-12:
            break
        time.sleep(5)
    rep.add("PASS" if abs((after - before) - total) < 1e-9 else "WARN", "key 已用额度增加量 = 费用日志合计",
            f"{before:.8f} → {after:.8f}（+{after - before:.8f}）")
    r = chat("chat-default", key, "Reply with one word: pong", mock_testing_fallbacks=True)
    cid = r.headers.get("x-litellm-call-id", "")
    rows = spend_rows([cid], 1) if r.status == 200 else []
    if rows:
        x, pf = rows[0], prices.get("chat-fallback", {})
        want = x["pt"] * pf.get("in", 0) + x["ct"] * pf.get("out", 0)
        rep.add("PASS" if "llama3.2" in x["model"] and abs(x["spend"] - want) < 1e-12 else "FAIL",
                "降级后按实际模型（llama3.2）的单价计费", f"model={x['model']}，{x['spend']:.3e}，应为 {want:.3e}")
    else:
        rep.add("FAIL", "降级请求的费用日志", f"{r.status} {r.err_msg()}")
    code, out = psql("select count(*) from \"LiteLLM_DailyTeamSpend\" where spend > 0")
    rep.add("PASS" if code == 0 and out.strip() not in ("", "0") else "WARN", "按团队的日汇总有数据（管理界面 Usage 页的数据源）",
            f"{out.strip() or '?'} 行；汇总有延迟时隔几分钟重跑")
    return rep.finish("内部结算价按“每 CPU 小时 $0.10”与 P1 实测吞吐折算，见 config.yaml 注释。")


# ---------- budget ----------
def cmd_budget(_a) -> int:
    rep = Report("budget", "预算超标阻断")
    org = load_org()
    team = next((t for t in org["team"] if any(k["alias"] == "demo-budget" for k in t.get("key", []))), None)
    kdef = next(k for k in team["key"] if k["alias"] == "demo-budget")
    tid = teams_by_alias().get(team["alias"], {}).get("team_id")
    http("POST", f"{GW}/key/delete", mk(), {"key_aliases": ["demo-budget"]}, timeout=30)
    r = http("POST", f"{GW}/key/generate", mk(), {"key_alias": "demo-budget", "team_id": tid, "max_budget": kdef["max_budget"],
                                                  "metadata": {"note": kdef.get("note", ""), "managed_by": "governance/org.toml"}}, timeout=30)
    key = r.json().get("key", "")
    if r.status != 200 or not key:
        rep.add("FAIL", "重建 demo-budget", f"{r.status} {r.err_msg()}")
        return rep.finish()
    keys = load_keys()
    keys["demo-budget"] = {"key": key, "team": team["alias"]}
    save_keys(keys)
    rep.add("PASS", "重建 demo-budget", f"{mask(key)}，预算 ${kdef['max_budget']}")
    blocked, calls, msg = False, 0, ""
    for i in range(12):
        r = chat("chat-default", key, "Count from 1 to 60, separated by spaces.", max_tokens=200)
        if r.status == 200:
            calls += 1
            pt, ct = usage(r)
            print(f"  第 {i + 1} 次：放行，{pt}+{ct} tok")
            time.sleep(1)
            continue
        msg = r.err_msg()
        blocked = "budget" in msg.lower()
        print(f"  第 {i + 1} 次：HTTP {r.status}")
        break
    # 拦截看内存里的实时计数，key 的已用额度是后台批量写库的，有几十秒延迟；等它落库再判定超支
    spend = 0.0
    for _ in range(18):
        spend = float(key_info(key).get("spend") or 0)
        if not blocked or spend >= kdef["max_budget"]:
            break
        time.sleep(5)
    rep.add("PASS" if blocked else "FAIL", "超出预算后请求被阻断", f"放行 {calls} 次后阻断，HTTP {r.status}" if blocked else f"12 次都放行，已用 ${spend:.6f}")
    rep.add("PASS" if "Budget has been exceeded" in msg else "WARN", "错误信息清楚", snip(msg, 160))
    per = spend / calls if calls else 0
    rep.add("PASS" if kdef["max_budget"] <= spend <= kdef["max_budget"] + per + 1e-9 else "WARN", "超支不超过一次调用的费用",
            f"已用 ${spend:.6f}，预算 ${kdef['max_budget']}，每次约 ${per:.6f}")
    return rep.finish("先放行、再结账的软上限：最后一次放行的调用可以把已用额度推过预算，之后的请求返回 422。")


# ---------- ratelimit ----------
def cmd_ratelimit(_a) -> int:
    rep = Report("ratelimit", "限流 429")
    key = key_of("demo-ratelimit")
    codes = []
    for _ in range(7):
        r = chat("chat-default", key, "Reply with one word: pong", max_tokens=4)
        codes.append(r.status)
        last = r
    first429 = codes.index(429) + 1 if 429 in codes else 0
    ok = codes[:5] == [200] * 5 and first429 == 6
    rep.add("PASS" if ok else ("WARN" if first429 and first429 < 6 else "FAIL"), "每分钟 5 次：前 5 次放行，第 6 次返回 429",
            " ".join(map(str, codes)) + ("" if ok or not first429 or first429 >= 6 else "（距上次运行不足 1 分钟，等 1 分钟重跑）"))
    if 429 in codes:
        rep.add("INFO", "429 的提示", snip(last.err_msg(), 160))
    return rep.finish("按请求数限流：CPU 推理太慢，按 token 限流难以在演示时间内触发。")


# ---------- cloud ----------
def cmd_cloud(_a) -> int:
    rep = Report("cloud", "云端模型 chat-cloud（Haiku 5.5）")
    if not cloud_ready():
        rep.add("FAIL", "Anthropic key", "为空：人工运行 bash scripts/gen-secrets.sh --anthropic 后 docker compose up -d litellm")
        return rep.finish()
    key = key_of("mkt-copywriter")
    r = chat(CLOUD, key, "In one sentence, what does a mortgage underwriter do?", max_tokens=512, temperature=0, top_p=0.5)
    cid = r.headers.get("x-litellm-call-id", "")
    pt, ct = usage(r)
    rep.add("PASS" if r.status == 200 else "FAIL", "经网关调用 Haiku 5.5（应用传了 temperature=0、top_p）",
            f"{r.secs:.1f}s，{pt}+{ct} tok，回答：{snip(answer(r)[0])}" if r.status == 200 else f"{r.status} {r.err_msg()}")
    if r.status != 200:
        return rep.finish()
    lg = logs_since(5)
    line = next((l for l in lg.splitlines() if cid and cid in l and "policy_check" in l), "")
    rep.add("PASS" if "temperature" in line and "top_p" in line else "FAIL", "插件丢弃了应用传的采样参数", snip(line.split("model=")[-1], 120))
    rows = spend_rows([cid], 1)
    if rows:
        x = rows[0]
        want = x["pt"] * CLOUD_PRICE["in"] + x["ct"] * CLOUD_PRICE["out"]
        rep.add("PASS" if abs(x["spend"] - want) < 1e-12 else "FAIL", "费用 = 输入 × $0.10/1M + 输出 × $0.50/1M",
                f"{x['pt']}+{x['ct']} tok，记 ${x['spend']:.8f}，应为 ${want:.8f}")
        rep.add("INFO", "云端请求的费用日志主键由 LiteLLM 生成，不含 Anthropic 原生 msg_ ID", x["request_id"][:24])
    else:
        rep.add("FAIL", "费用日志", "90 秒内没有这次请求的记录")
    r = chat(CLOUD, key, "Reply with one word: pong", mock_testing_fallbacks=True)
    grp = r.headers.get("x-litellm-model-group", "")
    rep.add("PASS" if r.status != 200 else "FAIL", "云端别名没有降级链（不会落到本地或别处）", f"HTTP {r.status} {grp}")
    return rep.finish()


# ---------- nolog ----------
def cmd_nolog(_a) -> int:
    rep = Report("nolog", "云端请求同样不存原文")
    if not cloud_ready():
        rep.add("FAIL", "Anthropic key", "为空")
        return rep.finish()
    canary = "CANARY-" + secrets.token_hex(6)
    r = chat(CLOUD, key_of("mkt-copywriter"), f"Repeat this code exactly: {canary}", max_tokens=256)
    cid = r.headers.get("x-litellm-call-id", "")
    rep.add("PASS" if r.status == 200 else "FAIL", "发送带标记串的云端请求",
            f"标记 {canary[:10]}…，回答{'含' if canary in answer(r)[0] else '不含'}标记")
    rows = spend_rows([cid], 1)
    rep.add("PASS" if rows else "WARN", "费用日志已记录这次请求", f"{len(rows)} 行")
    code, out = psql("select coalesce(messages::text,'') || '|' || coalesce(response::text,'') || '|' || "
                     f"coalesce(proxy_server_request::text,'') from \"LiteLLM_SpendLogs\" where litellm_call_id = '{cid}'")
    rep.add("PASS" if code == 0 and canary not in out else "FAIL", "费用日志的原文字段为空", snip(out, 60))
    code, dump = run(["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "litellm", "--data-only", "litellm"], timeout=180)
    rep.add("FAIL" if code != 0 or canary in dump else "PASS", "整库导出搜不到标记串", f"导出 {len(dump) // 1024} KB")
    all_logs = base.logs("15m", None)
    rep.add("FAIL" if canary in all_logs else "PASS", "三个容器的日志搜不到标记串", f"日志 {len(all_logs) // 1024} KB")
    return rep.finish()


# ---------- reconcile ----------
def cmd_reconcile(a) -> int:
    rep = Report("reconcile", "云端对账（网关 vs Anthropic Console）")
    if a.send:
        key = key_of("mkt-copywriter")
        okn = 0
        for i in range(a.send):
            r = chat(CLOUD, key, f"Write one short sentence about mortgage term #{i + 1}.", max_tokens=512)
            okn += r.status == 200
        rep.add("PASS" if okn == a.send else "WARN", f"发送对账批次 {a.send} 次", f"成功 {okn}")
        time.sleep(30)
    sql = ("select count(*), coalesce(sum(prompt_tokens),0), coalesce(sum(completion_tokens),0), coalesce(sum(spend),0), "
           "coalesce(to_char(min(\"startTime\") at time zone 'UTC','YYYY-MM-DD HH24:MI'),''), "
           "coalesce(to_char(max(\"startTime\") at time zone 'UTC','YYYY-MM-DD HH24:MI'),'') "
           f"from \"LiteLLM_SpendLogs\" where model_group = '{CLOUD}' and coalesce(status,'success') = 'success'")
    code, out = psql(sql)
    if code != 0 or "|" not in out:
        rep.add("FAIL", "查询费用日志", snip(out, 160))
        return rep.finish()
    n, tin, tout, spend, t0, t1 = out.strip().split("|")
    n, tin, tout, spend = int(n), int(tin), int(tout), float(spend)
    want = tin * CLOUD_PRICE["in"] + tout * CLOUD_PRICE["out"]
    rep.add("INFO", "网关记录（全部云端成功调用）", f"{n} 次，输入 {tin} tok，输出 {tout} tok，UTC {t0} ~ {t1}")
    rep.add("PASS" if abs(spend - want) < 1e-9 else "FAIL", "网关费用 = token × 官方单价", f"记 ${spend:.6f}，按单价算 ${want:.6f}")
    if a.console_in is not None and a.console_out is not None:
        for label, gw, con in (("输入", tin, a.console_in), ("输出", tout, a.console_out)):
            d = gw - con
            st = "PASS" if d == 0 else ("WARN" if abs(d) <= max(50, gw * 0.01) else "FAIL")
            rep.add(st, f"{label} token：网关 = Console", f"网关 {gw}，Console {con}，差 {d}" + ("（Console 可能尚未汇总完，隔几分钟再比）" if st == "WARN" else ""))
        if a.console_usd is not None:
            rep.add("PASS" if abs(spend - a.console_usd) <= 0.01 else "FAIL", "金额：网关 ≈ Console（Console 按美分显示）",
                    f"网关 ${spend:.4f}，Console ${a.console_usd:.2f}")
    else:
        rep.add("INFO", "下一步", "Console → Usage：筛选网关专用 key 与 claude-haiku-5-5，日期覆盖上面的 UTC 区间，"
                "记下输入/输出 token，再运行 reconcile --console-in N --console-out M")
    return rep.finish("Haiku 5.5 的思考 token 计入输出；网关按响应里的 usage 计，与 Console 口径一致。")


# ---------- persist ----------
def _state() -> dict:
    st = {"teams": {}, "keys": {}}
    for alias, t in teams_by_alias().items():
        r = http("GET", f"{GW}/team/info?team_id={t['team_id']}", mk(), timeout=20)
        ti = r.json().get("team_info", t) if r.status == 200 else t
        st["teams"][alias] = {"models": sorted(ti.get("models") or []), "max_budget": ti.get("max_budget"),
                              "rpm_limit": ti.get("rpm_limit"), "spend": round(float(ti.get("spend") or 0), 10)}
    for alias, rec in load_keys().items():
        i = key_info(rec["key"])
        st["keys"][alias] = {"valid": bool(i), "max_budget": i.get("max_budget"), "rpm_limit": i.get("rpm_limit"),
                             "spend": round(float(i.get("spend") or 0), 10)}
    return st


def cmd_persist(a) -> int:
    rep = Report("persist", "重启后团队、key、预算、已用额度保留")
    if a.save:
        st = _state()
        STATE_FILE.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
        STATE_FILE.chmod(0o600)
        rep.add("PASS", "已保存重启前快照", f"{len(st['teams'])} 个团队，{len(st['keys'])} 个 key → .secrets/p3-persist.json")
        return rep.finish()
    if not STATE_FILE.exists():
        rep.add("FAIL", "重启前快照", "没有，先运行 persist --save")
        return rep.finish()
    for _ in range(36):
        if http("GET", f"{GW}/health/liveliness", timeout=5).status == 200:
            break
        time.sleep(5)
    old, new = json.loads(STATE_FILE.read_text(encoding="utf-8")), _state()
    for kind in ("teams", "keys"):
        for alias, o in old[kind].items():
            n = new[kind].get(alias)
            if not n:
                rep.add("FAIL", f"{alias}", "重启后不见了")
                continue
            diff = [f"{f}: {o.get(f)} → {n.get(f)}" for f in o if f != "spend" and o.get(f) != n.get(f)]
            sp_ok = (n.get("spend") or 0) >= (o.get("spend") or 0) - 1e-9  # 只许增加：persist 自身的验证调用会计费
            rep.add("PASS" if not diff and sp_ok else "FAIL", f"{'团队' if kind == 'teams' else 'key'} {alias}",
                    "; ".join(diff) or f"已用 ${n.get('spend'):.6f} 保留" + ("" if sp_ok else f"（重启前 ${o.get('spend'):.6f}）"))
    r = chat("chat-default", key_of("uw-loan-assistant"), "Reply with one word: pong")
    rep.add("PASS" if r.status == 200 else "FAIL", "重启后团队 key 可调用", f"{r.secs:.1f}s（含冷启动）" if r.status == 200 else r.err_msg())
    return rep.finish()


def cmd_record(a) -> int:
    base.write_section(a.section, a.title, a.text)
    return 0


def main() -> int:
    ensure_results_header()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ["secrets", "infra", "login", "org", "access", "budget", "ratelimit", "cloud", "nolog"]:
        sub.add_parser(name)
    p = sub.add_parser("admin")
    p.add_argument("--email", default=ADMIN_EMAIL)
    p = sub.add_parser("pricing")
    p.add_argument("-n", type=int, default=12, help="本地请求次数（默认 12）")
    p = sub.add_parser("reconcile")
    p.add_argument("--send", type=int, default=0, help="先发 N 次云端调用作为对账批次")
    p.add_argument("--console-in", type=int)
    p.add_argument("--console-out", type=int)
    p.add_argument("--console-usd", type=float)
    p = sub.add_parser("persist")
    p.add_argument("--save", action="store_true")
    p = sub.add_parser("record")
    p.add_argument("section")
    p.add_argument("--title", required=True)
    p.add_argument("--text", required=True)
    a = ap.parse_args()
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    sys.exit(main())
