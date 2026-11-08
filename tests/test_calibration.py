import asyncio
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from luxury_advisor.cli import read_cases
from luxury_advisor.models import CandidateSet
from luxury_advisor.quality import build_reply_brief, review_candidates
from luxury_advisor.service import draft, load_context
from test_quality import GOOD, RecordingProvider, output

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.calibration = json.loads((DATA_DIR / "reply_calibration.json").read_text())
        self.cases = {case.case_id: case.input for case in read_cases(DATA_DIR)}

    def context(self, case="D001"):
        context = load_context(DATA_DIR, self.cases[case])
        context["reply_brief"] = build_reply_brief(context, DATA_DIR)
        return context




    def test_negative_frames_and_client_guesses_trigger_specific_feedback(self):
        candidates = CandidateSet.model_validate_json(output(
            "陈女士，我没有折扣权限，您不用着急。",
            "陈女士，以您的职业审美，这款一定适合您。",
            "陈女士，您最近一定很忙，应该喜欢简短问候。",
        ))
        findings = review_candidates(candidates, self.context())["findings"]
        self.assertEqual([f["candidate_index"] for f in findings if f["code"] == "negative_framing"], [1])
        self.assertEqual([f["candidate_index"] for f in findings if f["code"] == "client_inference"], [2, 3])

    def test_lexical_bu_and_wishes_or_conditional_choices_are_not_blanket_banned(self):
        candidates = CandidateSet.model_validate_json(output(
            "陈女士，愿新一岁，有更多不凡的时刻。",
            "陈女士，不同的日子，各有值得珍藏的心意。",
            "陈女士，如果您希望了解，可以再介绍细节。",
        ))
        review = review_candidates(candidates, self.context())
        self.assertEqual(review["status"], "no_rule_flags")
        self.assertIsNone(review["semantic_score"])

    def test_positive_business_conditions_are_allowed_without_fabricating_a_concession(self):
        candidates = CandidateSet.model_validate_json(output(
            "唐女士，这款标价16,800元，本次按目录标价提供。",
            "唐女士，折光小号手提包标价16,800元，按这一价格提供，您可以结合价差比较。",
            "唐女士，本次价格为目录标价16,800元，供您作选择时参考。",
        ))
        review = review_candidates(candidates, self.context("D012"))
        self.assertEqual(review["status"], "no_rule_flags")
        self.assertFalse(review["copy_blocked"])

    def test_negative_style_feedback_uses_the_existing_bounded_rewrite(self):
        negative = output("陈女士，生日快乐，您不必回复。", "陈女士，不是来推销的，生日快乐。", "陈女士，您一定喜欢这份祝福。")
        provider = RecordingProvider(negative, GOOD)
        record = asyncio.run(draft(self.cases["D001"], provider, DATA_DIR))
        self.assertEqual(len(provider.contexts), 2)
        self.assertEqual(record["quality_review"]["automatic_rewrite_count"], 1)
        self.assertEqual(record["quality_review"]["status"], "no_rule_flags")
        self.assertEqual(record["attempts"][0]["raw_output"], negative)
        self.assertEqual(record["context"]["reply_brief"]["calibration"]["version"], self.calibration["version"])
        self.assertEqual(record["semantic_evaluation"], "not_evaluated")

    def test_price_replay_regressions_get_actionable_feedback(self):
        candidates = CandidateSet.model_validate_json(output(
            "魏女士，同价和八折都做不到。",
            "魏女士，这款标价16,800元，价格条件就是这样。",
            "魏女士，本次按目录标价16,800元提供。",
        ))
        findings = review_candidates(candidates, self.context("D012"))["findings"]
        self.assertEqual([(f["candidate_index"], f["code"]) for f in findings], [(1, "negative_framing"), (2, "blunt_price_boundary")])


if __name__ == "__main__":
    unittest.main()
