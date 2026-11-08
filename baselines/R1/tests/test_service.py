import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

from luxury_advisor.cli import read_cases
from luxury_advisor.models import Scenario
from luxury_advisor.provider import DeepSeekProvider
from luxury_advisor.service import ProviderOutput, draft, save_run, validate_candidates

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
VALID_OUTPUT = json.dumps({"candidates": [
    {"strategy": "简短祝福", "message": "陈女士，生日快乐，愿新一岁常有自在时刻。"},
    {"strategy": "温暖问候", "message": "陈女士，今天送上生日祝福，愿您度过愉快的一天。"},
    {"strategy": "克制表达", "message": "祝您生日快乐，愿这一年平安顺意。"},
]}, ensure_ascii=False)


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    async def generate(self, instructions, context):
        self.calls += 1
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return ProviderOutput(output, "test-double-not-a-real-model", {"input_tokens": 0})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.cases = read_cases(DATA_DIR)
        self.request = self.cases[0].input

    def test_development_cases_cover_six_scenarios(self):
        self.assertEqual(len(self.cases), 12)
        for scenario in Scenario:
            self.assertEqual(sum(c.input.scenario == scenario for c in self.cases), 2)

    def test_success_is_not_reported_as_semantic_evaluation(self):
        provider = FakeProvider([VALID_OUTPUT])
        result = asyncio.run(draft(self.request, provider, DATA_DIR))
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["semantic_evaluation"], "not_evaluated")
        self.assertEqual(provider.calls, 1)

    def test_blank_output_is_repaired_once_and_original_attempt_is_retained(self):
        provider = FakeProvider(["   ", VALID_OUTPUT])
        result = asyncio.run(draft(self.request, provider, DATA_DIR))
        self.assertEqual(result["status"], "generated")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["attempts"][0]["raw_output"], "   ")
        self.assertEqual(result["attempts"][0]["validation"], "failed")

    def test_repair_budget_is_bounded(self):
        provider = FakeProvider(["{}", "{}", VALID_OUTPUT])
        result = asyncio.run(draft(self.request, provider, DATA_DIR))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["candidates"], [])

    def test_duplicate_candidates_are_rejected(self):
        obj = json.loads(VALID_OUTPUT)
        obj["candidates"][1]["message"] = obj["candidates"][0]["message"]
        with self.assertRaises(ValueError):
            validate_candidates(json.dumps(obj))

    def test_two_candidates_are_rejected(self):
        obj = json.loads(VALID_OUTPUT)
        obj["candidates"].pop()
        with self.assertRaises(ValidationError):
            validate_candidates(json.dumps(obj))

    def test_unknown_product_is_rejected_before_network_boundary(self):
        request = self.request.model_copy(update={"product_ids": ["UNKNOWN"]})
        provider = FakeProvider([VALID_OUTPUT])
        with self.assertRaises(ValueError):
            asyncio.run(draft(request, provider, DATA_DIR))
        self.assertEqual(provider.calls, 0)

    def test_provider_error_message_is_not_copied_to_evidence(self):
        provider = FakeProvider([RuntimeError("sensitive-upstream-detail")])
        result = asyncio.run(draft(self.request, provider, DATA_DIR))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(provider.calls, 1)
        self.assertNotIn("sensitive-upstream-detail", json.dumps(result))

    def test_run_file_cannot_be_overwritten(self):
        result = asyncio.run(draft(self.request, FakeProvider([VALID_OUTPUT]), DATA_DIR))
        with tempfile.TemporaryDirectory() as directory:
            path = save_run(result, Path(directory))
            self.assertEqual(json.loads(path.read_text())["run_id"], result["run_id"])
            with self.assertRaises(FileExistsError):
                save_run(result, Path(directory))

    def test_missing_key_prevents_provider_creation(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "not configured"):
                DeepSeekProvider()

    def test_incomplete_provider_response_is_rejected(self):
        client = Mock()
        client.responses.create = AsyncMock(return_value=SimpleNamespace(status="incomplete"))
        client.close = AsyncMock()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-dummy-key"}):
            with patch("luxury_advisor.provider.AsyncOpenAI", return_value=client):
                provider = DeepSeekProvider()
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    asyncio.run(provider.generate("instructions", "context"))
                asyncio.run(provider.close())


if __name__ == "__main__":
    unittest.main()
