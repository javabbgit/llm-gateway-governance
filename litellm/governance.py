"""治理插件（P3 版：仍是占位，P4 在这里实现 PII 检测与驻留路由）。

挂在 LiteLLM 的两个钩子上：
- async_pre_call_hook：每个请求在路由之前经过这里。打一行元数据日志后放行；
  对 LOCKED_PARAMS 里的逻辑名，丢弃应用自带的受控参数，让 config.yaml 的设定生效（总纲决策 20）。
- async_logging_hook：写日志之前运行。把 Ollama 的短响应 ID 换成唯一 ID，避免费用日志撞号丢行。

日志只记元数据（请求 ID、逻辑模型名、key 别名、团队、调用类型），绝不记录请求内容。
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

STAGE = "stub"

# 网关统一管控的模型参数：对这些逻辑名，丢弃应用自带的同名参数。
# 只能“丢弃”不能“改写”：改写会随降级带到下一个模型。
LOCKED_PARAMS = {
    # qwen3 在 config.yaml 固定 reasoning_effort: none（P1：4.8s → 0.2s）
    "chat-default": ("reasoning_effort", "reasoning"),
    # Haiku 5.5：思考强度由 config.yaml 固定为 low，控制费用；
    # 它不接受采样参数（temperature≠1、top_p、top_k 都返回 400），应用传了也丢弃，而不是让请求失败。
    "chat-cloud": ("reasoning_effort", "reasoning", "thinking", "temperature", "top_p", "top_k"),
}

# Ollama 的 OpenAI 兼容接口返回 chatcmpl-<0..999 的随机数>。LiteLLM 费用日志以响应 ID 作主键、
# 批量写入时跳过重复行，所以本地模型的请求会因撞号被静默丢弃（约 40 次请求就有一半概率撞上）。
SHORT_ID = re.compile(r"^chatcmpl-\d{1,6}$")


def _unique_id(obj, call_id: str) -> bool:
    rid = getattr(obj, "id", None)
    if isinstance(rid, str) and SHORT_ID.match(rid):
        obj.id = f"chatcmpl-{call_id}"
        return True
    return False


class GovernancePlugin(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        call_id = data.get("litellm_call_id", "-")
        model = data.get("model", "-")
        alias = getattr(user_api_key_dict, "key_alias", None) or "-"
        team = getattr(user_api_key_dict, "team_alias", None) or "-"
        dropped = [p for p in LOCKED_PARAMS.get(model, ()) if data.pop(p, None) is not None]
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # model 此时仍是应用请求的逻辑名（如 chat-default），说明钩子运行在路由之前
        print(
            f"{ts} policy_check: pass ({STAGE}) call_id={call_id} model={model} "
            f"key_alias={alias} team={team} call_type={call_type}"
            + (f" dropped_params={','.join(dropped)}" if dropped else ""),
            file=sys.stderr,
            flush=True,
        )
        return data

    async def async_logging_hook(self, kwargs: dict, result, call_type: str):
        # LiteLLM 先依次运行所有回调的 logging hook，再运行写费用日志的回调，所以这里改的 ID 一定先生效。
        # 流式请求的费用日志用 async_complete_streaming_response，两处都处理。云端供应商的 ID 不动。
        call_id = kwargs.get("litellm_call_id")
        if call_id:
            for obj in (result, kwargs.get("async_complete_streaming_response")):
                _unique_id(obj, call_id)
        return kwargs, result


proxy_handler_instance = GovernancePlugin()
