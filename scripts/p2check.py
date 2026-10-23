#!/usr/bin/env python3
"""P2 网关核心检查工具，只用 Python 标准库。

子命令
  env       记录环境版本（Docker、Compose、三个镜像、LiteLLM/Postgres/Ollama 版本）
  infra     镜像锁定、容器健康、端口、.env、数据库连接、插件已加载、管理界面可访问
  bypass    反向测试：绕过网关直连模型和数据库应当失败
  key       创建或核对 P2 测试用虚拟 key（存 .secrets/p2-test.key，不提交）
  route     经网关调用别名、流式、qwen3 思考参数复测
  sdk       在 LiteLLM 锁定镜像里用 OpenAI 官方 SDK 测试（只改 base_url）
  fallback  降级测试（mock_testing_fallbacks）
  plugin    占位插件日志：在路由之前、与请求 ID 对得上、受控参数被丢弃
  nolog     日志不存原文：带标记串请求后，数据库与容器日志里都搜不到
  cloud     GitHub Models 云端别名 chat-github
  persist   重启后恢复：容器健康、key 仍有效、可调用；--boot 额外核对 WSL 开机后自动拉起
  secrets   密钥扫描：.env 与 .secrets 从未进入 git 历史，历史中没有密钥值或常见令牌格式
  record    把一段文本写进 docs/p2-results.md 的指定小节（供 shell 脚本调用）

每个子命令把结果写进 docs/p2-results.md 对应小节（重复运行覆盖该小节）。有 FAIL 时退出码为 1。
任何输出里密钥只显示前 6 位。环境变量 GATEWAY_URL 可改网关地址，默认 http://127.0.0.1:4000。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GW = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000").rstrip("/")
ENV_FILE = ROOT / ".env"
KEY_FILE = ROOT / ".secrets" / "p2-test.key"
RESULTS = ROOT / "docs" / "p2-results.md"
COMPOSE = ROOT / "docker-compose.yml"
SDK_SCRIPT = ROOT / "scripts" / "sdk_check.py"
ALIASES_LOCAL = ["chat-default", "chat-fallback"]
ALIAS_CLOUD = "chat-github"
GH_MODEL = "openai/gpt-4.1-mini"
SERVICES = ["ollama", "postgres", "litellm"]
IMAGE_REPOS = {"ollama": "ollama/ollama", "postgres": "postgres", "litellm": "ghcr.io/berriai/litellm"}


# ---------- 报告 ----------
class Report:
    def __init__(self, section: str, title: str):
        self.section, self.title, self.rows = section, title, []

    def add(self, status: str, item: str, detail: str = "") -> None:
        self.rows.append((status, item, detail))
        color = {"PASS": "32", "WARN": "33", "FAIL": "31", "INFO": "36"}.get(status, "0")
        print(f"\033[{color}m{status:4}\033[0m {item}" + (f" — {detail}" if detail else ""), flush=True)

    def count(self, s: str) -> int:
        return sum(1 for r in self.rows if r[0] == s)

    def finish(self, extra: str = "") -> int:
        summary = f"PASS {self.count('PASS')} / WARN {self.count('WARN')} / FAIL {self.count('FAIL')}"
        print(f"\n汇总：{summary}")
        lines = [f"_{datetime.now():%Y-%m-%d %H:%M}，{summary}_", "", "| 结果 | 检查项 | 说明 |", "| --- | --- | --- |"]
        for s, i, d in self.rows:
            lines.append(f"| {s} | {i} | {d.replace('|', '/').replace(chr(10), ' ')} |")
        if extra:
            lines += ["", extra]
        write_section(self.section, self.title, "\n".join(lines))
        return 1 if self.count("FAIL") else 0


def write_section(name: str, title: str, body: str) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    text = RESULTS.read_text(encoding="utf-8") if RESULTS.exists() else "# P2 实测结果\n\n由 scripts/p2check.py 自动写入，各小节重跑时覆盖。\n"
    block = f"<!-- BEGIN {name} -->\n## {title}\n\n{body}\n<!-- END {name} -->"
    pat = re.compile(rf"<!-- BEGIN {re.escape(name)} -->.*?<!-- END {re.escape(name)} -->", re.S)
    text = pat.sub(lambda _: block, text) if pat.search(text) else text.rstrip() + "\n\n" + block + "\n"
    RESULTS.write_text(text, encoding="utf-8")


# ---------- 工具 ----------
def mask(v: str | None) -> str:
    return (v[:6] + "…") if v else "（空）"


def read_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def master_key() -> str:
    return os.environ.get("P2CHECK_MASTER_KEY") or read_env().get("LITELLM_MASTER_KEY", "")


def test_key() -> str:
    if os.environ.get("P2CHECK_TEST_KEY"):
        return os.environ["P2CHECK_TEST_KEY"]
    return KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""


def run(cmd: list[str], timeout: float = 60, input_text: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, input=input_text)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, f"找不到命令 {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "超时"


class Resp:
    def __init__(self, status: int, headers: dict, body: bytes, secs: float, error: str = ""):
        self.status, self.headers, self.body, self.secs, self.error = status, headers, body, secs, error

    def json(self):
        try:
            return json.loads(self.body or b"{}")
        except ValueError:
            return {}

    def err_msg(self) -> str:
        if self.error:
            return self.error
        j = self.json()
        m = j.get("error", {}).get("message") if isinstance(j.get("error"), dict) else j.get("detail") or j.get("error")
        return str(m or self.body[:200].decode("utf-8", "replace"))[:240]


def http(method: str, url: str, key: str | None = None, body=None, timeout: float = 150, form: bool = False) -> Resp:
    headers = {}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(), time.time() - t0)
    except urllib.error.HTTPError as e:
        return Resp(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(), time.time() - t0)
    except Exception as e:  # noqa: BLE001  连接失败、超时等
        return Resp(0, {}, b"", time.time() - t0, f"{type(e).__name__}: {e}")


def chat(alias: str, key: str, content: str = "Reply with one word: pong", **extra) -> Resp:
    body = {"model": alias, "messages": [{"role": "user", "content": content}], "max_tokens": 64, "temperature": 0}
    body.update(extra)
    return http("POST", f"{GW}/v1/chat/completions", key, body)


def answer(r: Resp) -> tuple[str, str, int]:
    j = r.json()
    try:
        msg = j["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return "", "", 0
    return (msg.get("content") or "").strip(), (msg.get("reasoning_content") or "").strip(), (j.get("usage") or {}).get("completion_tokens", 0)


def snip(s: str, n: int = 40) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def container_id(svc: str) -> str:
    _, out = run(["docker", "compose", "ps", "-q", svc])
    return out.splitlines()[0].strip() if out else ""


def inspect(cid: str, fmt: str) -> str:
    _, out = run(["docker", "inspect", "--format", fmt, cid])
    return out.strip()


def compose_images() -> dict:
    text = COMPOSE.read_text(encoding="utf-8") if COMPOSE.exists() else ""
    found = {}
    for svc, repo in IMAGE_REPOS.items():
        m = re.search(rf"^\s*image:\s*({re.escape(repo)}[:@]\S+)", text, re.M)
        found[svc] = m.group(1) if m else ""
    return found


def logs(since: str = "5m", service: str | None = "litellm") -> str:
    if os.environ.get("P2CHECK_LOG_FILE"):
        return Path(os.environ["P2CHECK_LOG_FILE"]).read_text(encoding="utf-8", errors="replace")
    cmd = ["docker", "compose", "logs", "--no-color", "--since", since]
    if service:
        cmd.append(service)
    _, out = run(cmd, timeout=60)
    return out


def tcp_open(host: str, port: int, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def psql(sql: str) -> tuple[int, str]:
    return run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "litellm", "-d", "litellm", "-tA", "-c", sql])


def need_key(rep: Report) -> str:
    k = test_key()
    if not k:
        rep.add("FAIL", "测试 key", "没有 .secrets/p2-test.key，先运行 python3 scripts/p2check.py key")
    return k


# ---------- 子命令 ----------
def cmd_env(_a) -> int:
    rep = Report("env", "环境版本")
    for label, cmd in [("Docker", ["docker", "version", "--format", "{{.Server.Version}}"]),
                       ("Compose", ["docker", "compose", "version", "--short"])]:
        code, out = run(cmd)
        rep.add("INFO" if code == 0 else "FAIL", label, out.splitlines()[0] if out else "")
    for svc, img in compose_images().items():
        rep.add("INFO", f"镜像 {svc}", img or "compose 中未找到")
    r = http("GET", f"{GW}/health/readiness/details", master_key(), timeout=15)
    rep.add("INFO" if r.status == 200 else "WARN", "LiteLLM 版本", r.json().get("litellm_version", r.err_msg()))
    code, out = run(["docker", "compose", "exec", "-T", "postgres", "postgres", "--version"])
    rep.add("INFO" if code == 0 else "WARN", "Postgres 版本", out.splitlines()[-1] if out else "")
    code, out = run(["docker", "compose", "exec", "-T", "ollama", "ollama", "--version"])
    rep.add("INFO" if code == 0 else "WARN", "Ollama 版本", out.splitlines()[-1] if out else "")
    return rep.finish()


def cmd_infra(_a) -> int:
    rep = Report("infra", "基础设施")
    env = read_env()
    # .env
    if not ENV_FILE.exists():
        rep.add("FAIL", ".env", "不存在，先运行 bash scripts/gen-env.sh")
    else:
        mode = oct(ENV_FILE.stat().st_mode & 0o777)
        rep.add("PASS" if mode == "0o600" else "WARN", ".env 权限", mode)
        code, _ = run(["git", "ls-files", "--error-unmatch", ".env"])
        rep.add("FAIL" if code == 0 else "PASS", ".env 未纳入 git", "已被跟踪！" if code == 0 else "")
        for k in ["LITELLM_MASTER_KEY", "LITELLM_SALT_KEY", "POSTGRES_PASSWORD"]:
            rep.add("PASS" if env.get(k) else "FAIL", f".env 含 {k}", mask(env.get(k)))
        mk = env.get("LITELLM_MASTER_KEY", "")
        rep.add("PASS" if mk.startswith("sk-") else "FAIL", "Master Key 以 sk- 开头", "")
    # 镜像
    for svc, img in compose_images().items():
        ok = bool(re.search(r":[^@\s]+@sha256:[0-9a-f]{64}$", img)) and "UNPINNED" not in img and ":latest" not in img
        rep.add("PASS" if ok else "FAIL", f"{svc} 镜像已锁定", img or "未找到", )
    # 容器
    for svc in SERVICES:
        cid = container_id(svc)
        if not cid:
            rep.add("FAIL", f"{svc} 容器", "未运行，执行 docker compose up -d")
            continue
        health = inspect(cid, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
        rep.add("PASS" if health == "healthy" else "FAIL", f"{svc} 健康", health)
        policy = inspect(cid, "{{.HostConfig.RestartPolicy.Name}}")
        rep.add("PASS" if policy == "unless-stopped" else "FAIL", f"{svc} 重启策略", policy)
        image = inspect(cid, "{{.Config.Image}}")
        want = compose_images().get(svc, "")
        rep.add("PASS" if image == want else "FAIL", f"{svc} 运行的是锁定镜像", snip(image, 70))
        ports = json.loads(inspect(cid, "{{json .NetworkSettings.Ports}}") or "{}") or {}
        bound = [f"{b.get('HostIp')}:{b.get('HostPort')}" for v in ports.values() if v for b in v]
        if svc == "litellm":
            ok = bound and all(b.startswith("127.0.0.1:") for b in bound) and "127.0.0.1:4000" in bound
            rep.add("PASS" if ok else "FAIL", "litellm 端口只绑定 127.0.0.1:4000", ", ".join(bound) or "无")
        else:
            rep.add("PASS" if not bound else "FAIL", f"{svc} 不对宿主机开放端口", ", ".join(bound) or "无映射")
    # 网关
    r = http("GET", f"{GW}/health/liveliness", timeout=10)
    rep.add("PASS" if r.status == 200 else "FAIL", "网关存活", str(r.status) if r.status else r.error)
    r = http("GET", f"{GW}/health/readiness/details", master_key(), timeout=15)
    j = r.json()
    rep.add("PASS" if j.get("db") == "connected" else "FAIL", "网关已连上 Postgres", str(j.get("db", r.err_msg())))
    cbs = j.get("success_callbacks", []) + j.get("failure_callbacks", []) + j.get("callbacks", [])
    rep.add("PASS" if "GovernancePlugin" in cbs else "FAIL", "治理插件已加载", "GovernancePlugin" if "GovernancePlugin" in cbs else f"回调列表：{cbs}")
    r = http("GET", f"{GW}/v1/models", None, timeout=10)
    rep.add("PASS" if r.status in (401, 403) else "FAIL", "不带 key 调用被拒", str(r.status or r.error))
    r = http("GET", f"{GW}/ui/", None, timeout=15)
    rep.add("PASS" if r.status == 200 else "WARN", "管理界面页面可访问", f"{GW}/ui/ → {r.status or r.error}")
    return rep.finish()


PROBE = r"""
import json, socket, sys
out = {}
for spec in sys.argv[1:]:
    host, port = spec.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=3).close(); out[spec] = "open"
    except OSError as e:
        out[spec] = type(e).__name__
print(json.dumps(out))
"""


def cmd_bypass(_a) -> int:
    rep = Report("bypass", "反向测试：绕过网关")
    # 第一层：宿主机经 127.0.0.1 访问
    for name, port in [("Ollama", 11434), ("Postgres", 5432)]:
        is_open = tcp_open("127.0.0.1", port)
        rep.add("FAIL" if is_open else "PASS", f"宿主机 127.0.0.1:{port}（{name}）连不上", "竟然连上了" if is_open else "拒绝连接")
    r = http("GET", "http://127.0.0.1:11434/api/tags", timeout=5)
    rep.add("FAIL" if r.status == 200 else "PASS", "宿主机调用 Ollama /api/tags 失败", r.error or str(r.status))
    # 第二层：另一个 Docker 网络里的容器（模拟绕过网关的应用）
    ips = {svc: inspect(container_id(svc), "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}").split()
           for svc in ["ollama", "postgres"] if container_id(svc)}
    ollama_ip = (ips.get("ollama") or [""])[0]
    pg_ip = (ips.get("postgres") or [""])[0]
    image = compose_images().get("litellm", "")
    targets = ["ollama:11434", "postgres:5432"] + ([f"{ollama_ip}:11434"] if ollama_ip else []) + ([f"{pg_ip}:5432"] if pg_ip else [])
    code, out = run(["docker", "run", "--rm", "--network", "bridge", "--entrypoint", "python3", image, "-c", PROBE, *targets], timeout=120)
    try:
        res = json.loads(out.strip().splitlines()[-1])
        for t in targets:
            rep.add("FAIL" if res.get(t) == "open" else "PASS", f"另一网络的容器连 {t}", res.get(t, "?"))
    except (ValueError, IndexError):
        rep.add("FAIL", "另一网络的容器测试", f"无法运行探测容器：{snip(out, 160)}")
    # 第三层：宿主机直连容器网桥 IP（Linux 默认可达，属 Docker 主机信任边界）
    if ollama_ip:
        is_open = tcp_open(ollama_ip, 11434)
        rep.add("WARN" if is_open else "PASS", f"宿主机直连 Ollama 容器 IP {ollama_ip}:11434",
                "可达：Linux 上宿主机能路由到网桥 IP；能在宿主机上执行命令的人本就等同 docker 组/root，记为已知边界" if is_open else "不可达")
    # 网关本身
    k = test_key()
    if k:
        r = http("GET", f"{GW}/v1/models", k, timeout=15)
        rep.add("PASS" if r.status == 200 else "FAIL", "经网关带 key 可访问", str(r.status or r.error))
    return rep.finish("宿主机直连容器 IP 的 WARN 是预期结果，处理方式见总纲第 12 节“更严格的网络隔离”。")


def cmd_key(_a) -> int:
    rep = Report("key", "测试用虚拟 key")
    mk = master_key()
    if not mk:
        rep.add("FAIL", "Master Key", "读不到 .env 中的 LITELLM_MASTER_KEY")
        return rep.finish()
    k = test_key()
    if k:
        r = http("GET", f"{GW}/key/info?key={urllib.parse.quote(k)}", mk, timeout=20)
        if r.status == 200:
            info = r.json().get("info", {})
            rep.add("PASS", "已有测试 key 有效", f"{mask(k)} 别名 {info.get('key_alias')}，模型 {info.get('models')}")
            return rep.finish()
        rep.add("FAIL", "已有测试 key 无效", f"{r.status} {r.err_msg()}；如确认作废，删除 .secrets/p2-test.key 后重跑")
        return rep.finish()
    body = {"key_alias": "p2-test", "models": ALIASES_LOCAL + [ALIAS_CLOUD], "metadata": {"purpose": "P2 test key"}}
    r = http("POST", f"{GW}/key/generate", mk, body, timeout=30)
    newk = r.json().get("key", "")
    if r.status != 200 or not newk:
        rep.add("FAIL", "创建测试 key", f"{r.status} {r.err_msg()}")
        return rep.finish()
    KEY_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    KEY_FILE.write_text(newk + "\n", encoding="utf-8")
    KEY_FILE.chmod(0o600)
    rep.add("PASS", "已创建测试 key", f"{mask(newk)}，别名 p2-test，存于 .secrets/p2-test.key（不提交）")
    return rep.finish()


def cmd_route(_a) -> int:
    rep = Report("route", "经网关调用")
    k = need_key(rep)
    if not k:
        return rep.finish()
    r = http("GET", f"{GW}/v1/models", k, timeout=15)
    ids = [m.get("id") for m in r.json().get("data", [])]
    for a in ALIASES_LOCAL + [ALIAS_CLOUD]:
        rep.add("PASS" if a in ids else "FAIL", f"/v1/models 列出 {a}", "")
    leaked = [i for i in ids if i and ("/" in i or ":" in i)]
    rep.add("PASS" if not leaked else "WARN", "只暴露逻辑名，不暴露后端模型名", ", ".join(leaked) or "")
    for a in ALIASES_LOCAL:
        r = chat(a, k)
        ans, think, n = answer(r)
        group = r.headers.get("x-litellm-model-group", "?")
        if r.status == 200 and ans:
            rep.add("PASS", f"{a} 调用", f"{r.secs:.1f}s，{n} tok，后端 {r.headers.get('x-litellm-model-name', '?')}，组 {group}，回答：{snip(ans)}")
        else:
            rep.add("FAIL", f"{a} 调用", f"{r.status} {r.err_msg()}")
    # qwen3 思考：应用不传参数 / 应用传 high，网关都应关闭思考
    for label, extra in [("应用不传参数", {}), ("应用传 reasoning_effort=high", {"reasoning_effort": "high"})]:
        r = chat("chat-default", k, "What is 17 + 25? Answer with the number only.", max_tokens=1024, **extra)
        ans, think, n = answer(r)
        if r.status != 200:
            rep.add("FAIL", f"chat-default 思考关闭（{label}）", f"{r.status} {r.err_msg()}")
        elif think or n > 100:
            rep.add("FAIL", f"chat-default 思考关闭（{label}）", f"{r.secs:.1f}s，{n} tok，仍有思考内容")
        else:
            rep.add("PASS", f"chat-default 思考关闭（{label}）", f"{r.secs:.1f}s，{n} tok，回答：{snip(ans)}")
    # 流式
    req = urllib.request.Request(f"{GW}/v1/chat/completions", method="POST",
                                 data=json.dumps({"model": "chat-default", "stream": True, "max_tokens": 64,
                                                  "messages": [{"role": "user", "content": "Count from 1 to 5."}]}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"})
    chunks, done, t0 = 0, False, time.time()
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line == "data: [DONE]":
                    done = True
                elif line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        if d.get("choices") and (d["choices"][0].get("delta") or {}).get("content"):
                            chunks += 1
                    except ValueError:
                        pass
        rep.add("PASS" if chunks >= 2 and done else "FAIL", "chat-default 流式", f"{chunks} 个正文块，{'以 [DONE] 结尾' if done else '没有 [DONE]'}，{time.time() - t0:.1f}s")
    except Exception as e:  # noqa: BLE001
        rep.add("FAIL", "chat-default 流式", f"{type(e).__name__}: {e}")
    return rep.finish()


def cmd_sdk(_a) -> int:
    rep = Report("sdk", "OpenAI 官方 SDK（只改 base_url）")
    k = need_key(rep)
    image = compose_images().get("litellm", "")
    if not k or not image:
        return rep.finish()
    env = dict(os.environ, GW_KEY=k, GW_URL=f"{GW}/v1")
    cmd = ["docker", "run", "--rm", "--network", "host", "-e", "GW_KEY", "-e", "GW_URL",
           "-v", f"{SDK_SCRIPT}:/sdk_check.py:ro", "--entrypoint", "python3", image, "/sdk_check.py"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300, env=env)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        out = "超时"
    got = False
    for line in out.splitlines():
        if line.startswith("{"):
            try:
                d = json.loads(line)
                rep.add(d["status"], d["item"], d.get("detail", ""))
                got = True
            except (ValueError, KeyError):
                pass
    if not got:
        rep.add("FAIL", "运行 sdk_check.py", snip(out, 240))
    return rep.finish()


def cmd_fallback(_a) -> int:
    rep = Report("fallback", "降级测试")
    k = need_key(rep)
    if not k:
        return rep.finish()
    r = chat("chat-default", k)
    rep.add("PASS" if r.status == 200 and r.headers.get("x-litellm-attempted-fallbacks", "0") == "0" else "FAIL",
            "正常请求不降级", f"组 {r.headers.get('x-litellm-model-group', '?')}，降级次数 {r.headers.get('x-litellm-attempted-fallbacks', '?')}")
    r = chat("chat-default", k, mock_testing_fallbacks=True)
    ans, _, n = answer(r)
    group = r.headers.get("x-litellm-model-group", "?")
    tries = r.headers.get("x-litellm-attempted-fallbacks", "?")
    if r.status == 200 and group == "chat-fallback" and tries not in ("0", "?"):
        rep.add("PASS", "chat-default 故障 → chat-fallback", f"{r.secs:.1f}s，降级次数 {tries}，后端 {r.headers.get('x-litellm-model-name', '?')}，回答：{snip(ans)}")
    elif r.status == 400 and "disabled" in r.err_msg():
        rep.add("FAIL", "chat-default 故障 → chat-fallback", "测试参数被禁用：config.yaml 缺 dangerously_allow_mock_testing_request_params: true")
    else:
        rep.add("FAIL", "chat-default 故障 → chat-fallback", f"{r.status} 组 {group} 降级次数 {tries} {r.err_msg() if r.status != 200 else ''}")
    r = chat("chat-github", k, mock_testing_fallbacks=True) if read_env().get("GITHUB_MODELS_TOKEN") else None
    if r is not None:
        rep.add("PASS" if r.status != 200 else "FAIL", "云端别名没有降级链（不会从云端落到别处，也不会从本地落到云端）",
                f"{r.status}，{snip(r.err_msg(), 80)}" if r.status != 200 else "竟然成功了，检查 router_settings.fallbacks")
    return rep.finish()


def cmd_plugin(_a) -> int:
    rep = Report("plugin", "治理插件占位")
    k = need_key(rep)
    if not k:
        return rep.finish()
    r1 = chat("chat-default", k)
    r2 = chat("chat-default", k, reasoning_effort="high")
    r3 = chat("chat-default", k, mock_testing_fallbacks=True)
    time.sleep(2)
    text = logs("10m")
    lines = [l for l in text.splitlines() if "policy_check:" in l]
    for label, r, want_drop in [("普通请求", r1, False), ("应用传 reasoning_effort=high", r2, True), ("降级请求", r3, False)]:
        cid = r.headers.get("x-litellm-call-id", "")
        hit = [l for l in lines if f"call_id={cid}" in l] if cid else []
        if not cid:
            rep.add("FAIL", f"{label}：响应头有 x-litellm-call-id", f"{r.status} {r.err_msg()}")
            continue
        if len(hit) != 1:
            rep.add("FAIL", f"{label}：插件日志恰好 1 行", f"找到 {len(hit)} 行（call_id {cid[:8]}…）")
            continue
        line = hit[0]
        ok = "policy_check: pass" in line and "model=chat-default" in line
        rep.add("PASS" if ok else "FAIL", f"{label}：插件在路由前记录逻辑名", snip(line[line.find('policy_check'):], 110))
        if want_drop:
            rep.add("PASS" if "dropped_params=reasoning_effort" in line else "FAIL", f"{label}：受控参数被丢弃", "")
    if r3.headers.get("x-litellm-model-group") == "chat-fallback":
        rep.add("PASS", "降级请求只经过插件一次", "钩子在路由之前，降级发生在钩子之后")
    rep.add("PASS" if "key_alias=p2-test" in "\n".join(lines) else "WARN", "插件日志带 key 别名", "")
    return rep.finish()


def cmd_nolog(_a) -> int:
    rep = Report("nolog", "日志不存原文")
    k = need_key(rep)
    if not k:
        return rep.finish()
    canary = "CANARY-" + secrets.token_hex(6)
    r = chat("chat-fallback", k, f"Repeat this code exactly: {canary}")
    cid = r.headers.get("x-litellm-call-id", "")
    rep.add("PASS" if r.status == 200 else "FAIL", "发送带标记串的请求", f"标记 {canary[:10]}…，call_id {cid[:8]}…，回答{'含' if canary in answer(r)[0] else '不含'}标记")
    row = ""
    for _ in range(18):  # 费用日志批量写入，最多等 90 秒
        code, row = psql(f"select count(*) from \"LiteLLM_SpendLogs\" where request_id = '{cid}'")
        if code == 0 and row.strip() not in ("", "0"):
            break
        time.sleep(5)
    rep.add("PASS" if row.strip() not in ("", "0") else "WARN", "费用日志已记录这次请求（证明日志在工作）", f"行数 {row.strip() or '?'}")
    code, out = psql(f"select coalesce(messages::text,'') || '|' || coalesce(response::text,'') || '|' || coalesce(proxy_server_request::text,'') from \"LiteLLM_SpendLogs\" where request_id = '{cid}'")
    if code == 0 and out:
        rep.add("PASS" if canary not in out else "FAIL", "费用日志的 messages/response/请求体字段不含原文", snip(out, 80))
    code, dump = run(["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "litellm", "--data-only", "litellm"], timeout=180)
    if code == 0:
        rep.add("FAIL" if canary in dump else "PASS", "整库导出搜不到标记串", f"导出 {len(dump) // 1024} KB")
    else:
        rep.add("FAIL", "整库导出", snip(dump, 160))
    all_logs = logs("15m", None)
    rep.add("FAIL" if canary in all_logs else "PASS", "三个容器的日志搜不到标记串", f"日志 {len(all_logs) // 1024} KB")
    return rep.finish()


def cmd_cloud(a) -> int:
    rep = Report("cloud", "GitHub Models 云端别名")
    tok = read_env().get("GITHUB_MODELS_TOKEN", "")
    if not tok:
        rep.add("WARN", "GITHUB_MODELS_TOKEN", ".env 里为空，跳过（步骤 8 是可选的）")
        return rep.finish()
    rep.add("PASS" if tok.startswith("github_pat_") else "WARN", "令牌是细粒度 PAT", mask(tok) + ("" if tok.startswith("github_pat_") else "：不是 github_pat_ 开头，经典令牌权限过宽"))
    r = http("GET", "https://models.github.ai/catalog/models", tok, timeout=30)
    if r.status == 200:
        cat = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
        ids = {m.get("id") for m in cat if isinstance(m, dict)}
        info = next((m for m in cat if isinstance(m, dict) and m.get("id") == GH_MODEL), {})
        rep.add("PASS" if GH_MODEL in ids else "FAIL", f"目录中有 {GH_MODEL}", f"限额档 {info.get('rate_limit_tier', '?')}，目录共 {len(ids)} 个模型")
    else:
        rep.add("FAIL", "读取 GitHub Models 目录", f"{r.status} {r.err_msg()}")
    k = need_key(rep)
    if k:
        r = chat(ALIAS_CLOUD, k)
        ans, _, n = answer(r)
        rep.add("PASS" if r.status == 200 and ans else "FAIL", f"经网关调用 {ALIAS_CLOUD}",
                f"{r.secs:.1f}s，{n} tok，后端 {r.headers.get('x-litellm-model-name', '?')}，回答：{snip(ans)}" if r.status == 200 else f"{r.status} {r.err_msg()}")
        cost = r.headers.get("x-litellm-response-cost", "?")
        rep.add("INFO", "网关记的费用", f"{cost}（GitHub Models 免费额度不出账单，P3 再定内部结算价）")
    text = logs("15m", None)
    rep.add("FAIL" if tok in text else "PASS", "容器日志里没有令牌原文", "")
    return rep.finish()


def cmd_persist(a) -> int:
    rep = Report("persist", "重启后恢复")
    boot = 0.0
    if a.boot:
        try:
            boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError):
            pass
    for svc in SERVICES:
        cid = container_id(svc)
        if not cid:
            rep.add("FAIL", f"{svc} 容器", "不存在")
            continue
        health = ""
        for _ in range(36):  # LiteLLM 冷启动要做数据库迁移，最多等 3 分钟
            health = inspect(cid, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
            if health == "healthy":
                break
            time.sleep(5)
        rep.add("PASS" if health == "healthy" else "FAIL", f"{svc} 健康", health)
        if a.boot:
            started = inspect(cid, "{{.State.StartedAt}}")
            try:
                st = datetime.fromisoformat(started[:26].rstrip("Z") + "+00:00").timestamp()
                rep.add("PASS" if st >= boot - 5 else "FAIL", f"{svc} 在本次开机后自动拉起", f"开机后 {st - boot:.0f}s 启动")
            except ValueError:
                rep.add("WARN", f"{svc} 启动时间", started)
    k = test_key()
    if not k:
        rep.add("FAIL", "测试 key", "没有 .secrets/p2-test.key")
        return rep.finish()
    r = http("GET", f"{GW}/key/info?key={urllib.parse.quote(k)}", master_key(), timeout=20)
    info = r.json().get("info", {})
    rep.add("PASS" if r.status == 200 else "FAIL", "测试 key 仍有效", f"已用额度 {info.get('spend')}" if r.status == 200 else f"{r.status} {r.err_msg()}")
    r = chat("chat-default", k)
    ans, _, n = answer(r)
    rep.add("PASS" if r.status == 200 and ans else "FAIL", "重启后 chat-default 可调用", f"{r.secs:.1f}s（含冷启动），回答：{snip(ans)}" if r.status == 200 else r.err_msg())
    return rep.finish()


TOKEN_PATTERNS = [
    (r"github_pat_[A-Za-z0-9_]{30,}", "GitHub 细粒度令牌"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub 令牌"),
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic key"),
    (r"sk-[A-Za-z0-9]{32,}", "sk- 形式的密钥"),
]


def cmd_secrets(_a) -> int:
    rep = Report("secrets", "密钥扫描")
    code, names = run(["git", "log", "--all", "--name-only", "--pretty=format:"], timeout=120)
    files = {n.strip() for n in names.splitlines() if n.strip()}
    bad = sorted(f for f in files if f == ".env" or f.startswith(".secrets/") or f.endswith(".key"))
    rep.add("FAIL" if bad else "PASS", "历史中从未提交 .env、.secrets/、*.key", ", ".join(bad))
    code, hist = run(["git", "log", "--all", "-p", "--no-color", "--no-ext-diff"], timeout=300)
    if code != 0:
        rep.add("FAIL", "读取 git 历史", snip(hist, 160))
        return rep.finish()
    env = read_env()
    vals = {k: v for k, v in env.items() if len(v) >= 12 and any(t in k for t in ("KEY", "TOKEN", "PASSWORD", "SECRET"))}
    k = test_key()
    if k:
        vals["测试 key"] = k
    for name, v in vals.items():
        rep.add("FAIL" if v in hist else "PASS", f"历史中没有 {name} 的值", "")
    allow = {"sk-1234", "sk-xxxx"}
    for pat, label in TOKEN_PATTERNS:
        hits = sorted({m for m in re.findall(pat, hist) if not any(m.startswith(a) for a in allow)})
        rep.add("FAIL" if hits else "PASS", f"历史中没有{label}格式的字符串", ", ".join(mask(h) for h in hits[:5]))
    code, out = run(["git", "check-ignore", ".env", ".secrets/p2-test.key"])
    rep.add("PASS" if out.count("\n") >= 1 else "FAIL", ".gitignore 覆盖 .env 与 .secrets/", out.replace("\n", ", "))
    return rep.finish("扫描范围：所有分支的完整历史与 .env 中的每一个密钥值。转公开后 GitHub 还会自动做 secret scanning。")


def cmd_record(a) -> int:
    write_section(a.section, a.title, a.text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ["env", "infra", "bypass", "key", "route", "sdk", "fallback", "plugin", "nolog", "cloud", "secrets"]:
        sub.add_parser(name)
    p = sub.add_parser("persist")
    p.add_argument("--boot", action="store_true", help="WSL 重启后运行：核对容器在本次开机后自动拉起")
    p = sub.add_parser("record")
    p.add_argument("section")
    p.add_argument("--title", required=True)
    p.add_argument("--text", required=True)
    a = ap.parse_args()
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    sys.exit(main())
