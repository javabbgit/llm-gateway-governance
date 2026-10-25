"""PII 检测（P4a）：抽取消息文本、判定语言、调用 Presidio analyzer、在插件内做二次校验。

返回给调用方的是“片段位置 + 实体类型”，片段原文只在内存里用于脱敏，绝不写日志、审计或 metadata。
单独运行时（P4a，不经网关）从标准输入读测试语料，逐条检测，输出每条的类型与数量：
    docker compose exec -T litellm python3 /app/config/pii_detect.py < tests/pii_corpus.jsonl
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass

DEFAULT_URL = "http://presidio-analyzer:3000"

# ---------- 文本抽取 ----------
# 每段文本记下它在 messages 里的位置，脱敏时按位置写回：(消息序号, 分段序号或 None, 文本)
# 覆盖：content 字符串；content 数组里的 text 段；assistant 的 tool_calls 参数（只检测，脱敏时也替换）。


@dataclass(frozen=True)
class Segment:
    msg: int
    part: int | None      # content 为数组时是段序号；为字符串时是 None；tool_calls 参数用 -1-序号
    text: str


def extract_segments(messages) -> list[Segment]:
    segs: list[Segment] = []
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            segs.append(Segment(i, None, c))
        elif isinstance(c, list):
            for j, p in enumerate(c):
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str) and p["text"].strip():
                    segs.append(Segment(i, j, p["text"]))
        for k, tc in enumerate(m.get("tool_calls") or []):
            args = (tc or {}).get("function", {}).get("arguments") if isinstance(tc, dict) else None
            if isinstance(args, str) and args.strip():
                segs.append(Segment(i, -1 - k, args))
    return segs


# ---------- 语言判定（决策 25、26） ----------
# 任一段含非拉丁字母 → 非英文；否则数法语、西语常用词，至少 min_hits 个且多于英文常用词 → 非英文。
# 词表刻意避开与英文同形的词（a、on、son、plus、pour、par、de 等），宁可漏判也不把英文误判成外语。
EN_WORDS = frozenset(
    "the and is are was were of to in for with that this it you your we our be on as at from by please "
    "my have has will can an or not what how hello thanks they their there which would should could".split())
FR_WORDS = frozenset(
    "le la les des du une est et dans que qui sur je vous nous cette ces mon ma mes votre vos nos leur "
    "il elle sont été être avec mais où très bonjour merci veuillez avant après aussi depuis".split())
ES_WORDS = frozenset(
    "el los las del es y una por para con su sus mi está están pero muy más usted hola gracias "
    "nosotros favor envíe cuando como también".split())
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def language_status(texts: list[str], min_hits: int = 3) -> str:
    """返回 'en'，或非英文的原因：'script'（非拉丁字母）、'fr'、'es'。"""
    for t in texts:
        for ch in t:
            if ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN"):
                return "script"
    for t in texts:
        words = [w.lower() for w in WORD.findall(t)]
        en = sum(w in EN_WORDS for w in words)
        for code, vocab in (("fr", FR_WORDS), ("es", ES_WORDS)):
            hits = sum(w in vocab for w in words)
            if hits >= min_hits and hits > en:
                return code
    return "en"


# ---------- 二次校验 ----------
def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits][::-1]
    total = 0
    for i, x in enumerate(d):
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        total += x
    return total % 10 == 0


def validate(entity: str, value: str) -> bool:
    """模式识别器在 YAML 里不能运行代码，校验放在这里。只看内存里的片段，不输出它。"""
    if entity == "CA_SIN":
        digits = re.sub(r"\D", "", value)
        # 0 开头的号码从未发放；8 开头是商业编号，不是个人 SIN
        return len(digits) == 9 and digits[0] not in "08" and luhn_ok(digits)
    return True


# ---------- 调用 Presidio ----------
@dataclass(frozen=True)
class Finding:
    seg: int              # 段序号（extract_segments 的下标）
    entity: str
    start: int
    end: int
    score: float


@dataclass
class Detection:
    status: str           # ok / timeout / error / unavailable
    findings: list
    ms: int
    error: str = ""       # 只记异常类型或 HTTP 状态码，不记响应内容

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.entity] = out.get(f.entity, 0) + 1
        return out


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """同一段里重叠的命中只留分数最高的（例如 9 位 SIN 同时被当成银行账号片段）。"""
    kept: list[Finding] = []
    for f in sorted(findings, key=lambda x: (x.seg, -x.score, x.start)):
        if any(k.seg == f.seg and f.start < k.end and k.start < f.end for k in kept):
            continue
        kept.append(f)
    return sorted(kept, key=lambda x: (x.seg, x.start))


async def analyze(texts: list[str], *, entities: list[str], score_threshold: float, allow_list: list[str],
                  language: str = "en", timeout: float = 3.0, url: str | None = None, client=None) -> Detection:
    """一次请求批量检测所有文本段。任何异常都返回非 ok 状态，由策略按 high 处理（fail-closed）。"""
    t0 = time.perf_counter()
    if not texts:
        return Detection("ok", [], 0)
    url = (url or os.environ.get("PRESIDIO_URL") or DEFAULT_URL).rstrip("/") + "/analyze"
    body = {"text": texts, "language": language, "entities": entities,
            "score_threshold": score_threshold, "allow_list": list(allow_list)}
    try:
        import httpx  # LiteLLM 镜像自带

        async def call():
            if client is not None:
                return await client.post(url, json=body)
            async with httpx.AsyncClient() as c:
                return await c.post(url, json=body)

        r = await asyncio.wait_for(call(), timeout=timeout)
        if r.status_code != 200:
            return Detection("error", [], _ms(t0), f"HTTP {r.status_code}")
        data = r.json()
        if not isinstance(data, list) or len(data) != len(texts):
            return Detection("error", [], _ms(t0), "unexpected response shape")
        found = []
        for i, results in enumerate(data):
            for x in results or []:
                ent, s, e = x.get("entity_type"), int(x.get("start", 0)), int(x.get("end", 0))
                if ent in entities and 0 <= s < e <= len(texts[i]) and validate(ent, texts[i][s:e]):
                    found.append(Finding(i, ent, s, e, float(x.get("score", 0))))
        return Detection("ok", _dedupe(found), _ms(t0))
    except asyncio.TimeoutError:
        return Detection("timeout", [], _ms(t0), "timeout")
    except Exception as e:  # noqa: BLE001  连接被拒、DNS 失败等：检测器不可用
        name = type(e).__name__
        status = "unavailable" if "Connect" in name or "Network" in name or isinstance(e, OSError) else "error"
        return Detection(status, [], _ms(t0), name)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ---------- P4a：不经网关，批量跑测试语料 ----------
async def _run_corpus(lines: list[str]) -> list[dict]:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pii_policy

    policy = pii_policy.load_policy(os.environ.get("GOVERNANCE_POLICY", "/app/governance/policy.toml"))
    out = []
    for line in lines:
        if not line.strip():
            continue
        case = json.loads(line)
        messages = case.get("messages") or [{"role": "user", "content": case["text"]}]
        segs = extract_segments(messages)
        texts = [s.text for s in segs]
        det = await analyze(texts, entities=policy.entities, score_threshold=policy.score_threshold,
                            allow_list=list(policy.allow_list), language=policy.language,
                            timeout=float(os.environ.get("DETECT_TIMEOUT", policy.timeout_seconds)))
        # 只输出类型、数量、状态与耗时，不输出命中的文本
        out.append({"id": case["id"], "status": det.status, "ms": det.ms, "counts": det.counts(),
                    "lang": language_status(texts, policy.min_hits),
                    "scores": {f.entity: round(f.score, 2) for f in det.findings}})
    return out


if __name__ == "__main__":
    for row in asyncio.run(_run_corpus(sys.stdin.read().splitlines())):
        print(json.dumps(row, ensure_ascii=False))
