-- P4 审计表：与 LiteLLM 同一个 Postgres，独立 schema governance（LiteLLM 的迁移只管 public，不会动这里）。
-- 由 python3 scripts/p4check.py audit-init 执行，可重复运行。
-- 绝不存原文：PII 只记类型与数量，连哈希也不存（9 位 SIN 只有 10 亿种可能，哈希可以穷举反查）。
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.pii_audit (
  id              bigserial PRIMARY KEY,
  ts              timestamptz NOT NULL DEFAULT now(),
  call_id         text NOT NULL UNIQUE,        -- = LiteLLM_SpendLogs.litellm_call_id，用来关联费用日志
  team            text,                        -- 团队别名
  key_alias       text,
  requested_model text NOT NULL,               -- 应用请求的逻辑名
  routed_model    text NOT NULL,               -- 策略决定的逻辑名（改道后为 chat-default）
  served_model    text,                        -- 实际返回结果的逻辑名（可能因降级变成 chat-fallback）；阻断时为空
  outcome         text NOT NULL DEFAULT 'pending',  -- pending / success / failure / blocked
  pii_counts      jsonb NOT NULL DEFAULT '{}'::jsonb, -- 例如 {"PERSON": 1, "CA_SIN": 1}
  level           text NOT NULL,               -- none / general / high
  reason          text NOT NULL,               -- none / detected / detector_unavailable / language_unsupported
  action          text NOT NULL,               -- pass / redact / reroute / block
  rule            text NOT NULL,               -- R1–R10，见 governance/policy.toml
  detector_status text NOT NULL,               -- ok / timeout / error / unavailable / skipped
  language        text NOT NULL,               -- en / script / fr / es
  detect_ms       integer,
  redacted        integer NOT NULL DEFAULT 0,  -- 替换成占位符的片段数
  stream          boolean NOT NULL DEFAULT false,
  policy_version  text NOT NULL,
  -- 只允许“类型 → 整数”，挡住任何把原文写进 pii_counts 的代码错误
  CONSTRAINT pii_counts_types_only CHECK (jsonb_typeof(pii_counts) = 'object'
    AND NOT jsonb_path_exists(pii_counts, '$.* ? (@.type() != "number")'))
);
CREATE INDEX IF NOT EXISTS pii_audit_ts ON governance.pii_audit (ts);
COMMENT ON TABLE governance.pii_audit IS 'P4 PII 驻留路由审计：只有类型与数量，不存原文';
