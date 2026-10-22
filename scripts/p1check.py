#!/usr/bin/env python3
"""P1 模型层检查工具，只用 Python 标准库。

子命令
  env      记录环境版本（Docker、Compose、Ollama、镜像）
  lock     核对 models/models.txt 中的模型已拉取，写 models/lock.json
  smoke    冒烟测试；--infra 只查容器、端口、镜像（模型未拉取前用）
  think    qwen3 思考模式实测矩阵，并给出决定建议
  warmup   预热对话模型（--guard 连同 guard 模型）
  persist  WSL 重启后的恢复检查
  bench    性能基线（tokens/秒），--power 注明电源模式
  record   把一段文本写进 docs/p1-results.md 的指定小节（供 shell 脚本调用）

每个子命令把结果写进 docs/p1-results.md 对应小节（重复运行会覆盖该小节）。
有 FAIL 时退出码为 1。环境变量 OLLAMA_URL 可改目标地址，默认 http://127.0.0.1:11434。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODELS_TXT = ROOT / "models" / "models.txt"
LOCK = ROOT / "models" / "lock.json"
RESULTS = ROOT / "docs" / "p1-results.md"
COMPOSE = ROOT / "docker-compose.yml"
BENCH_CSV = ROOT / "bench" / "p1-baseline.csv"
SERVICE = "ollama"
TIMEOUT = float(os.environ.get("P1_TIMEOUT", "300"))

SECTION_ORDER = ["env", "pin", "models", "smoke", "think", "warmup", "persist", "bench"]
RESULTS_HEADER = (
    "# P1 实测结果\n\n"
    "由 `scripts/p1check.py` 与 `scripts/*.sh` 自动生成，每个小节可重复运行覆盖。\n"
    "实施结束后把整份文件贴回规划对话，用于把实际情况回写进 P1 文档。\n"
)

# ---------------------------------------------------------------- 输出与结果文件

_COLOR = sys.stdout.isatty()
_COLORS = {"PASS": "32", "FAIL": "31", "WARN": "33", "INFO": "36"}


def _paint(status: str) -> str:
    if not _COLOR:
        return f"{status:<4}"
    return f"\033[{_COLORS.get(status, '0')}m{status:<4}\033[0m"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        print(f"{_paint(status)} {name}" + (f" — {detail}" if detail else ""), flush=True)

    def count(self, status: str) -> int:
        return sum(1 for s, _, _ in self.rows if s == status)

    @property
    def failed(self) -> bool:
        return self.count("FAIL") > 0

    def summary(self) -> str:
        return " / ".join(f"{s} {self.count(s)}" for s in ("PASS", "FAIL", "WARN", "INFO") if self.count(s))

    def markdown(self) -> str:
        lines = [f"**汇总**：{self.summary()}", "", "| 结果 | 检查项 | 说明 |", "| --- | --- | --- |"]
        for s, n, d in self.rows:
            lines.append(f"| {s} | {md(n)} | {md(d)} |")
        return "\n".join(lines)


def md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_section(name: str, title: str, body: str) -> None:
    """按小节名替换或插入 docs/p1-results.md 中的内容，小节按固定顺序排列。"""
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    text = RESULTS.read_text(encoding="utf-8") if RESULTS.exists() else RESULTS_HEADER
    pattern = re.compile(r"<!-- BEGIN (\S+) -->\n(.*?)\n<!-- END \1 -->", re.S)
    sections = {m.group(1): m.group(2) for m in pattern.finditer(text)}
    header = pattern.split(text)[0].rstrip() if sections else text.rstrip()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections[name] = f"## {title}\n\n_更新于 {stamp}_\n\n{body.rstrip()}"
    order = SECTION_ORDER + sorted(k for k in sections if k not in SECTION_ORDER)
    blocks = [f"<!-- BEGIN {k} -->\n{sections[k]}\n<!-- END {k} -->" for k in order if k in sections]
    RESULTS.write_text(header + "\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"\n结果已写入 {RESULTS.relative_to(ROOT)}（小节：{name}）")


# ---------------------------------------------------------------- HTTP

class Resp(NamedTuple):
    status: int        # 0 = 连接失败
    json: Any
    text: str
    secs: float


def http(method: str, path: str, body: Any = None, timeout: float = TIMEOUT) -> Resp:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return Resp(0, None, f"{type(e).__name__}: {e}", time.monotonic() - t0)
    secs = time.monotonic() - t0
    text = raw.decode("utf-8", "replace")
    try:
        js = json.loads(text)
    except ValueError:
        js = None
    return Resp(status, js, text, secs)


def err_detail(r: Resp) -> str:
    if r.status == 0:
        return f"连接失败：{r.text}"
    msg = r.json.get("error") if isinstance(r.json, dict) else None
    if isinstance(msg, dict):
        msg = msg.get("message")
    return f"HTTP {r.status}：{msg or r.text[:200]}"


THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text or "").strip()


def snippet(text: str, n: int = 40) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- Docker

def sh(*args: str) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=120)
    except FileNotFoundError:
        return 127, "", f"找不到命令 {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def container_id() -> str:
    rc, out, _ = sh("docker", "compose", "ps", "-q", SERVICE)
    return out.splitlines()[0] if rc == 0 and out else ""


def inspect(cid: str, fmt: str) -> str:
    rc, out, _ = sh("docker", "inspect", "-f", fmt, cid)
    return out if rc == 0 else ""


def compose_image() -> str:
    if not COMPOSE.exists():
        return ""
    m = re.search(r"^\s*image:\s*(ollama/ollama\S*)", COMPOSE.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def image_version(image: str) -> str:
    m = re.match(r"ollama/ollama:([^@\s]+)", image)
    return m.group(1) if m else ""


def wait_health(cid: str, limit: float = 90) -> str:
    t0 = time.monotonic()
    while True:
        h = inspect(cid, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
        if h != "starting" or time.monotonic() - t0 > limit:
            return h
        time.sleep(3)


# ---------------------------------------------------------------- 模型清单

class Model(NamedTuple):
    tag: str
    kind: str      # chat / guard / embed
    alias: str


def norm(tag: str) -> str:
    return tag if ":" in tag else tag + ":latest"


def load_models() -> list[Model]:
    out = []
    for line in MODELS_TXT.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        p = line.split()
        kind = p[1] if len(p) > 1 else "chat"
        alias = p[2] if len(p) > 2 and p[2] != "-" else ""
        out.append(Model(norm(p[0]), kind, alias))
    return out


def model_by_alias(alias: str) -> Model | None:
    return next((m for m in load_models() if m.alias == alias), None)


_caps: dict[str, list[str]] = {}


def capabilities(tag: str) -> list[str]:
    if tag not in _caps:
        r = http("POST", "/api/show", {"model": tag}, timeout=60)
        _caps[tag] = list(r.json.get("capabilities") or []) if r.status == 200 and isinstance(r.json, dict) else []
    return _caps[tag]


def thinks(tag: str) -> bool:
    return "thinking" in capabilities(tag)


# ---------------------------------------------------------------- 调用封装

USER_PING = "Reply with exactly one word: pong"
USER_SAFE = "How do I bake a loaf of bread?"


def native_chat(tag: str, content: str, extra: dict | None = None, num_predict: int = 64) -> Resp:
    body = {"model": tag, "messages": [{"role": "user", "content": content}], "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_predict": num_predict}}
    body.update(extra or {})
    return http("POST", "/api/chat", body)


def v1_chat(tag: str, content: str, extra: dict | None = None, max_tokens: int = 64) -> Resp:
    body = {"model": tag, "messages": [{"role": "user", "content": content}],
            "temperature": 0, "seed": 42, "max_tokens": max_tokens}
    body.update(extra or {})
    return http("POST", "/v1/chat/completions", body)


def native_parts(r: Resp) -> tuple[str, str, int]:
    """返回 (回答, 思考内容, 生成 token 数)。"""
    msg = (r.json or {}).get("message") or {}
    content = msg.get("content") or ""
    thinking = msg.get("thinking") or ""
    m = THINK_RE.search(content)
    if m and not thinking:
        thinking = m.group(0)
    return strip_think(content), thinking, int((r.json or {}).get("eval_count") or 0)


def v1_parts(r: Resp) -> tuple[str, str, int]:
    js = r.json or {}
    msg = ((js.get("choices") or [{}])[0] or {}).get("message") or {}
    content = msg.get("content") or ""
    thinking = msg.get("reasoning") or msg.get("reasoning_content") or ""
    m = THINK_RE.search(content)
    if m and not thinking:
        thinking = m.group(0)
    return strip_think(content), thinking, int((js.get("usage") or {}).get("completion_tokens") or 0)


# ---------------------------------------------------------------- 子命令：env

def cmd_env(_: argparse.Namespace) -> int:
    rep = Report()
    _, docker_v, _ = sh("docker", "version", "--format", "{{.Server.Version}}")
    _, compose_v, _ = sh("docker", "compose", "version", "--short")
    os_name = ""
    osr = Path("/etc/os-release")
    if osr.exists():
        m = re.search(r'^PRETTY_NAME="?([^"\n]+)', osr.read_text(), re.M)
        os_name = m.group(1) if m else ""
    r = http("GET", "/api/version", timeout=10)
    ollama_v = r.json.get("version", "") if r.status == 200 and isinstance(r.json, dict) else ""
    rows = [
        ("系统", os_name), ("内核", os.uname().release), ("CPU", cpu_name()), ("逻辑核数", str(os.cpu_count())),
        ("Docker Engine", docker_v or "未取到"), ("Docker Compose", compose_v or "未取到"),
        ("compose 中的镜像", compose_image() or "未取到"), ("Ollama 服务版本", ollama_v or "服务未运行"),
    ]
    for k, v in rows:
        rep.add("INFO", k, v)
    body = "| 项目 | 值 |\n| --- | --- |\n" + "\n".join(f"| {k} | {md(v)} |" for k, v in rows)
    write_section("env", "环境版本", body)
    return 0


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "未知"


# ---------------------------------------------------------------- 子命令：lock

def cmd_lock(_: argparse.Namespace) -> int:
    rep = Report()
    r = http("GET", "/api/tags", timeout=30)
    if r.status != 200:
        rep.add("FAIL", "读取 /api/tags", err_detail(r))
        write_section("models", "模型锁定清单", rep.markdown())
        return 1
    have = {m["name"]: m for m in r.json.get("models", [])}
    ver = http("GET", "/api/version", timeout=10)
    entries = []
    for m in load_models():
        t = have.get(m.tag)
        if not t:
            rep.add("FAIL", m.tag, "未拉取（运行 bash scripts/pull-models.sh）")
            continue
        d = t.get("details") or {}
        e = {"name": m.tag, "kind": m.kind, "alias": m.alias, "digest": t.get("digest", ""),
             "size_bytes": t.get("size", 0), "family": d.get("family", ""),
             "parameter_size": d.get("parameter_size", ""), "quantization": d.get("quantization_level", ""),
             "capabilities": capabilities(m.tag)}
        entries.append(e)
        rep.add("PASS", m.tag, f"{e['parameter_size']} {e['quantization']}，{e['size_bytes'] / 1e9:.2f} GB，"
                f"摘要 {e['digest'][:12]}，能力 {','.join(e['capabilities']) or '未知'}")
    for extra in sorted(set(have) - {m.tag for m in load_models()}):
        rep.add("WARN", extra, "容器里有但不在 models.txt 中（不需要可用 ollama rm 删除）")
    lock = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ollama_version": (ver.json or {}).get("version", "") if ver.status == 200 else "",
            "image": compose_image(), "models": entries}
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写 {LOCK.relative_to(ROOT)}")
    table = ["| 模型 | 类型 | 别名 | 参数量 | 量化 | 大小 GB | 摘要（前 12 位） | 能力 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in entries:
        table.append(f"| {e['name']} | {e['kind']} | {e['alias'] or '-'} | {e['parameter_size']} | "
                     f"{e['quantization']} | {e['size_bytes'] / 1e9:.2f} | {e['digest'][:12]} | "
                     f"{', '.join(e['capabilities'])} |")
    write_section("models", "模型锁定清单", rep.markdown() + "\n\n" + "\n".join(table))
    return 1 if rep.failed else 0


# ---------------------------------------------------------------- 子命令：smoke

def check_infra(rep: Report) -> str:
    """容器、镜像、端口、版本、云功能。返回容器 ID（空表示没有运行）。"""
    img = compose_image()
    if "@sha256:" in img and "UNPINNED" not in img:
        rep.add("PASS", "compose 镜像已锁定版本与摘要", img)
    else:
        rep.add("FAIL", "compose 镜像未锁定", f"当前为 {img or '未找到'}，运行 bash scripts/pin-image.sh")
    rc, _, err = sh("docker", "info", "--format", "{{.ServerVersion}}")
    if rc != 0:
        rep.add("FAIL", "Docker 可用", err or "docker info 失败")
        return ""
    cid = container_id()
    if not cid:
        rep.add("FAIL", "ollama 容器在运行", "没有找到容器，先 docker compose up -d")
        return ""
    health = wait_health(cid)
    rep.add("PASS" if health == "healthy" else "FAIL", "容器健康检查", health)
    pol = inspect(cid, "{{.HostConfig.RestartPolicy.Name}}")
    rep.add("PASS" if pol == "unless-stopped" else "FAIL", "重启策略 unless-stopped", pol)
    run_img = inspect(cid, "{{.Config.Image}}")
    if run_img == img:
        rep.add("PASS", "运行中的容器使用 compose 锁定的镜像")
    else:
        rep.add("WARN", "运行中的容器与 compose 镜像不一致", f"{run_img}；执行 docker compose up -d 重建")
    rc, out, _ = sh("docker", "port", cid, "11434/tcp")
    binds = [b for b in out.splitlines() if b.strip()]
    if binds and all(b.startswith("127.0.0.1:") for b in binds):
        rep.add("PASS", "11434 只绑定 127.0.0.1", ", ".join(binds))
    else:
        rep.add("FAIL", "11434 只绑定 127.0.0.1", ", ".join(binds) or "未发布端口")
    envs = inspect(cid, "{{range .Config.Env}}{{println .}}{{end}}").splitlines()
    want = {"OLLAMA_NO_CLOUD": "1", "OLLAMA_MAX_LOADED_MODELS": "3", "OLLAMA_KEEP_ALIVE": "24h"}
    for k, v in want.items():
        rep.add("PASS" if f"{k}={v}" in envs else "FAIL", f"环境变量 {k}={v}")
    _, logs_out, logs_err = sh("docker", "logs", "--tail", "400", cid)
    m = re.search(r"(?i)[^\n]*cloud[^\n]*disabled[^\n]*", logs_out + "\n" + logs_err)
    rep.add("INFO", "启动日志中的云功能状态", snippet(m.group(0), 120) if m else "日志里没找到 cloud disabled 字样，以环境变量为准")
    root = http("GET", "/", timeout=10)
    rep.add("PASS" if root.status == 200 and "Ollama is running" in root.text else "FAIL",
            f"宿主机访问 {BASE}/", snippet(root.text, 60) if root.status else err_detail(root))
    ver = http("GET", "/api/version", timeout=10)
    v = (ver.json or {}).get("version", "") if ver.status == 200 and isinstance(ver.json, dict) else ""
    want_v = image_version(img)
    if v and v == want_v:
        rep.add("PASS", "服务版本与锁定标签一致", v)
    else:
        rep.add("WARN" if v else "FAIL", "服务版本与锁定标签一致", f"服务 {v or '未取到'}，标签 {want_v or '未取到'}")
    return cid


def cmd_smoke(args: argparse.Namespace) -> int:
    rep = Report()
    cid = check_infra(rep)
    if args.infra or not cid:
        write_section("smoke", "冒烟测试" + ("（仅基础设施）" if args.infra else ""), rep.markdown())
        return 1 if rep.failed else 0

    models = load_models()
    tags = http("GET", "/api/tags", timeout=30)
    have = {m["name"] for m in (tags.json or {}).get("models", [])} if tags.status == 200 else set()
    v1m = http("GET", "/v1/models", timeout=30)
    v1ids = {m.get("id") for m in (v1m.json or {}).get("data", [])} if v1m.status == 200 else set()
    for m in models:
        ok = m.tag in have and (m.tag in v1ids or m.tag.removesuffix(":latest") in v1ids)
        rep.add("PASS" if ok else "FAIL", f"{m.tag} 出现在 /api/tags 与 /v1/models",
                "" if ok else "未拉取或名称不符，运行 bash scripts/pull-models.sh")

    for m in models:
        if m.tag not in have:
            continue
        if m.kind in ("chat", "guard"):
            smoke_chat(rep, m)
        elif m.kind == "embed":
            smoke_embed(rep, m)

    first = next((m for m in models if m.kind == "chat" and m.tag in have), None)
    if first:
        smoke_stream(rep, first)

    write_section("smoke", "冒烟测试", rep.markdown())
    return 1 if rep.failed else 0


def smoke_chat(rep: Report, m: Model) -> None:
    prompt = USER_SAFE if m.kind == "guard" else USER_PING
    think = thinks(m.tag)
    label = m.tag + (f"（{m.alias}）" if m.alias else "")

    r = native_chat(m.tag, prompt, {"think": False} if think else None)
    if r.status == 200:
        ans, th, n = native_parts(r)
        ok = bool(ans)
        rep.add("PASS" if ok else "FAIL", f"{label} 原生 /api/chat",
                f"{r.secs:.1f}s，{n} tok，回答：{snippet(ans) or '（空）'}" + ("，含思考内容" if th else ""))
        if m.kind == "guard":
            safe = ans.lower().startswith("safe")
            rep.add("PASS" if safe else "WARN", f"{label} 把正常问题判为 safe", snippet(ans))
    else:
        rep.add("FAIL", f"{label} 原生 /api/chat", err_detail(r))

    r = v1_chat(m.tag, prompt, {"reasoning_effort": "none"} if think else None)
    if r.status == 200:
        ans, th, n = v1_parts(r)
        if ans and th and think:
            rep.add("WARN", f"{label} /v1/chat/completions",
                    f"{r.secs:.1f}s，{n} tok，回答：{snippet(ans)}；已传 reasoning_effort=none 仍在思考，见步骤 5")
        elif ans:
            rep.add("PASS", f"{label} /v1/chat/completions",
                    f"{r.secs:.1f}s，{n} tok，回答：{snippet(ans)}" + ("，含思考内容" if th else ""))
        else:
            rep.add("FAIL", f"{label} /v1/chat/completions",
                    "回答为空" + ("，只有思考内容，见步骤 5" if th else ""))
    else:
        rep.add("FAIL", f"{label} /v1/chat/completions", err_detail(r))


def smoke_embed(rep: Report, m: Model) -> None:
    r = http("POST", "/api/embed", {"model": m.tag, "input": "hello gateway"})
    vec = ((r.json or {}).get("embeddings") or [[]])[0] if r.status == 200 else []
    rep.add("PASS" if vec else "FAIL", f"{m.tag} 原生 /api/embed",
            f"{r.secs:.2f}s，维度 {len(vec)}" if vec else err_detail(r))
    r = http("POST", "/v1/embeddings", {"model": m.tag, "input": "hello gateway"})
    data = ((r.json or {}).get("data") or []) if r.status == 200 else []
    vec = ((data[0] or {}).get("embedding") or []) if data else []
    rep.add("PASS" if vec else "FAIL", f"{m.tag} /v1/embeddings",
            f"{r.secs:.2f}s，维度 {len(vec)}" if vec else err_detail(r))


def smoke_stream(rep: Report, m: Model) -> None:
    body = {"model": m.tag, "messages": [{"role": "user", "content": "Count from 1 to 5."}],
            "stream": True, "temperature": 0, "max_tokens": 64}
    if thinks(m.tag):
        body["reasoning_effort"] = "none"
    r = http("POST", "/v1/chat/completions", body)
    if r.status != 200:
        rep.add("FAIL", f"{m.tag} /v1 流式输出", err_detail(r))
        return
    lines = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
    chunks = [ln for ln in lines if ln and ln != "[DONE]"]
    pieces = 0
    for c in chunks:
        try:
            delta = (json.loads(c).get("choices") or [{}])[0].get("delta") or {}
        except ValueError:
            continue
        if delta.get("content"):
            pieces += 1
    ok = pieces >= 2 and lines and lines[-1] == "[DONE]"
    rep.add("PASS" if ok else "FAIL", f"{m.tag} /v1 流式输出",
            f"{len(chunks)} 个数据块，其中 {pieces} 个含正文，结尾 {'[DONE]' if lines and lines[-1] == '[DONE]' else '缺少 [DONE]'}")


# ---------------------------------------------------------------- 子命令：think

THINK_PROMPT = "What is 17 + 25? Reply with only the number."


def cmd_think(args: argparse.Namespace) -> int:
    rep = Report()
    m = model_by_alias("chat-default")
    tag = norm(args.model) if args.model else (m.tag if m else "qwen3:0.6b")
    caps = capabilities(tag)
    rep.add("INFO", f"{tag} 声明的能力", ", ".join(caps) or "未取到（模型未拉取？）")
    if not caps:
        write_section("think", "qwen3 思考模式实测", rep.markdown())
        return 1

    native_chat(tag, "hi", {"think": False}, num_predict=8)  # 预热，不计时
    variants = [
        ("原生 · 不传 think", "native", {}, ""),
        ("原生 · think=false", "native", {"think": False}, ""),
        ("原生 · think=true", "native", {"think": True}, ""),
        ("/v1 · 不传参数", "v1", {}, ""),
        ("/v1 · reasoning_effort=none", "v1", {"reasoning_effort": "none"}, ""),
        ("/v1 · reasoning.effort=none", "v1", {"reasoning": {"effort": "none"}}, ""),
        ("/v1 · 提示词末尾加 /no_think", "v1", {}, " /no_think"),
        ("/v1 · think=false（非标准字段）", "v1", {"think": False}, ""),
    ]
    results = []
    for name, kind, extra, suffix in variants:
        prompt = THINK_PROMPT + suffix
        r = native_chat(tag, prompt, extra, 1024) if kind == "native" else v1_chat(tag, prompt, extra, 1024)
        if r.status != 200:
            results.append(dict(name=name, http=r.status, secs=r.secs, tok=0, thinking=None, ans=err_detail(r), ok=False))
            rep.add("WARN", name, err_detail(r))
            continue
        ans, th, n = native_parts(r) if kind == "native" else v1_parts(r)
        row = dict(name=name, http=200, secs=r.secs, tok=n, thinking=bool(th), think_chars=len(th),
                   ans=snippet(ans, 30), ok="42" in ans)
        results.append(row)
        rep.add("INFO", name, f"{r.secs:.1f}s，{n} tok，思考：{'有' if th else '无'}，回答：{row['ans'] or '（空）'}")

    def by(n: str) -> dict:
        return next(x for x in results if x["name"] == n)

    def works(x: dict) -> bool:
        return x["http"] == 200 and x["thinking"] is False and bool(x["ans"])

    if works(by("/v1 · reasoning_effort=none")):
        verdict = ("保留 qwen3:0.6b。/v1 的 reasoning_effort=none 能关闭思考；"
                   "P2 在 LiteLLM 的 chat-default 上固定附带该参数，并在网关层复测。")
        status = "PASS"
    elif works(by("/v1 · reasoning.effort=none")):
        verdict = ("保留 qwen3:0.6b。/v1 的 reasoning.effort=none 能关闭思考（reasoning_effort 不行）；"
                   "P2 需确认 LiteLLM 能原样透传该对象。")
        status = "PASS"
    elif works(by("/v1 · 提示词末尾加 /no_think")):
        verdict = ("只有提示词软开关 /no_think 有效，依赖用户输入，不可靠。按总纲把 chat-default 换成 qwen2.5:0.5b。")
        status = "WARN"
    else:
        verdict = "/v1 接口无法关闭思考。按总纲把 chat-default 换成 qwen2.5:0.5b。"
        status = "WARN"
    default_v1 = by("/v1 · 不传参数")
    rep.add("INFO", "/v1 默认是否思考", "是" if default_v1.get("thinking") else "否")
    rep.add(status, "建议", verdict)

    table = ["| 方式 | HTTP | 耗时 s | 生成 tok | 思考 | 回答 | 答对 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for x in results:
        th = "—" if x["thinking"] is None else ("有" if x["thinking"] else "无")
        table.append(f"| {md(x['name'])} | {x['http']} | {x['secs']:.1f} | {x['tok']} | {th} | {md(x['ans'])} | "
                     f"{'是' if x['ok'] else '否'} |")
    body = (f"模型 `{tag}`，问题“{THINK_PROMPT}”，temperature 0，seed 42，上限 1024 tok。\n\n"
            + "\n".join(table) + f"\n\n**建议**：{verdict}\n\n" + rep.markdown())
    write_section("think", "qwen3 思考模式实测", body)
    return 0


# ---------------------------------------------------------------- 子命令：warmup

def cmd_warmup(args: argparse.Namespace) -> int:
    rep = Report()
    targets = [m for m in load_models() if m.kind == "chat" or (args.guard and m.kind == "guard")]
    for m in targets:
        r = http("POST", "/api/generate", {"model": m.tag, "prompt": "", "keep_alive": args.keep_alive})
        load = (r.json or {}).get("load_duration", 0) / 1e9 if r.status == 200 else 0
        rep.add("PASS" if r.status == 200 else "FAIL", f"加载 {m.tag}",
                f"{r.secs:.1f}s（其中载入 {load:.1f}s）" if r.status == 200 else err_detail(r))
    ps = http("GET", "/api/ps", timeout=30)
    loaded = {x.get("name"): x for x in (ps.json or {}).get("models", [])} if ps.status == 200 else {}
    for m in targets:
        x = loaded.get(m.tag)
        rep.add("PASS" if x else "FAIL", f"{m.tag} 常驻内存",
                f"占用 {x.get('size', 0) / 1e9:.2f} GB，到期 {str(x.get('expires_at', ''))[:19]}" if x else "不在 /api/ps 中")
    write_section("warmup", "预热", rep.markdown())
    return 1 if rep.failed else 0


# ---------------------------------------------------------------- 子命令：persist

def cmd_persist(_: argparse.Namespace) -> int:
    rep = Report()
    cid = container_id()
    if not cid:
        rep.add("FAIL", "WSL 重启后容器自动运行", "没有容器；检查 systemctl is-active docker")
        write_section("persist", "WSL 重启后恢复", rep.markdown())
        return 1
    health = wait_health(cid)
    rep.add("PASS" if health == "healthy" else "FAIL", "容器健康", health)
    started = inspect(cid, "{{.State.StartedAt}}")
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        boot = time.time() - uptime
        start_ts = datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except (OSError, ValueError):
        uptime, boot, start_ts = -1, 0, 0
    rep.add("INFO", "容器启动时间 / WSL 已运行", f"{started[:19]}Z / {uptime / 60:.1f} 分钟")
    if start_ts and start_ts >= boot - 60:
        rep.add("PASS", "容器在本次 WSL 启动后自动拉起", f"启动于 WSL 开机后 {(start_ts - boot):.0f} 秒")
    else:
        rep.add("FAIL", "容器在本次 WSL 启动后自动拉起",
                "容器启动早于本次开机：确认刚做过 wsl --shutdown，且未手动 docker compose up")
    if not LOCK.exists():
        rep.add("FAIL", "models/lock.json 存在", "先完成步骤 3")
    else:
        lock = {e["name"]: e["digest"] for e in json.loads(LOCK.read_text(encoding="utf-8"))["models"]}
        tags = http("GET", "/api/tags", timeout=30)
        have = {m["name"]: m.get("digest", "") for m in (tags.json or {}).get("models", [])} if tags.status == 200 else {}
        same = [n for n, d in lock.items() if have.get(n) == d]
        ok = len(same) == len(lock)
        rep.add("PASS" if ok else "FAIL", "模型仍在且摘要与 lock.json 一致（无需重新下载）",
                f"{len(same)}/{len(lock)} 个一致")
    m = model_by_alias("chat-default")
    if m:
        r = native_chat(m.tag, USER_PING, {"think": False} if thinks(m.tag) else None)
        ans = native_parts(r)[0] if r.status == 200 else ""
        rep.add("PASS" if ans else "FAIL", f"重启后 {m.tag} 可对话",
                f"{r.secs:.1f}s（含冷启动载入），回答：{snippet(ans)}" if ans else err_detail(r))
    write_section("persist", "WSL 重启后恢复", rep.markdown())
    return 1 if rep.failed else 0


# ---------------------------------------------------------------- 子命令：bench

BENCH_PROMPT = ("Explain in about 100 words what an API gateway does for a company "
                "that lets many internal teams use several AI models.")
EMBED_TEXT = " ".join(["Mortgage applications contain names, addresses and income details."] * 10)


def cmd_bench(args: argparse.Namespace) -> int:
    rep = Report()
    models = load_models()
    ver = http("GET", "/api/version", timeout=10)
    info = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "cpu": cpu_name(), "threads": os.cpu_count(),
            "ollama": (ver.json or {}).get("version", "") if ver.status == 200 else "", "image": compose_image(),
            "power": args.power or "未注明"}
    BENCH_CSV.parent.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict] = []
    summary: list[list[str]] = []
    for m in models:
        if m.kind in ("chat", "guard"):
            prompt = BENCH_PROMPT if m.kind == "chat" else USER_SAFE
            extra = {"think": False} if thinks(m.tag) else {}
            native_chat(m.tag, "hi", extra, num_predict=4)  # 预热
            gen, pp, tot = [], [], []
            for i in range(args.runs):
                nonce = secrets.token_hex(4)  # 放在开头，避免提示缓存让后几次的提示处理失真
                r = native_chat(m.tag, f"[{nonce}] {prompt}", extra, num_predict=args.tokens)
                if r.status != 200:
                    rep.add("FAIL", f"{m.tag} 第 {i + 1} 次", err_detail(r))
                    continue
                js = r.json
                ec, ed = js.get("eval_count", 0), js.get("eval_duration", 0)
                pc, pd = js.get("prompt_eval_count", 0), js.get("prompt_eval_duration", 0)
                g = ec / (ed / 1e9) if ed else 0.0
                p = pc / (pd / 1e9) if pd else 0.0
                t = js.get("total_duration", 0) / 1e9
                gen.append(g)
                pp.append(p)
                tot.append(t)
                raw_rows.append({"date": info["date"], "model": m.tag, "kind": m.kind, "run": i + 1,
                                 "prompt_tokens": pc, "prompt_tps": round(p, 2), "gen_tokens": ec,
                                 "gen_tps": round(g, 2), "load_s": round(js.get("load_duration", 0) / 1e9, 3),
                                 "total_s": round(t, 3), "power": info["power"], "ollama": info["ollama"]})
            if gen:
                gm, pm, tm = statistics.median(gen), statistics.median(pp), statistics.median(tot)
                note = "生成量很少，只看单次耗时" if m.kind == "guard" else ""
                summary.append([m.tag, m.kind, f"{gm:.1f}", f"{pm:.1f}", f"{tm:.2f}", note])
                rep.add("PASS", m.tag, f"生成 {gm:.1f} tok/s，提示处理 {pm:.1f} tok/s，单次 {tm:.2f}s（中位数，{len(gen)} 次）")
        elif m.kind == "embed":
            http("POST", "/api/embed", {"model": m.tag, "input": "warm up"})
            secs = []
            for i in range(args.runs):
                r = http("POST", "/api/embed", {"model": m.tag, "input": EMBED_TEXT})
                if r.status == 200:
                    secs.append(r.secs)
                    raw_rows.append({"date": info["date"], "model": m.tag, "kind": m.kind, "run": i + 1,
                                     "prompt_tokens": (r.json or {}).get("prompt_eval_count", 0), "prompt_tps": "",
                                     "gen_tokens": "", "gen_tps": "", "load_s": "", "total_s": round(r.secs, 3),
                                     "power": info["power"], "ollama": info["ollama"]})
            if secs:
                sm = statistics.median(secs)
                summary.append([m.tag, m.kind, "—", "—", f"{sm:.2f}", "约 100 词文本，单次向量化"])
                rep.add("PASS", m.tag, f"单次向量化 {sm * 1000:.0f} ms（中位数）")
    new_file = not BENCH_CSV.exists()
    fields = ["date", "model", "kind", "run", "prompt_tokens", "prompt_tps", "gen_tokens", "gen_tps",
              "load_s", "total_s", "power", "ollama"]
    with BENCH_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if new_file:
            w.writeheader()
        w.writerows(raw_rows)
    print(f"原始数据已追加到 {BENCH_CSV.relative_to(ROOT)}")
    head = (f"{info['date']}，CPU {info['cpu']}（{info['threads']} 线程），Ollama {info['ollama']}，"
            f"电源模式：{info['power']}；每个模型 {args.runs} 次取中位数，生成上限 {args.tokens} tok，纯 CPU。")
    table = ["| 模型 | 类型 | 生成 tok/s | 提示处理 tok/s | 单次耗时 s | 备注 |", "| --- | --- | --- | --- | --- | --- |"]
    table += ["| " + " | ".join(md(c) for c in row) + " |" for row in summary]
    write_section("bench", "性能基线", head + "\n\n" + "\n".join(table) + "\n\n" + rep.markdown())
    return 1 if rep.failed else 0


# ---------------------------------------------------------------- 子命令：record

def cmd_record(args: argparse.Namespace) -> int:
    text = args.text if args.text is not None else (Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read())
    write_section(args.name, args.title or args.name, text)
    return 0


# ---------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("env").set_defaults(fn=cmd_env)
    sub.add_parser("lock").set_defaults(fn=cmd_lock)
    p = sub.add_parser("smoke")
    p.add_argument("--infra", action="store_true", help="只查容器、端口、镜像，不调用模型")
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("think")
    p.add_argument("--model", help="默认取 models.txt 中别名 chat-default 的模型")
    p.set_defaults(fn=cmd_think)
    p = sub.add_parser("warmup")
    p.add_argument("--guard", action="store_true", help="同时预热 guard 模型")
    p.add_argument("--keep-alive", default="24h")
    p.set_defaults(fn=cmd_warmup)
    sub.add_parser("persist").set_defaults(fn=cmd_persist)
    p = sub.add_parser("bench")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--tokens", type=int, default=128)
    p.add_argument("--power", help="电源模式说明，例如“插电·性能”")
    p.set_defaults(fn=cmd_bench)
    p = sub.add_parser("record")
    p.add_argument("name")
    p.add_argument("--title")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--text")
    g.add_argument("--file")
    p.set_defaults(fn=cmd_record)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
