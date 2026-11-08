import asyncio
import json
import unittest
from pathlib import Path

from luxury_advisor.cli import read_cases
from luxury_advisor.models import CandidateSet
from luxury_advisor.quality import build_reply_brief, review_candidates
from luxury_advisor.service import ProviderOutput, draft, load_context

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def output(*messages):
    return json.dumps({"candidates": [{"strategy": f"表达{index}", "message": text} for index, text in enumerate(messages, 1)]}, ensure_ascii=False)


GOOD = output("陈女士，生日快乐，愿新一岁常有自在时刻。", "陈女士，今天送上生日祝福，愿您度过愉快的一天。", "祝您生日快乐，愿这一年平安顺意。")
DRIFT = output("陈女士，生日快乐，有空来店里看看就好。", "陈女士，生日快乐，您随意。", "陈女士，祝您生日快乐。\n\n序隅 顾问")
PROMISE = output("陈女士，今天生日可以打八折。", "陈女士，生日快乐，保证有现货。", "祝您生日快乐，我们可以免费换新。")


class RecordingProvider:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.contexts = []

    async def generate(self, instructions, context):
        self.contexts.append(json.loads(context))
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return ProviderOutput(value, "test-double", {"input_tokens": 10, "output_tokens": 20})


class ReplyQualityTests(unittest.TestCase):
    def setUp(self):
        self.cases = {item.case_id: item.input for item in read_cases(DATA_DIR)}

    def context(self, case="D001"):
        context = load_context(DATA_DIR, self.cases[case])
        context["reply_brief"] = build_reply_brief(context, DATA_DIR)
        return context

    def test_greeting_regressions_are_found_without_a_semantic_score(self):
        review = review_candidates(CandidateSet.model_validate_json(DRIFT), self.context())
        self.assertEqual({item["code"] for item in review["findings"]}, {"greeting_drift", "awkward_distance", "unrequested_signature"})
        self.assertEqual(review["human_review"], "not_reviewed")
        self.assertIsNone(review["semantic_score"])

    def test_problem_context_in_freeform_input_does_not_get_routine_care(self):
        request = self.cases["D006"].model_copy(update={"conversation_history": [], "scenario_details": {"background": "客户反馈提手边缘起皮，想知道能否免费更换。"}})
        context = load_context(DATA_DIR, request)
        context["reply_brief"] = build_reply_brief(context, DATA_DIR)
        messages = output("沈女士，可以用柔软干布擦拭试试。", "沈女士，先不要用干布擦拭，需要门店确认情况。", "沈女士，能否免费更换需要先由门店查看确认。")
        review = review_candidates(CandidateSet.model_validate_json(messages), context)
        self.assertEqual(context["reply_brief"]["context_mode"], "product_issue")
        remedies = [item for item in review["findings"] if item["code"] == "unverified_issue_remedy"]
        self.assertEqual([item["candidate_index"] for item in remedies], [1])

    def test_price_candidate_cannot_skip_the_actual_question(self):
        messages = output("唐女士，我没有直接答应同价或折扣的权限，您可以再考虑。", "唐女士，这款是光面牛皮，您可以来店里看看。", "唐女士，理解您对价差的顾虑，这边无法直接匹配价格。")
        review = review_candidates(CandidateSet.model_validate_json(messages), self.context("D012"))
        self.assertEqual([item["candidate_index"] for item in review["findings"] if item["code"] == "price_question_unanswered"], [2])

    def test_clear_unauthorized_promises_are_blocked_but_denials_are_not(self):
        review = review_candidates(CandidateSet.model_validate_json(PROMISE), self.context())
        self.assertTrue(review["copy_blocked"])
        self.assertEqual(sum(item["code"] == "unsupported_commitment" for item in review["findings"]), 3)
        denied = output("陈女士，不能保证有现货。", "陈女士，我们不可以免费换新。", "陈女士，没有折扣权限，但是可以打八折。")
        review = review_candidates(CandidateSet.model_validate_json(denied), self.context())
        self.assertEqual([item["candidate_index"] for item in review["findings"] if item["code"] == "unsupported_commitment"], [3])

    def test_very_short_greetings_are_not_lengthened_for_wording_diversity(self):
        messages = output("陈女士，生日快乐。", "陈女士，生日快乐，愿您自在。", "陈女士，祝新一岁顺心。")
        review = review_candidates(CandidateSet.model_validate_json(messages), self.context())
        self.assertEqual(review["status"], "no_rule_flags")
        self.assertIsNone(review["semantic_score"])

    def test_feedback_rewrite_is_bounded_and_original_output_is_preserved(self):
        provider = RecordingProvider(DRIFT, GOOD)
        record = asyncio.run(draft(self.cases["D001"], provider, DATA_DIR))
        self.assertEqual(record["status"], "generated")
        self.assertEqual(record["attempts"][0]["raw_output"], DRIFT)
        self.assertEqual(record["attempts"][0]["quality_review"]["status"], "needs_review")
        self.assertEqual(record["quality_review"]["status"], "no_rule_flags")
        self.assertEqual(record["quality_review"]["automatic_rewrite_count"], 1)
        self.assertEqual(len(provider.contexts), 2)
        self.assertIn("revision_request", provider.contexts[1])
        self.assertEqual(record["semantic_evaluation"], "not_evaluated")

    def test_format_and_content_share_two_call_budget_and_unresolved_risk_remains_visible(self):
        for first in ("{}", PROMISE):
            with self.subTest(first=first):
                provider = RecordingProvider(first, PROMISE, GOOD)
                record = asyncio.run(draft(self.cases["D001"], provider, DATA_DIR))
                self.assertEqual(len(provider.contexts), 2)
                self.assertEqual(record["quality_review"]["status"], "needs_review")
                self.assertTrue(record["quality_review"]["copy_blocked"])
                self.assertEqual(len(record["candidates"]), 3)

    def test_failed_rewrite_retains_initial_draft_and_does_not_hide_remaining_issues(self):
        provider = RecordingProvider(DRIFT, RuntimeError("private upstream detail"))
        record = asyncio.run(draft(self.cases["D001"], provider, DATA_DIR))
        self.assertEqual(record["status"], "generated")
        self.assertEqual(record["quality_review"]["rewrite_outcome"], "not_completed")
        self.assertEqual(record["quality_review"]["status"], "needs_review")
        self.assertNotIn("private upstream detail", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
