"""治理插件（P2 占位版）。

挂在 LiteLLM 的请求前置钩子 async_pre_call_hook 上：每个请求在路由之前经过这里。
P2 只做两件事：打一行日志后放行；对 LOCKED_PARAMS 里的逻辑名丢弃应用自带的受控参数。
P4 在这里实现 PII 检测、驻留决策、阻断/改道/脱敏和审计。

日志只记元数据（请求 ID、逻辑模型名、key 别名、调用类型），绝不记录请求内容。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

STAGE = "stub"

# 网关统一管控的模型参数：对这些逻辑名，丢弃应用自带的同名参数，让 config.yaml 里的设定生效。
# 例：chat-default 在 config.yaml 里固定 reasoning_effort: none；应用即使传 high 也会被丢弃。
# 只能“丢弃”不能“改写”：改写会随降级带到 chat-fallback（llama3.2 不支持思考，可能被 Ollama 拒绝）。
LOCKED_PARAMS = {
    "chat-default": ("reasoning_effort", "reasoning"),
}


class GovernancePlugin(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        call_id = data.get("litellm_call_id", "-")
        model = data.get("model", "-")
        alias = getattr(user_api_key_dict, "key_alias", None) or "-"
        dropped = [p for p in LOCKED_PARAMS.get(model, ()) if data.pop(p, None) is not None]
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # model 此时仍是应用请求的逻辑名（如 chat-default），说明钩子运行在路由之前
        print(
            f"{ts} policy_check: pass ({STAGE}) call_id={call_id} model={model} "
            f"key_alias={alias} call_type={call_type}"
            + (f" dropped_params={','.join(dropped)}" if dropped else ""),
            file=sys.stderr,
            flush=True,
        )
        return data


proxy_handler_instance = GovernancePlugin()
