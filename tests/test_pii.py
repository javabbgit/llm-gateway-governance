"""P4b 离线单元测试：处置矩阵每一格、故障与语言兜底、白名单阻断、策略校验、语言判定、Luhn、脱敏与还原。

只用标准库，不碰网络与容器。运行：python3 scripts/p4check.py unit（或 python3 -m unittest discover -s tests -v）
"""
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "litellm"))

import pii_detect  # noqa: E402
import pii_policy  # noqa: E402
import pii_redact  # noqa: E402

POLICY_FILE = ROOT / "governance" / "policy.toml"
CORPUS = ROOT / "tests" / "pii_corpus.jsonl"


def policy(mode: str = "full") -> pii_policy.Policy:
    raw = pii_policy.tomllib.loads(POLICY_FILE.read_text(encoding="utf-8"))
    raw["enforcement"] = mode
    return pii_policy.parse_policy(raw)


JUR = {"local": "local", "approved": "US", "unapproved": "CN"}
COUNTS = {"none": {}, "general": {"PERSON": 1, "EMAIL_ADDRESS": 2}, "high": {"PERSON": 1, "CA_SIN": 1}}
# 总纲第 8 节的处置矩阵：(类别, 级别) → (规则, 动作)
EXPECTED = {
    ("local", "none"): ("R1", "pass"), ("local", "general"): ("R2", "pass"), ("local", "high"): ("R3", "pass"),
    ("approved", "none"): ("R4", "pass"), ("approved", "general"): ("R5", "redact"), ("approved", "high"): ("R6", "reroute"),
    ("unapproved", "none"): ("R7", "pass"), ("unapproved", "general"): ("R8", "reroute"), ("unapproved", "high"): ("R9", "reroute"),
}


def decide(p, cls, level, *, detector_ok=True, language_ok=True, allowed=None, requested="chat-x"):
    return pii_policy.decide(p, requested=requested, jurisdiction=JUR[cls], counts=COUNTS[level],
                             detector_ok=detector_ok, language_ok=language_ok, allowed_models=allowed)


class MatrixTest(unittest.TestCase):
    def test_every_cell(self):
        p = policy()
        for (cls, level), (rule, action) in EXPECTED.items():
            with self.subTest(cell=f"{cls}/{level}"):
                d = decide(p, cls, level)
                self.assertEqual((d.rule, d.action, d.level, d.cls), (rule, action, level, cls))
                self.assertEqual(d.target, "chat-default" if action == "reroute" else "chat-x")

    def test_detector_failure_counts_as_high(self):
        p = policy()
        for cls in JUR:
            d = decide(p, cls, "none", detector_ok=False)
            self.assertEqual((d.level, d.reason), ("high", pii_policy.REASON_DETECTOR))
            self.assertEqual(d.action, "pass" if cls == "local" else "reroute")

    def test_non_english_counts_as_high(self):
        p = policy()
        for cls in JUR:
            d = decide(p, cls, "none", language_ok=False)
            self.assertEqual((d.level, d.reason), ("high", pii_policy.REASON_LANGUAGE))
            self.assertEqual(d.action, "pass" if cls == "local" else "reroute")

    def test_detector_failure_wins_over_language(self):
        d = decide(policy(), "unapproved", "none", detector_ok=False, language_ok=False)
        self.assertEqual(d.reason, pii_policy.REASON_DETECTOR)

    def test_reroute_target_not_allowed_blocks(self):
        p = policy()
        d = decide(p, "unapproved", "high", allowed={"chat-cloud", "chat-deepseek"})
        self.assertEqual((d.action, d.rule), ("block", "R10"))
        d = decide(p, "unapproved", "high", allowed={"chat-default", "chat-deepseek"})
        self.assertEqual(d.action, "reroute")
        d = decide(p, "unapproved", "none", allowed={"chat-deepseek"})   # 不需要改道时白名单不影响
        self.assertEqual(d.action, "pass")

    def test_route_mode_turns_redact_into_reroute(self):
        d = decide(policy("route"), "approved", "general")
        self.assertEqual((d.action, d.rule, d.target), ("reroute", "R5", "chat-default"))

    def test_unknown_or_missing_jurisdiction_is_unapproved(self):
        p = policy()
        for j in (None, "", "EU"):
            d = pii_policy.decide(p, requested="m", jurisdiction=j, counts={"PERSON": 1}, detector_ok=True,
                                  language_ok=True, allowed_models=None)
            self.assertEqual((d.cls, d.action), ("unapproved", "reroute"))

    def test_unknown_entities_are_ignored(self):
        p = policy()
        self.assertEqual(pii_policy.level_of(p, {"LOCATION": 3, "DATE_TIME": 1}), "none")
        self.assertEqual(pii_policy.level_of(p, {"PERSON": 0}), "none")

    def test_counts_text_has_no_values(self):
        self.assertEqual(pii_policy.counts_text({"PERSON": 2, "CA_SIN": 1}), "CA_SIN:1,PERSON:2")
        self.assertEqual(pii_policy.counts_text({}), "-")


class PolicyFileTest(unittest.TestCase):
    def raw(self):
        return pii_policy.tomllib.loads(POLICY_FILE.read_text(encoding="utf-8"))

    def test_file_loads(self):
        p = pii_policy.load_policy(POLICY_FILE)
        self.assertIn(p.enforcement, pii_policy.MODES)
        self.assertEqual(len(p.matrix), 9)

    def test_missing_cell_rejected(self):
        raw = self.raw()
        raw["rule"] = raw["rule"][:-1]
        with self.assertRaises(pii_policy.PolicyError):
            pii_policy.parse_policy(raw)

    def test_local_must_pass(self):
        raw = self.raw()
        raw["rule"][0]["action"] = "reroute"
        with self.assertRaises(pii_policy.PolicyError):
            pii_policy.parse_policy(raw)

    def test_entity_in_two_levels_rejected(self):
        raw = self.raw()
        raw["levels"]["general"].append("CA_SIN")
        with self.assertRaises(pii_policy.PolicyError):
            pii_policy.parse_policy(raw)

    def test_bad_mode_rejected(self):
        raw = self.raw()
        raw["enforcement"] = "audit-only"
        with self.assertRaises(pii_policy.PolicyError):
            pii_policy.parse_policy(raw)

    def test_unreadable_file(self):
        with self.assertRaises(pii_policy.PolicyError):
            pii_policy.load_policy(ROOT / "governance" / "no-such-policy.toml")


class LanguageTest(unittest.TestCase):
    def test_corpus_languages(self):
        expect = {"en": "en", "zh": "script", "ru": "script", "fr": "fr", "es": "es"}
        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            msgs = case.get("messages") or [{"role": "user", "content": case["text"]}]
            texts = [s.text for s in pii_detect.extract_segments(msgs)]
            with self.subTest(case=case["id"]):
                self.assertEqual(pii_detect.language_status(texts, 3), expect[case["lang"]])

    def test_one_foreign_message_is_enough(self):
        texts = ["You are a helpful assistant for the mortgage team and you answer in English.",
                 "Bonjour, je voudrais avoir le dossier de mon client avant vendredi."]
        self.assertEqual(pii_detect.language_status(texts, 3), "fr")

    def test_accented_names_stay_english(self):
        self.assertEqual(pii_detect.language_status(["Please call José Martínez and Zoë Brontë today."], 3), "en")


class ValidateTest(unittest.TestCase):
    def test_sin(self):
        self.assertTrue(pii_detect.validate("CA_SIN", "193 456 787"))
        self.assertTrue(pii_detect.validate("CA_SIN", "130692544"))
        self.assertFalse(pii_detect.validate("CA_SIN", "123 456 789"))   # Luhn 不通过
        self.assertFalse(pii_detect.validate("CA_SIN", "046 454 286"))   # 0 开头从未发放
        self.assertTrue(pii_detect.validate("PERSON", "anything"))

    def test_dedupe_keeps_highest_score(self):
        F = pii_detect.Finding
        out = pii_detect._dedupe([F(0, "CA_BANK_ACCOUNT", 10, 19, 0.55), F(0, "CA_SIN", 10, 19, 0.85),
                                  F(1, "PERSON", 0, 5, 0.85)])
        self.assertEqual([(f.seg, f.entity) for f in out], [(0, "CA_SIN"), (1, "PERSON")])


class SegmentTest(unittest.TestCase):
    def test_all_text_places(self):
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": [{"type": "text", "text": "part"}, {"type": "image_url", "image_url": {}}]},
                {"role": "assistant", "content": None,
                 "tool_calls": [{"function": {"name": "f", "arguments": "{\"name\": \"Emily\"}"}}]}]
        segs = pii_detect.extract_segments(msgs)
        self.assertEqual([(s.msg, s.part) for s in segs], [(0, None), (1, 0), (2, -1)])


class RedactTest(unittest.TestCase):
    F = pii_detect.Finding

    def setUp(self):
        self.msgs = [{"role": "assistant", "content": "Borrower is Emily Tremblay."},
                     {"role": "user", "content": [{"type": "text", "text": "Email Emily Tremblay at e.t@example.com"}]}]
        self.segs = pii_detect.extract_segments(self.msgs)
        self.findings = [self.F(0, "PERSON", 12, 26, 0.85), self.F(1, "PERSON", 6, 20, 0.85),
                         self.F(1, "EMAIL_ADDRESS", 24, 39, 1.0)]

    def test_redact_and_restore(self):
        original = copy.deepcopy(self.msgs)
        out, mapping = pii_redact.redact(self.msgs, self.segs, self.findings)
        self.assertEqual(self.msgs, original)                          # 不改动传入的对象
        self.assertEqual(out[0]["content"], "Borrower is [PERSON_1].")
        self.assertEqual(out[1]["content"][0]["text"], "Email [PERSON_1] at [EMAIL_ADDRESS_1]")
        self.assertEqual(mapping, {"PERSON_1": "Emily Tremblay", "EMAIL_ADDRESS_1": "e.t@example.com"})
        flat = json.dumps(out)
        self.assertNotIn("Emily", flat)
        self.assertNotIn("example.com", flat)
        self.assertEqual(pii_redact.restore("Hi [PERSON_1], PERSON_1 and [EMAIL_ADDRESS_1]", mapping),
                         "Hi Emily Tremblay, Emily Tremblay and e.t@example.com")

    def test_restore_does_not_eat_longer_names(self):
        mapping = {f"PERSON_{i}": f"N{i}" for i in range(1, 12)}
        self.assertEqual(pii_redact.restore("[PERSON_1] [PERSON_10] PERSON_11", mapping), "N1 N10 N11")

    def test_restore_response(self):
        resp = NS(choices=[NS(message=NS(content="Dear [PERSON_1]", reasoning_content=None))])
        self.assertEqual(pii_redact.restore_response(resp, {"PERSON_1": "Emily"}), 1)
        self.assertEqual(resp.choices[0].message.content, "Dear Emily")

    def test_restore_chunks_with_split_placeholder(self):
        pieces = ["Dear [PER", "SON_1], your rate", " is fixed.", None]
        chunks = [NS(choices=[NS(index=0, delta=NS(content=p))]) for p in pieces]
        out = pii_redact.restore_chunks(chunks, {"PERSON_1": "Emily Tremblay"})
        self.assertEqual(len(out), 4)                                   # 块数不变
        texts = [c.choices[0].delta.content for c in out]
        self.assertEqual(texts[0], "Dear Emily Tremblay, your rate is fixed.")
        self.assertEqual(texts[1:], ["", "", None])


if __name__ == "__main__":
    unittest.main(verbosity=2)
