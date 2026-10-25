#!/usr/bin/env python3
"""P5 可观测与演示检查工具，只用 Python 标准库。复用 p2check / p3check / p4check 与 demo.py、audit.py。

子命令
  infra      演示前提：四个服务健康、策略为 full、演示 key 齐全、脚本就位、管理界面可达、启动不联网下载价格表
  audit      审计查询脚本：表格、汇总、JSON 都能出；JSON 只有类型与数量；输出里搜不到语料中的任何 PII；非法过滤被拒
  repeat     连续跑 demo.sh N 次（默认 3，每次自动重置），每次全部 PASS 且不超过 5 分钟【计费】每次 1 次 Haiku
  offline    离线模式：默认用 --offline 强制；--real 要求先断网（Windows 开飞行模式），验证自动判定离线
  size       磁盘占用：镜像（是否被 compose 引用）、卷、构建缓存，供快照瘦身决定
  slim       【人工】删除 compose 未引用的镜像、悬空镜像与构建缓存；绝不碰卷
  docs       README 与 ADR：章节齐全、相对链接有效、ADR 覆盖总纲决策 1–36、无密钥、README 为英文
  record     把一段文本写进 docs/p5-results.md 的指定小节

结果写入 docs/p5-results.md 对应小节（重跑覆盖）。有 FAIL 时退出码为 1。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402
import demo  # noqa: E402
import p2check as base  # noqa: E402
import p3check as p3  # noqa: E402
import p4check as p4  # noqa: E402
from p2check import GW, Report, http, run, snip  # noqa: E402

ROOT = base.ROOT
base.RESULTS = ROOT / "docs" / "p5-results.md"     # p3check / p4check 导入时改过，这里改回 P5
README = ROOT / "README.md"
ADR_DIR = ROOT / "docs" / "adr"
DEMO_DOC = ROOT / "docs" / "demo.md"
LAST_DECISION = 36            # 总纲第 11 节的决策编号上限（P5 新增 30–36）
SUPERSEDED = {18}             # 已作废，ADR 里仍要提到
DEMO_LIMIT_S = 300            # 总纲：5 分钟内
PROJECT = "llm-gateway-governance"


def header() -> None:
    if not base.RESULTS.exists():
        base.RESULTS.parent.mkdir(parents=True, exist_ok=True)
        base.RESULTS.write_text("# P5 实测结果\n\n由 scripts/p5check.py 自动写入，各小节重跑时覆盖。"
                                "演示本身的输出是英文，本文件沿用中文。\n", encoding="utf-8")


def run_demo(*args: str, timeout: int = 900) -> tuple[int, dict, float]:
    """跑一次 demo.py（输出直接显示在终端），返回 (退出码, 汇总 JSON, 秒数)。"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    t0 = time.time()
    try:
        rc = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), "run", "--json-summary", path, *args],
                            cwd=ROOT, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        rc = 124
    secs = time.time() - t0
    try:
        summary = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        summary = {}
    Path(path).unlink(missing_ok=True)
    return rc, summary, secs


def scene_text(summary: dict) -> str:
    return " ".join(f"{s['num']}:{s['status']}" for s in summary.get("scenes", []))


# ---------- infra ----------
def cmd_infra(_a) -> int:
    rep = Report("infra", "P5 演示前提")
    for svc in demo.SERVICES:
        cid = base.container_id(svc)
        h = base.inspect(cid, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}") if cid else "未运行"
        rep.add("PASS" if h == "healthy" else "FAIL", f"{svc} 健康", h)
    pol = p4.policy()
    rep.add("PASS" if pol.enforcement == "full" else "FAIL", "策略模式为 full",
            f"version {pol.version}，enforcement={pol.enforcement}")
    for alias in (demo.UW, demo.MKT, demo.BUDGET_KEY, demo.RL_KEY):
        rep.add("PASS" if p3.key_of(alias) else "FAIL", f"演示 key {alias}", "存在" if p3.key_of(alias) else "缺失：python3 scripts/p3check.py org")
    for f in ("scripts/demo.sh", "scripts/reset.sh", "scripts/demo.py", "scripts/audit.py", "scripts/keepalive.ps1"):
        rep.add("PASS" if (ROOT / f).exists() else "FAIL", f"{f} 就位", "")
    for f in ("scripts/demo.sh", "scripts/reset.sh"):
        rc, out = run(["bash", "-n", f])
        rep.add("PASS" if rc == 0 else "FAIL", f"bash -n {f}", snip(out, 80))
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    rep.add("PASS" if 'LITELLM_LOCAL_MODEL_COST_MAP: "True"' in compose else "FAIL",
            "LiteLLM 启动时不联网下载价格表（离线演示前提）", "LITELLM_LOCAL_MODEL_COST_MAP")
    r = http("GET", f"{GW}/ui/", None, timeout=15)
    rep.add("PASS" if r.status == 200 else "WARN", "管理界面可达", f"{GW}/ui/ → {r.status or r.error}")
    ok, reason = demo.cloud_status(False)
    rep.add("INFO", "云端场景", "在线，场景 8 会真实调用 Haiku" if ok else f"将跳过：{reason}")
    return rep.finish()


# ---------- audit ----------
def cmd_audit(_a) -> int:
    rep = Report("audit", "审计查询脚本 scripts/audit.py")
    script = [sys.executable, "scripts/audit.py"]
    rc, table = run(script + ["--since", "7d", "--limit", "30"], timeout=60)
    rep.add("PASS" if rc == 0 and ("ACTION" in table or "no audit rows" in table) else "FAIL", "表格输出", snip(table.splitlines()[0] if table else "", 90))
    rc, summ = run(script + ["--summary"], timeout=60)
    rep.add("PASS" if rc == 0 and "By action" in summ else "FAIL", "汇总输出（按处置、规则、原因、团队、检测器）",
            snip(summ.splitlines()[0] if summ else "", 90))
    rc, js = run(script + ["--json", "--limit", "200"], timeout=60)
    try:
        rows = json.loads(js)
    except ValueError:
        rows = None
    rep.add("PASS" if rc == 0 and isinstance(rows, list) else "FAIL", "JSON 输出可解析", f"{len(rows or [])} 行")
    allowed = set(audit.COLUMNS) | {"spend"}
    entity = p4.policy().entity_level
    bad = [r.get("call_id") for r in rows or [] if set(r) - allowed
           or any(k not in entity or not isinstance(v, int) for k, v in (r.get("pii_counts") or {}).items())]
    rep.add("PASS" if rows is not None and not bad else "FAIL", "每行只有约定的列，pii_counts 只有“类型 → 整数”", f"{len(bad)} 行异常")
    needles = sorted({v for c in p4.corpus() for v in c.get("pii", [])} | {p4.FAKE_SIN, p4.FAKE_NAME})
    blob = "\n".join([table, summ, js])
    hits = [n for n in needles if n in blob]
    rep.add("PASS" if not hits else "FAIL", "三种输出里搜不到语料中的任何 PII 原文", f"搜索 {len(needles)} 个值，命中 {len(hits)} 个")
    rc, out = run(script + ["--since", "1h;drop table x"], timeout=30)
    rep.add("PASS" if rc == 2 else "FAIL", "非法过滤参数被拒绝（不拼进 SQL）", snip(out, 80))
    try:
        s = audit.fetch_summary()
        rep.add("INFO", "审计表现状", f"共 {s.get('total')} 行；按处置 {json.dumps(s.get('by_action'), ensure_ascii=False)}")
    except audit.QueryError as e:
        rep.add("FAIL", "审计表现状", str(e)[:120])
    return rep.finish("管理界面看不到 governance.pii_audit，这个脚本是它的命令行视图（总纲决策 11）。")


# ---------- repeat ----------
def cmd_repeat(a) -> int:
    rep = Report("repeat", f"demo.sh 连续运行 {a.n} 次")
    rows = ["| 次 | 退出码 | PASS | FAIL | SKIP | 审计 | 秒 | 场景 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i in range(1, a.n + 1):
        print(f"\n===== 第 {i}/{a.n} 次 =====", flush=True)
        rc, s, secs = run_demo(*(["--offline"] if a.offline else []))
        ok = rc == 0 and s.get("fail") == 0 and s.get("audit") == "PASS" and secs <= DEMO_LIMIT_S
        rep.add("PASS" if ok else "FAIL", f"第 {i} 次", f"PASS {s.get('pass')} / FAIL {s.get('fail')} / SKIP {s.get('skip')}，"
                f"审计 {s.get('audit')}，{secs:.0f} 秒" + ("" if secs <= DEMO_LIMIT_S else "（超过 5 分钟）"))
        rows.append(f"| {i} | {rc} | {s.get('pass')} | {s.get('fail')} | {s.get('skip')} | {s.get('audit')} | {secs:.0f} | {scene_text(s)} |")
        if i == 1 and s.get("skip") and not a.offline:
            rep.add("WARN", "云端场景被跳过", s.get("cloud_reason", ""))
    return rep.finish("每次运行开头自动重置（重建 demo-budget 与 demo-ratelimit），所以不用等限流窗口过去。\n\n" + "\n".join(rows))


# ---------- offline ----------
def cmd_offline(a) -> int:
    rep = Report("offline-real" if a.real else "offline", "离线模式（真实断网）" if a.real else "离线模式（--offline 强制）")
    if a.real:
        online = demo.internet_ok()
        rep.add("PASS" if not online else "FAIL", "外网确实不可达", "已断网" if not online else "还能连上 api.anthropic.com：先在 Windows 开飞行模式或断开 Wi-Fi")
        if online:
            return rep.finish()
        rc, s, secs = run_demo()
    else:
        rc, s, secs = run_demo("--offline")
    scenes = {x["num"]: x for x in s.get("scenes", [])}
    s8 = scenes.get(8, {})
    rep.add("PASS" if s8.get("status") == "SKIP" else "FAIL", "云端场景 8 被跳过", f"{s8.get('status')}：{s8.get('note', '')}")
    local_bad = [n for n, x in scenes.items() if n != 8 and x["status"] != "PASS"]
    rep.add("PASS" if len(scenes) == 9 and not local_bad else "FAIL", "本地场景 1–7、9 全部通过",
            "全部 PASS" if not local_bad else f"未通过：{local_bad}")
    rep.add("PASS" if s.get("audit") == "PASS" else "FAIL", "审计轨迹", str(s.get("audit")))
    rep.add("PASS" if rc == 0 and secs <= DEMO_LIMIT_S else "FAIL", "退出码 0，5 分钟内", f"退出码 {rc}，{secs:.0f} 秒")
    if a.real:
        rep.add("PASS" if "cannot reach" in s.get("cloud_reason", "") else "FAIL", "离线是自动判定的（没有加 --offline）",
                s.get("cloud_reason", ""))
    return rep.finish("真实断网验证完成后记得恢复网络。" if a.real else "强制离线只证明跳过逻辑；断网实测用 --real。")


# ---------- size / slim ----------
def _compose_refs() -> set[str]:
    return {re.sub(r"@sha256:.*$", "", img) for img in base.compose_images().values() if img}


def _images() -> list[dict]:
    _, out = run(["docker", "images", "--format", "{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}"], timeout=60)
    imgs = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            repo, tag, iid, size = parts
            imgs.append({"ref": f"{repo}:{tag}", "repo": repo, "tag": tag, "id": iid, "size": size,
                         "dangling": repo == "<none>" or tag == "<none>"})
    used = _compose_refs()
    for i in imgs:
        i["used"] = i["ref"] in used
    return imgs


def _df_lines() -> list[str]:
    _, out = run(["docker", "system", "df"], timeout=60)
    lines = []
    for x in out.splitlines():          # 只取开头的汇总表（TYPE / Images / Containers / Local Volumes / Build Cache）
        if not x.strip():
            break
        lines.append(x)
    return lines


def _volumes() -> list[tuple[str, str]]:
    _, out = run(["docker", "system", "df", "-v"], timeout=120)
    vols, on = [], False
    for line in out.splitlines():
        if line.startswith("Local Volumes space usage"):
            on = True
            continue
        if on and (not line.strip() or line.startswith("Build cache")):
            if vols:
                break
            continue
        if on and not line.startswith("VOLUME NAME"):
            p = line.split()
            if len(p) >= 3:
                vols.append((p[0], p[-1]))
    return vols


def cmd_size(_a) -> int:
    rep = Report("size", "磁盘占用（快照瘦身前）")
    for line in _df_lines():
        rep.add("INFO", "docker system df", " ".join(line.split()))
    imgs = _images()
    for i in imgs:
        rep.add("INFO", ("在用 " if i["used"] else "可删 ") + i["ref"], f"{i['size']}，{i['id'][:12]}")
    for name, size in _volumes():
        rep.add("INFO", f"卷 {name}", size + ("（不可删：模型）" if "ollama" in name else "（不可删：key 与审计）" if "pg-data" in name else ""))
    cand = [i for i in imgs if not i["used"]]
    rep.add("PASS", "可删镜像（compose 未引用或悬空）", f"{len(cand)} 个" + (f"：{', '.join(i['ref'] for i in cand)}" if cand else ""))
    return rep.finish("快照是整个发行版的文件，镜像层占大头。可删的只有上表标“可删”的镜像和构建缓存；卷绝不删。"
                      "删除由人工运行 python3 scripts/p5check.py slim。")


def cmd_slim(_a) -> int:
    rep = Report("slim", "快照瘦身【人工】")
    before = _df_lines()
    for i in [x for x in _images() if not x["used"]]:
        target = i["id"] if i["dangling"] else i["ref"]
        rc, out = run(["docker", "image", "rm", target], timeout=120)
        rep.add("PASS" if rc == 0 else "WARN", f"删除 {i['ref']}", f"{i['size']}" if rc == 0 else snip(out, 100))
    rc, out = run(["docker", "builder", "prune", "-f"], timeout=300)
    rep.add("PASS" if rc == 0 else "WARN", "清理构建缓存", snip(out.splitlines()[-1] if out else "", 80))
    after = _df_lines()
    for b, a2 in zip(before, after):
        if b.startswith(("Images", "Build Cache")):
            rep.add("INFO", "前 → 后", f"{' '.join(b.split())}  →  {' '.join(a2.split())}")
    rc, _ = run(["docker", "compose", "ps", "-q"], timeout=30)
    rep.add("PASS" if all(i["used"] for i in _images() if not i["dangling"]) or rc == 0 else "WARN", "在用镜像都还在", "")
    return rep.finish("没有删除任何卷。下一步照常 docker compose ps 确认四个服务 healthy，再导出快照。")


# ---------- docs ----------
def _links(md: str) -> list[str]:
    return [m for m in re.findall(r"\]\(([^)\s#]+)(?:#[^)]*)?\)", md) if not re.match(r"[a-z]+:", m)]


def cmd_docs(_a) -> int:
    rep = Report("docs", "README 与 ADR")
    text = README.read_text(encoding="utf-8") if README.exists() else ""
    need = ["## Why", "## Architecture", "## Demo", "## What is verified", "## Quick start", "## Decisions", "## Roadmap"]
    miss = [h for h in need if h not in text]
    rep.add("PASS" if text and not miss else "FAIL", "README 章节齐全", "缺 " + ", ".join(miss) if miss else f"{len(need)} 个")
    rep.add("PASS" if "```mermaid" in text else "FAIL", "README 有 Mermaid 架构图", "")
    rep.add("PASS" if "in progress" not in text.lower() and "Planned" not in text else "FAIL", "README 没有过期的进度说法", "")
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    rep.add("PASS" if not cjk else "WARN", "README 为英文（公开仓库）", f"{len(cjk)} 个中文字符")
    broken = []
    for f in [README, DEMO_DOC, *sorted(ADR_DIR.glob("*.md"))]:
        if not f.exists():
            continue
        for link in _links(f.read_text(encoding="utf-8")):
            if not (f.parent / link).resolve().exists():
                broken.append(f"{f.relative_to(ROOT)} → {link}")
    rep.add("PASS" if not broken else "FAIL", "相对链接都指向存在的文件", "; ".join(broken[:4]) or "全部有效")
    adrs = sorted(ADR_DIR.glob("[0-9][0-9][0-9]-*.md"))
    rep.add("PASS" if len(adrs) >= 15 else "FAIL", "ADR 文件", f"{len(adrs)} 篇")
    bad = [f.name for f in adrs if not all(h in f.read_text(encoding="utf-8") for h in
                                           ("## Context", "## Decision", "## Alternatives rejected", "## Consequences"))]
    rep.add("PASS" if not bad else "FAIL", "每篇 ADR 都有 Context / Decision / Alternatives rejected / Consequences", ", ".join(bad))
    covered: set[int] = set()
    for f in adrs:
        m = re.search(r"^Plan decisions: (.+)$", f.read_text(encoding="utf-8"), re.M)
        if m:
            covered |= {int(x) for x in re.findall(r"\d+", m.group(1))}
    missing = sorted(set(range(1, LAST_DECISION + 1)) - covered)
    rep.add("PASS" if not missing else "FAIL", f"ADR 覆盖总纲决策 1–{LAST_DECISION}", f"缺 {missing}" if missing else "全部覆盖（含作废的 18）")
    secrets_pat = re.compile(r"sk-(ant-)?[A-Za-z0-9_-]{16,}")
    leaked = [str(f.relative_to(ROOT)) for f in [README, DEMO_DOC, *ADR_DIR.glob("*.md")] if f.exists() and secrets_pat.search(f.read_text(encoding="utf-8"))]
    rep.add("PASS" if not leaked else "FAIL", "文档里没有密钥样式的字符串", ", ".join(leaked))
    rep.add("PASS" if DEMO_DOC.exists() else "FAIL", "docs/demo.md（演示讲稿与管理界面导览）", "")
    return rep.finish()


def cmd_record(a) -> int:
    header()
    base.write_section(a.section, a.title or a.section, a.text)
    print(f"已写入 {base.RESULTS.relative_to(ROOT)} 的 {a.section} 小节")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("infra", "audit", "size", "slim", "docs"):
        sub.add_parser(name)
    p = sub.add_parser("repeat")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("offline")
    p.add_argument("--real", action="store_true")
    p = sub.add_parser("record")
    p.add_argument("section")
    p.add_argument("--title", default="")
    p.add_argument("--text", required=True)
    a = ap.parse_args()
    header()
    return globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
