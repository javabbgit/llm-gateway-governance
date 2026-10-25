"""脱敏与还原（P4d）：把命中的片段换成 [PERSON_1] 这样的占位符，回答回来后再换回原文。

占位符映射只存在插件进程的内存里（按 litellm_call_id），绝不写入日志、审计表或请求 metadata
（metadata 会进 LiteLLM 的费用日志）。纯函数，不碰网络。
"""
from __future__ import annotations

import copy
import re


def redact(messages: list, segments: list, findings: list) -> tuple[list, dict]:
    """返回 (脱敏后的 messages 副本, {占位符名: 原文})。同一原文在所有消息里用同一个占位符。"""
    by_seg: dict[int, list] = {}
    for f in findings:
        by_seg.setdefault(f.seg, []).append(f)
    names: dict[tuple[str, str], str] = {}     # (实体, 原文) → 占位符名
    counters: dict[str, int] = {}
    mapping: dict[str, str] = {}
    out = copy.deepcopy(messages)
    for idx, seg in enumerate(segments):
        hits = sorted(by_seg.get(idx, []), key=lambda f: f.start)
        if not hits:
            continue
        text, pieces, pos = seg.text, [], 0
        for f in hits:
            if f.start < pos:          # 已去重，这里只是保险
                continue
            value = text[f.start:f.end]
            key = (f.entity, value)
            if key not in names:
                counters[f.entity] = counters.get(f.entity, 0) + 1
                names[key] = f"{f.entity}_{counters[f.entity]}"
                mapping[names[key]] = value
            pieces += [text[pos:f.start], f"[{names[key]}]"]
            pos = f.end
        pieces.append(text[pos:])
        _write_back(out, seg, "".join(pieces))
    return out, mapping


def _write_back(messages: list, seg, text: str) -> None:
    m = messages[seg.msg]
    if seg.part is None:
        m["content"] = text
    elif seg.part >= 0:
        m["content"][seg.part]["text"] = text
    else:
        m["tool_calls"][-1 - seg.part]["function"]["arguments"] = text


def _pattern(mapping: dict):
    if not mapping:
        return None
    alts = "|".join(re.escape(n) for n in sorted(mapping, key=len, reverse=True))
    # 认 [PERSON_1]，也认模型去掉方括号后的 PERSON_1；\b 防止 PERSON_1 吃掉 PERSON_10 的前缀
    return re.compile(r"\[?\b(" + alts + r")\b\]?")


def restore(text, mapping: dict):
    if not isinstance(text, str) or not mapping:
        return text
    pat = _pattern(mapping)
    return pat.sub(lambda m: mapping[m.group(1)], text)


RESTORE_FIELDS = ("content", "reasoning_content")


def restore_response(response, mapping: dict) -> int:
    """非流式回答：就地还原每个 choice 的 content 与 reasoning_content，返回改动的字段数。"""
    changed = 0
    for ch in getattr(response, "choices", None) or []:
        msg = getattr(ch, "message", None)
        for field in RESTORE_FIELDS:
            old = getattr(msg, field, None)
            new = restore(old, mapping)
            if new != old:
                setattr(msg, field, new)
                changed += 1
    return changed


def restore_chunks(chunks: list, mapping: dict) -> list:
    """流式回答（决策 23）：整段缓存后还原。每个 choice 的完整文本放进它的第一个内容块，其余内容块置空；
    块的数量、顺序、id、finish_reason 与 usage 都不变，客户端看到的仍是标准 SSE 流。"""
    for field in RESTORE_FIELDS:
        full: dict[int, list] = {}
        first: dict[int, object] = {}
        for c in chunks:
            for ch in getattr(c, "choices", None) or []:
                d = getattr(ch, "delta", None)
                v = getattr(d, field, None)
                if isinstance(v, str) and v:
                    idx = getattr(ch, "index", 0) or 0
                    full.setdefault(idx, []).append(v)
                    first.setdefault(idx, d)
                    setattr(d, field, "")
        for idx, parts in full.items():
            setattr(first[idx], field, restore("".join(parts), mapping))
    return chunks
