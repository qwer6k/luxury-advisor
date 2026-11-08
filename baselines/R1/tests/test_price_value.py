import asyncio
import copy
import re
import unittest
from pathlib import Path

from luxury_advisor.cli import read_cases
from luxury_advisor.models import CandidateSet, DraftRequest
from luxury_advisor.quality import build_price_value_brief, build_reply_brief, review_candidates
from luxury_advisor.service import draft, load_context
from test_quality import RecordingProvider, output

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PLAIN_PRICE = output(
    "吴女士，这款按目录标价23,800元提供。",
    "吴女士，弧影中号肩包的标价为23,800元，本次按这一价格提供。",
    "吴女士，这款本次提供的价格是目录标价23,800元。",
)


class PriceValueTests(unittest.TestCase):
    def setUp(self):
        self.cases = {item.case_id: item.input for item in read_cases(DATA_DIR)}

    def context(self, case="D011"):
        context = load_context(DATA_DIR, self.cases[case])
        context["reply_brief"] = build_reply_brief(context, DATA_DIR)
        return context

    def test_value_connections_reference_only_the_selected_current_product_facts(self):
        for case_id in ("D011", "D012"):
            context = self.context(case_id)
            value = context["reply_brief"]["price_value_brief"]
            self.assertEqual(value["evaluation_status"], "not_evaluated")
            self.assertTrue(value["optional_connections"])
            for note in value["optional_connections"]:
                self.assertIn(note["product_id"], context["request"]["product_ids"])
                self.assertTrue(note["use_only_when"])
                for fact in note["verified_catalog_facts"]:
                    parts = re.fullmatch(r"product_information\[(\d+)\]\.([a-z]+)(?:\[(\d+)\])?", fact["ref"])
                    self.assertIsNotNone(parts)
                    product_index, field, item_index = parts.groups()
                    actual = context["product_information"][int(product_index)][field]
                    if item_index is not None:
                        actual = actual[int(item_index)]
                    self.assertEqual(fact["value"], actual)

    def test_stale_note_is_dropped_if_even_one_of_its_product_facts_changes(self):
        context = copy.deepcopy(self.context("D012"))
        context["product_information"][0]["features"].remove("可拆卸肩带")
        value = build_price_value_brief(context, DATA_DIR, [])
        self.assertIn("B02-change", value["omitted_stale_note_ids"])
        self.assertNotIn("B02-change", [note["id"] for note in value["optional_connections"]])
        self.assertIn("B02-color", [note["id"] for note in value["optional_connections"]])

    def test_price_focus_includes_sourced_long_term_preferences_beside_current_price_question(self):
        context = load_context(DATA_DIR, self.cases["D011"])
        context["client_memory"] = {"facts": [{"id": "preference-1", "kind": "preference", "topic": "收纳习惯", "value": "希望随身小物分开放"}], "interactions": []}
        brief = build_reply_brief(context, DATA_DIR)
        evidence = brief["price_value_brief"]["customer_evidence"]
        self.assertTrue(any(item["ref"] == "request.conversation_history[0]" for item in evidence))
        self.assertTrue(any(item["ref"] == "client_memory.facts:preference-1" for item in evidence))
        self.assertTrue(any(item["value"] == "岩灰色" for item in evidence))

    def test_other_scenes_do_not_receive_a_sales_value_brief(self):
        for case_id, case in self.cases.items():
            if case.scenario != "price_objection":
                self.assertNotIn("price_value_brief", self.context(case_id)["reply_brief"])

    def test_status_pressure_blocks_copy_while_legitimate_price_does_not(self):
        candidates = CandidateSet.model_validate_json(output(
            "吴女士，23,800元，以您的身份就该选择这款。",
            "吴女士，真正懂品质的人会接受23,800元的价格。",
            "吴女士，这款按标价23,800元提供，内部分隔袋可供您了解收纳布局。",
        ))
        review = review_candidates(candidates, self.context())
        self.assertTrue(review["copy_blocked"])
        self.assertEqual([f["candidate_index"] for f in review["findings"] if f["code"] == "status_pressure"], [1, 2])

    def test_self_commentary_gets_feedback_but_price_only_responses_are_not_forced_into_sales(self):
        review = review_candidates(CandidateSet.model_validate_json(output(
            "吴女士，这款标价23,800元，我把价格条件如实说明。",
            "吴女士，本次按目录标价23,800元提供。",
            "吴女士，弧影中号肩包按标价23,800元提供。",
        )), self.context())
        self.assertEqual([(f["candidate_index"], f["code"]) for f in review["findings"]], [(1, "price_self_commentary")])
        review = review_candidates(CandidateSet.model_validate_json(PLAIN_PRICE), self.context())
        self.assertEqual(review["status"], "no_rule_flags")
        self.assertIsNone(review["semantic_score"])

    def test_value_brief_and_risk_feedback_share_the_existing_two_call_budget(self):
        pressure = output("吴女士，真正懂品质的人会接受23,800元的价格。", "吴女士，以您的身份，23,800元正合适。", "吴女士，这款标价23,800元，彰显您的身份。")
        provider = RecordingProvider(pressure, PLAIN_PRICE)
        record = asyncio.run(draft(self.cases["D011"], provider, DATA_DIR))
        self.assertEqual(len(provider.contexts), 2)
        self.assertIn("price_value_brief", provider.contexts[0]["reply_brief"])
        self.assertEqual(record["quality_review"]["automatic_rewrite_count"], 1)
        self.assertFalse(record["quality_review"]["copy_blocked"])
        self.assertEqual(record["attempts"][0]["raw_output"], pressure)
        self.assertEqual(record["semantic_evaluation"], "not_evaluated")

    def test_latest_price_only_request_suppresses_old_style_and_value_examples(self):
        context = self.context()
        context["request"]["client"]["preferences"] = ["旧记录喜欢文学表达"]
        context["request"]["conversation_history"] = [{"speaker": "client", "text": "先只告诉我这款多少钱、能不能打折，别介绍其他的，短一点。"}]
        brief = build_reply_brief(context, DATA_DIR)
        value = brief["price_value_brief"]
        self.assertEqual(value["response_mode"], "price_only")
        self.assertEqual(value["optional_connections"], [])
        self.assertTrue(value["editorial_examples"])
        self.assertTrue(all(e["response_mode"] == "price_only" for e in value["editorial_examples"]))
        self.assertEqual(value["response_contract"]["source"]["value"], context["request"]["conversation_history"][0]["text"])

    def test_negated_price_only_or_price_condition_does_not_activate_the_contract(self):
        for text in ("别只报价格，也请说说与我用途有关的细节。", "不要只问价格，请介绍具体设计。", "只要价格合适，我就考虑。"):
            with self.subTest(text=text):
                context = self.context()
                context["request"]["conversation_history"] = [{"speaker": "client", "text": text}]
                brief = build_reply_brief(context, DATA_DIR)
                self.assertEqual(brief["price_value_brief"]["response_mode"], "personal_value_or_explore")

    def test_price_only_wish_and_unrequested_question_are_blocked(self):
        context = self.context()
        context["request"]["conversation_history"] = [{"speaker": "client", "text": "只告诉我价格，别介绍其他的。"}]
        context["reply_brief"] = build_reply_brief(context, DATA_DIR)
        review = review_candidates(CandidateSet.model_validate_json(output(
            "吴女士，这款按标价23,800元提供，愿您挑到合心意的包。",
            "吴女士，这款按标价23,800元提供，您平时在意什么？",
            "吴女士，这款按目录标价23,800元提供。",
        )), context)
        self.assertTrue(review["copy_blocked"])
        self.assertEqual([f["candidate_index"] for f in review["findings"] if f["code"] == "price_only_drift"], [1, 2])

    def test_price_only_drift_can_be_rewritten_with_original_retained(self):
        value = self.cases["D011"].model_dump(mode="json")
        value["conversation_history"] = [{"speaker": "client", "text": "只告诉我价格和折扣，短一点就好。"}]
        request = DraftRequest.model_validate(value)
        wishes = output("吴女士，23,800元，愿您从容选择。", "吴女士，标价23,800元，愿日子舒心。", "吴女士，23,800元，祝您选到合心意的包。")
        provider = RecordingProvider(wishes, PLAIN_PRICE)
        record = asyncio.run(draft(request, provider, DATA_DIR))
        self.assertEqual(len(provider.contexts), 2)
        self.assertEqual(record["quality_review"]["status"], "no_rule_flags")
        self.assertEqual(record["attempts"][0]["raw_output"], wishes)


if __name__ == "__main__":
    unittest.main()
