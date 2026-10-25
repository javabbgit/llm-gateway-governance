"""治理插件（P4：PII 检测与数据驻留路由）。

挂在 LiteLLM 的钩子上，所有判断集中在这一处（总纲决策 12）：
- async_pre_call_hook：路由之前运行。抽取文本 → 语言判定 → Presidio 检测 → 处置矩阵（governance/policy.toml）
  → 放行 / 脱敏 / 改道 / 阻断 → 按最终模型丢弃受控参数（决策 20）→ 写审计表。
  LiteLLM 只在鉴权时查一次模型白名单，钩子里改写目标模型不会再查，所以改道前插件自己核对白名单。
- async_post_call_success_hook：非流式回答，把占位符还原成原文。
- async_post_call_streaming_iterator_hook：流式回答需要还原时，缓存整段上游流、还原后重放（决策 23）。
- async_post_call_response_headers_hook：用 x-governance-* 响应头告诉应用处置结果
  （改道后 LiteLLM 会把回答里的 model 字段改回应用请求的名字，只看 model 字段看不出改道）。
- async_log_success_event / async_log_failure_event：在审计表回填实际使用的模型与结果。
- async_logging_hook：Ollama 短响应 ID 换成唯一 ID（P3）。

日志、审计、响应头只有元数据与“类型:数量”，绝不出现请求或回答的原文；占位符映射只在本进程内存里。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 同目录的 pii_* 模块

import pii_detect  # noqa: E402
import pii_policy  # noqa: E402
import pii_redact  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

POLICY_FILE = os.environ.get("GOVERNANCE_POLICY", "/app/governance/policy.toml")
try:
    POLICY = pii_policy.load_policy(POLICY_FILE)
    POLICY_ERROR = ""
except pii_policy.PolicyError as e:      # 读不出策略：不让网关静默放行，所有请求阻断（见 pre_call）
    POLICY, POLICY_ERROR = None, str(e)
STAGE = f"p4-{POLICY.enforcement}" if POLICY else "p4-policy-error"

# 网关统一管控的模型参数：对这些逻辑名，丢弃应用自带的同名参数（P3，决策 20）。
LOCKED_PARAMS = {
    "chat-default": ("reasoning_effort", "reasoning"),
    "chat-cloud": ("reasoning_effort", "reasoning", "thinking", "temperature", "top_p", "top_k"),
}

SHORT_ID = re.compile(r"^chatcmpl-\d{1,6}$")
STATE_TTL = 600            # 秒；占位符映射与响应头信息最多保留这么久
_state: dict[str, dict] = {}


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"{ts} {msg}", file=sys.stderr, flush=True)


def _unique_id(obj, call_id: str) -> bool:
    rid = getattr(obj, "id", None)
    if isinstance(rid, str) and SHORT_ID.match(rid):
        obj.id = f"chatcmpl-{call_id}"
        return True
    return False


def _purge() -> None:
    now = time.monotonic()
    for k in [k for k, v in _state.items() if now - v["t"] > STATE_TTL]:
        _state.pop(k, None)


def _allowed_models(u) -> set | None:
    """调用方能用的逻辑名。None = 不限（master key，或 key 与团队都没设白名单）。"""
    base = list(getattr(u, "models", None) or []) or list(getattr(u, "team_models", None) or [])
    if not base or "all-proxy-models" in base or "*" in base:
        return None
    return set(base)


_JUR_CACHE: dict[str, str | None] = {}


def _jurisdiction(model: str) -> str | None:
    """读 config.yaml 里这个逻辑名的 model_info.jurisdiction。找不到返回 None（策略按未批准处理）。"""
    if model in _JUR_CACHE:
        return _JUR_CACHE[model]
    jur = None
    try:
        from litellm.proxy.proxy_server import llm_router
        for d in (llm_router.get_model_list(model_name=model) or []) if llm_router else []:
            j = (d.get("model_info") or {}).get("jurisdiction")
            if j:
                jur = str(j)
                break
    except Exception as e:  # noqa: BLE001
        _log(f"policy_warn: jurisdiction lookup failed model={model} err={type(e).__name__}")
        return None
    _JUR_CACHE[model] = jur
    return jur


def _texts(data: dict) -> tuple[list, list[str]]:
    segs = pii_detect.extract_segments(data.get("messages"))
    texts = [s.text for s in segs]
    if "messages" not in data:      # 非对话接口：只检测，不脱敏
        for k in ("input", "prompt"):
            v = data.get(k)
            texts += [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]
    return segs, texts


class _Audit:
    """审计表写入。直接用 psycopg（LiteLLM 镜像经 litellm-proxy-extras 自带）连 DATABASE_URL。
    写失败只记一行错误、不阻断请求：数据库不可用时 LiteLLM 的 key 鉴权会先失败。"""

    INSERT = (
        "INSERT INTO governance.pii_audit (call_id, team, key_alias, requested_model, routed_model, outcome, "
        "pii_counts, level, reason, action, rule, detector_status, language, detect_ms, redacted, stream, "
        "policy_version) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (call_id) DO NOTHING"
    )
    UPDATE = ("UPDATE governance.pii_audit SET served_model = COALESCE(%s, served_model), outcome = %s "
              "WHERE call_id = %s AND outcome IN ('pending', 'failure')")

    def __init__(self):
        self._conn = None
        self._lock = asyncio.Lock()

    async def _exec(self, sql: str, params: tuple) -> None:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        import psycopg
                        self._conn = await psycopg.AsyncConnection.connect(os.environ.get("GOVERNANCE_DATABASE_URL") or os.environ["DATABASE_URL"], autocommit=True,
                                                                           connect_timeout=3)
                    await self._conn.execute(sql, params)
                    return
                except Exception as e:  # noqa: BLE001
                    self._conn = None
                    if attempt == 2:
                        _log(f"audit_error: {type(e).__name__} call_id={params[0] if sql is self.INSERT else params[-1]}")

    async def insert(self, **r) -> None:
        await self._exec(self.INSERT, (
            r["call_id"], r["team"], r["key_alias"], r["requested"], r["routed"], r["outcome"],
            json.dumps(r["counts"]), r["level"], r["reason"], r["action"], r["rule"], r["detector"],
            r["language"], r["ms"], r["redacted"], r["stream"], r["policy_version"]))

    async def finish(self, call_id: str, served: str | None, outcome: str) -> None:
        await self._exec(self.UPDATE, (served, outcome, call_id))


class GovernancePlugin(CustomLogger):
    def __init__(self):
        super().__init__()
        self.audit = _Audit()
        self._http = None
        if POLICY is None:
            _log(f"policy_error: {POLICY_ERROR}；所有请求将被阻断")
        elif POLICY.enforcement == "off":
            _log("policy_warn: enforcement=off，PII 检测与驻留路由未启用（只应出现在 P4a/P4b）")

    def _client(self):
        if self._http is None:
            import httpx
            self._http = httpx.AsyncClient()
        return self._http

    # ---------- 请求进来 ----------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        from fastapi import HTTPException

        call_id = data.get("litellm_call_id", "-")
        requested = data.get("model", "-")
        alias = getattr(user_api_key_dict, "key_alias", None) or "-"
        team = getattr(user_api_key_dict, "team_alias", None) or "-"
        stream = bool(data.get("stream"))
        head = f"call_id={call_id} model={requested} key_alias={alias} team={team} call_type={call_type}"

        if POLICY is None:
            _log(f"policy_check: block (policy-error) {head}")
            raise HTTPException(status_code=503, detail={"error": "governance policy unavailable; request blocked"})

        if POLICY.enforcement == "off":
            dropped = [p for p in LOCKED_PARAMS.get(requested, ()) if data.pop(p, None) is not None]
            _log(f"policy_check: pass ({STAGE}) {head}" + (f" dropped_params={','.join(dropped)}" if dropped else ""))
            return data

        _purge()
        segs, texts = _texts(data)
        lang = pii_detect.language_status(texts, POLICY.min_hits)
        det = await pii_detect.analyze(
            texts, entities=POLICY.entities, score_threshold=POLICY.score_threshold,
            allow_list=list(POLICY.allow_list), language=POLICY.language,
            timeout=POLICY.timeout_seconds, client=self._client())
        counts = det.counts()
        d = pii_policy.decide(
            POLICY, requested=requested, jurisdiction=_jurisdiction(requested), counts=counts,
            detector_ok=det.ok, language_ok=(lang == "en"), allowed_models=_allowed_models(user_api_key_dict))

        redacted = 0
        mapping: dict = {}
        if d.action == "redact":
            if segs and det.findings:
                data["messages"], mapping = pii_redact.redact(data["messages"], segs, det.findings)
                redacted = sum(1 for _ in det.findings)
        elif d.action == "reroute":
            data["model"] = d.target

        # 受控参数按“最终模型”处理；改道时连原目标的受控参数一起丢（如 chat-cloud 的 thinking 不能带给 qwen3）
        locked = set(LOCKED_PARAMS.get(d.target, ()))
        if d.target != requested:
            locked |= set(LOCKED_PARAMS.get(requested, ()))
        dropped = sorted(p for p in locked if data.pop(p, None) is not None)

        summary = (f"pii={pii_policy.counts_text(counts)} level={d.level} rule={d.rule} reason={d.reason} "
                   f"detector={det.status} {det.ms}ms lang={lang}")
        _log(f"policy_check: {d.action} ({STAGE}) {head} routed={d.target} {summary}"
             + (f" redacted={redacted}" if redacted else "")
             + (f" dropped_params={','.join(dropped)}" if dropped else ""))

        await self.audit.insert(
            call_id=call_id, team=team, key_alias=alias, requested=requested, routed=d.target,
            outcome="blocked" if d.action == "block" else "pending", counts=counts, level=d.level,
            reason=d.reason, action=d.action, rule=d.rule, detector=det.status, language=lang, ms=det.ms,
            redacted=redacted, stream=stream, policy_version=POLICY.version)

        if d.action == "block":
            raise HTTPException(status_code=403, detail={
                "error": f"policy_blocked: rule {d.rule} — {d.note}. "
                         f"Request contains data that may not be sent to {requested} (level {d.level}, reason {d.reason})."})

        _state[call_id] = {"t": time.monotonic(), "mapping": mapping, "headers": {
            "x-governance-action": d.action, "x-governance-rule": d.rule, "x-governance-level": d.level,
            "x-governance-reason": d.reason, "x-governance-routed-model": d.target,
            "x-governance-pii": pii_policy.counts_text(counts)}}
        return data

    # ---------- 回答回来 ----------
    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        st = _state.get(data.get("litellm_call_id", ""))
        if st and st["mapping"] and not data.get("stream"):
            pii_redact.restore_response(response, st["mapping"])
        return response

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data: dict):
        st = _state.get(request_data.get("litellm_call_id", ""))
        if not (st and st["mapping"]):
            async for item in response:
                yield item
            return
        # 需要还原：先收完整段上游流（占位符可能被拆在两个块里），还原后按原样逐块重放
        chunks = [item async for item in response]
        for item in pii_redact.restore_chunks(chunks, st["mapping"]):
            yield item

    async def async_post_call_response_headers_hook(self, data: dict, user_api_key_dict, response,
                                                    request_headers=None, litellm_call_info=None):
        st = _state.get(data.get("litellm_call_id", ""))
        return dict(st["headers"]) if st else None

    # ---------- 写日志之前 / 之后 ----------
    async def async_logging_hook(self, kwargs: dict, result, call_type: str):
        call_id = kwargs.get("litellm_call_id")
        if call_id:
            for obj in (result, kwargs.get("async_complete_streaming_response")):
                _unique_id(obj, call_id)
        return kwargs, result

    @staticmethod
    def _served(kwargs: dict) -> str | None:
        slo = kwargs.get("standard_logging_object") or {}
        group = slo.get("model_group") if isinstance(slo, dict) else None
        if not group:
            md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            group = md.get("model_group")
        return group

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        if POLICY and POLICY.enforcement != "off" and kwargs.get("litellm_call_id"):
            await self.audit.finish(kwargs["litellm_call_id"], self._served(kwargs), "success")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        # 降级时第一个模型失败也会触发这里；之后成功会再把 outcome 改成 success
        if POLICY and POLICY.enforcement != "off" and kwargs.get("litellm_call_id"):
            await self.audit.finish(kwargs["litellm_call_id"], None, "failure")


proxy_handler_instance = GovernancePlugin()
