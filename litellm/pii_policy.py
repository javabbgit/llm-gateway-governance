"""PII 驻留策略：读取 governance/policy.toml，按处置矩阵做决定（P4b）。

纯函数，不碰网络、不读环境变量以外的任何东西，只用标准库；宿主机上的单元测试和容器里的插件用同一份代码。
输入只有“类型 → 数量”，从不接触原文。
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

LEVELS = ("none", "general", "high")
CLASSES = ("local", "approved", "unapproved")
ACTIONS = ("pass", "redact", "reroute")
MODES = ("off", "route", "full")

# 级别的原因（写进审计表 reason 列）
REASON_NONE = "none"                       # 没检测到 PII
REASON_DETECTED = "detected"               # 检测到 PII
REASON_DETECTOR = "detector_unavailable"   # Presidio 超时、出错或不可达（fail-closed）
REASON_LANGUAGE = "language_unsupported"   # 文本非英文，无法检测（决策 25、26）


class PolicyError(ValueError):
    """策略文件读不出或自相矛盾。插件遇到它时阻断所有请求。"""


@dataclass(frozen=True)
class Rule:
    id: str
    cls: str
    level: str
    action: str


@dataclass(frozen=True)
class Policy:
    version: str
    enforcement: str
    reroute_target: str
    block_rule: str
    jurisdictions: dict
    default_class: str
    entity_level: dict          # 实体 → 级别
    matrix: dict                # (类别, 级别) → Rule
    timeout_seconds: float
    score_threshold: float
    language: str
    allow_list: tuple
    min_hits: int

    @property
    def entities(self) -> list[str]:
        return sorted(self.entity_level)


@dataclass(frozen=True)
class Decision:
    action: str                 # pass / redact / reroute / block
    rule: str                   # R1–R10
    level: str                  # none / general / high（故障与非英文时为 high）
    reason: str                 # 见上面 REASON_*
    cls: str                    # 请求目标的类别
    target: str                 # 决策后的逻辑名（改道时为 reroute_target）
    note: str = ""              # 给日志与错误信息的一句话说明，不含任何原文


def load_policy(path: str | Path) -> Policy:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise PolicyError(f"读不出策略文件 {path}：{e}") from e
    return parse_policy(raw)


def parse_policy(raw: dict) -> Policy:
    def need(d: dict, key: str, where: str):
        if key not in d:
            raise PolicyError(f"策略缺少 {where}{key}")
        return d[key]

    enforcement = need(raw, "enforcement", "")
    if enforcement not in MODES:
        raise PolicyError(f"enforcement 只能是 {MODES}，实际 {enforcement!r}")

    jur = dict(need(raw, "jurisdictions", ""))
    default_class = jur.pop("default_class", "unapproved")
    for k, v in list(jur.items()) + [("default_class", default_class)]:
        if v not in CLASSES:
            raise PolicyError(f"jurisdictions.{k} 的类别只能是 {CLASSES}，实际 {v!r}")

    entity_level: dict[str, str] = {}
    for level, names in need(raw, "levels", "").items():
        if level not in ("general", "high"):
            raise PolicyError(f"levels 只能有 general 和 high，实际 {level!r}")
        for n in names:
            if n in entity_level:
                raise PolicyError(f"实体 {n} 同时出现在 {entity_level[n]} 和 {level}")
            entity_level[n] = level

    matrix: dict[tuple[str, str], Rule] = {}
    ids = set()
    for r in need(raw, "rule", ""):
        rule = Rule(need(r, "id", "rule."), need(r, "class", "rule."), need(r, "level", "rule."), need(r, "action", "rule."))
        if rule.cls not in CLASSES or rule.level not in LEVELS or rule.action not in ACTIONS:
            raise PolicyError(f"规则 {rule.id} 的类别、级别或动作不合法")
        if (rule.cls, rule.level) in matrix:
            raise PolicyError(f"规则 {rule.id} 与 {matrix[(rule.cls, rule.level)].id} 重复覆盖同一格")
        if rule.id in ids:
            raise PolicyError(f"规则编号 {rule.id} 重复")
        if rule.cls == "local" and rule.action != "pass":
            raise PolicyError(f"规则 {rule.id}：本地模型只能放行")
        ids.add(rule.id)
        matrix[(rule.cls, rule.level)] = rule
    missing = [(c, lv) for c in CLASSES for lv in LEVELS if (c, lv) not in matrix]
    if missing:
        raise PolicyError(f"处置矩阵缺格：{missing}")

    block_rule = need(raw, "block_rule", "")
    if block_rule in ids:
        raise PolicyError(f"block_rule {block_rule} 与矩阵规则编号重复")

    det = need(raw, "detector", "")
    lang = raw.get("language", {})
    return Policy(
        version=str(need(raw, "version", "")),
        enforcement=enforcement,
        reroute_target=need(raw, "reroute_target", ""),
        block_rule=block_rule,
        jurisdictions=jur,
        default_class=default_class,
        entity_level=entity_level,
        matrix=matrix,
        timeout_seconds=float(det.get("timeout_seconds", 3.0)),
        score_threshold=float(det.get("score_threshold", 0.5)),
        language=str(det.get("language", "en")),
        allow_list=tuple(det.get("allow_list", ())),
        min_hits=int(lang.get("min_hits", 3)),
    )


def class_of(policy: Policy, jurisdiction: str | None) -> str:
    """未标注或未列出的 jurisdiction 按 default_class（未批准）处理。"""
    if not jurisdiction:
        return policy.default_class
    return policy.jurisdictions.get(jurisdiction, policy.default_class)


def level_of(policy: Policy, counts: dict) -> str:
    """counts：实体类型 → 数量。策略里没有的实体忽略。"""
    levels = {policy.entity_level.get(e) for e, n in counts.items() if n > 0}
    if "high" in levels:
        return "high"
    if "general" in levels:
        return "general"
    return "none"


def decide(
    policy: Policy,
    *,
    requested: str,
    jurisdiction: str | None,
    counts: dict,
    detector_ok: bool,
    language_ok: bool,
    allowed_models: set | None,
) -> Decision:
    """处置矩阵（总纲第 8 节）。allowed_models 为 None 表示调用方可用全部模型。

    1. 级别：检测器故障或非英文一律按 high；否则取检测到的最高级别。
    2. 查 (类别, 级别) 那一格得到动作。
    3. 改道目标不在白名单里 → 阻断（钩子里改写模型会绕过 LiteLLM 的白名单，必须自己查）。
    4. route 模式还没有脱敏，需要脱敏的格子先按改道处理。
    """
    cls = class_of(policy, jurisdiction)
    if not detector_ok:
        level, reason = "high", REASON_DETECTOR
    elif not language_ok:
        level, reason = "high", REASON_LANGUAGE
    else:
        level = level_of(policy, counts)
        reason = REASON_DETECTED if level != "none" else REASON_NONE

    rule = policy.matrix[(cls, level)]
    action, note = rule.action, ""
    if action == "redact" and policy.enforcement == "route":
        action, note = "reroute", "route 模式：脱敏尚未启用，按改道处理"

    if action == "reroute":
        target = policy.reroute_target
        if allowed_models is not None and target not in allowed_models:
            return Decision("block", policy.block_rule, level, reason, cls, requested,
                            f"改道目标 {target} 不在调用方的模型白名单里")
        return Decision("reroute", rule.id, level, reason, cls, target, note)
    return Decision(action, rule.id, level, reason, cls, requested, note)


def counts_text(counts: dict) -> str:
    """日志与响应头用：PERSON:1,CA_SIN:1（只有类型与数量）。"""
    return ",".join(f"{k}:{v}" for k, v in sorted(counts.items()) if v) or "-"
