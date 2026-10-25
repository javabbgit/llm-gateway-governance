"""P5 离线单元测试：审计查询的输入校验与输出、演示脚本的屏幕脱敏与离线判定、文档链接解析。不碰网络与容器。"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import audit  # noqa: E402
import demo  # noqa: E402
import p5check  # noqa: E402

ROW = {"ts": "2026-10-25T17:31:44.517492+00:00", "call_id": "11111111-1111-1111-1111-111111111111", "team": "marketing",
       "key_alias": "mkt-copywriter", "requested_model": "chat-deepseek", "routed_model": "chat-default",
       "served_model": "chat-default", "outcome": "success", "pii_counts": {"CA_SIN": 1}, "level": "high",
       "reason": "detected", "action": "reroute", "rule": "R9", "detector_status": "ok", "language": "en",
       "detect_ms": 11, "redacted": 0, "stream": False, "policy_version": "2026-10-p4", "spend": 0.0000123}


class AuditQuery(unittest.TestCase):
    def test_since_accepts_units(self):
        self.assertEqual(audit.since_sql("15m"), "interval '15 minutes'")
        self.assertEqual(audit.since_sql("2h"), "interval '2 hours'")
        self.assertEqual(audit.since_sql("7d"), "interval '7 days'")

    def test_since_rejects_injection(self):
        for bad in ("1h;drop table x", "5x", "1 hour", "", "-1h"):
            with self.assertRaises(audit.QueryError):
                audit.since_sql(bad)

    def test_filters_are_validated(self):
        with self.assertRaises(audit.QueryError):
            audit.where_clause(action="delete")
        with self.assertRaises(audit.QueryError):
            audit.where_clause(team="x' or '1'='1")
        w = audit.where_clause(ids=["ABCDEF12-0000-0000-0000-000000000000'; --"])
        self.assertNotIn("'; --", w)
        self.assertIn("abcdef12-0000-0000-0000-000000000000", w)

    def test_rows_render_types_only(self):
        out = audit.render_rows([ROW], wide=True)
        self.assertIn("chat-deepseek → chat-default", out)
        self.assertIn("CA_SIN:1", out)
        self.assertIn("R9", out)

    def test_pending_and_blocked(self):
        self.assertEqual(audit.route_text({**ROW, "served_model": None, "outcome": "pending"}), "chat-deepseek → …")
        self.assertEqual(audit.route_text({**ROW, "outcome": "blocked", "served_model": None}), "chat-deepseek → (blocked)")
        self.assertEqual(audit.money(None), "…")

    def test_summary_render(self):
        s = {"total": 2, "first": ROW["ts"], "last": ROW["ts"], "by_action": {"reroute": 1, "pass": 1},
             "by_rule": {"R9": 1, "R1": 1}, "by_reason": {"detected": 1, "none": 1}, "by_outcome": {"success": 2},
             "by_detector": {"ok": 2}, "by_team": [{"team": "marketing", "action": "reroute", "n": 1}],
             "pii_types": {"CA_SIN": 1}, "detect_ms": {"p50": 9, "p95": 11, "max": 11}, "spend": 0.00001}
        out = audit.render_summary(s)
        for want in ("By action", "reroute", "CA_SIN", "p50 9 ms"):
            self.assertIn(want, out)
        self.assertEqual(audit.render_summary({"total": 0}), "(no audit rows match)")


class Demo(unittest.TestCase):
    def test_clean_masks_fake_sin(self):
        self.assertNotIn(demo.FAKE_SIN, demo.clean(f"SIN {demo.FAKE_SIN} and {demo.FAKE_SIN.replace(' ', '')}"))

    def test_forced_offline(self):
        os.environ["DEMO_OFFLINE"] = "1"
        try:
            ok, reason = demo.cloud_status(False)
        finally:
            os.environ.pop("DEMO_OFFLINE")
        self.assertFalse(ok)
        self.assertIn("offline", reason)
        self.assertEqual(demo.cloud_status(True), (False, "offline mode forced (--offline)"))

    def test_nine_scenes_one_cloud(self):
        self.assertEqual([s.num for s in demo.SCENES], list(range(1, 10)))
        self.assertEqual([s.num for s in demo.SCENES if s.cloud], [8])
        for s in demo.SCENES:
            self.assertTrue(hasattr(demo.Demo, f"s{s.num}"))


class Docs(unittest.TestCase):
    def test_links_skip_urls_and_anchors(self):
        md = "[a](docs/x.md) [b](https://example.com) [c](#top) [d](adr/README.md#index) [e](mailto:x@y)"
        self.assertEqual(p5check._links(md), ["docs/x.md", "adr/README.md"])


if __name__ == "__main__":
    unittest.main()
