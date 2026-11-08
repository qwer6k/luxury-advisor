import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from luxury_advisor import api
from luxury_advisor.cli import read_cases
from luxury_advisor.service import ProviderOutput


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.request = read_cases(api.DATA_DIR)[0].input.model_dump(mode="json")
        self.directory = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(api, "RUNS_DIR", Path(self.directory.name))
        self.path_patch.start()
        self.db_patch = patch.object(api, "CLIENT_DB", Path(self.directory.name) / "clients.sqlite3")
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.path_patch.stop()
        self.directory.cleanup()
        self.client.close()

    def test_bootstrap_does_not_expose_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-private-secret"}):
            response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_configured"])
        self.assertEqual(len(response.json()["cases"]), 12)
        self.assertNotIn("test-private-secret", response.text)

    def test_generate_and_retrieve_use_the_same_saved_run(self):
        output = json.dumps({"candidates": [
            {"strategy": "简洁", "message": "陈女士，祝您生日快乐。"},
            {"strategy": "温暖", "message": "陈女士，愿您新一岁平安顺意。"},
            {"strategy": "轻松", "message": "今天送上生日祝福，愿您度过愉快的一天。"},
        ]}, ensure_ascii=False)
        provider = AsyncMock()
        provider.generate.return_value = ProviderOutput(output, "test-double", {"input_tokens": 20, "output_tokens": 30})
        with patch.object(api, "DeepSeekProvider", return_value=provider):
            response = self.client.post("/api/draft", json=self.request)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        saved = self.client.get(f"/api/runs/{result['run_id']}")
        self.assertEqual(saved.json()["candidates"], result["candidates"])
        self.assertEqual(saved.json()["usage"], {"input_tokens": 20, "output_tokens": 30})
        listing = self.client.get("/api/runs").json()
        self.assertEqual(len(listing), 1)
        self.assertNotIn("context", result)
        self.assertNotIn("attempts", result)
        self.assertEqual(result["semantic_evaluation"], "not_evaluated")
        self.assertEqual(result["quality_review"]["status"], "no_rule_flags")
        self.assertIsNone(result["quality_review"]["semantic_score"])
        self.assertTrue(result["reply_brief"]["approaches"])
        self.assertNotIn("editorial_example", result["reply_brief"])
        self.assertNotIn("writing_rules", result["reply_brief"])
        self.assertEqual(listing[0]["quality_status"], "no_rule_flags")
        provider.close.assert_awaited_once()

    def test_failed_generation_is_saved_and_visible(self):
        provider = AsyncMock()
        provider.generate.side_effect = RuntimeError("sensitive upstream text")
        with patch.object(api, "DeepSeekProvider", return_value=provider):
            response = self.client.post("/api/draft", json=self.request)
        self.assertEqual(response.status_code, 502)
        listing = self.client.get("/api/runs").json()
        self.assertEqual(listing[0]["status"], "failed")
        self.assertNotIn("sensitive upstream text", json.dumps(listing))

    def test_invalid_run_identifier_is_rejected(self):
        self.assertEqual(self.client.get("/api/runs/not-a-uuid").status_code, 422)

    def test_missing_key_prevents_generation(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.assertEqual(self.client.post("/api/draft", json=self.request).status_code, 503)

    def test_unknown_product_is_rejected_without_model_call(self):
        provider = AsyncMock()
        self.request["product_ids"] = ["UNKNOWN"]
        with patch.object(api, "DeepSeekProvider", return_value=provider):
            response = self.client.post("/api/draft", json=self.request)
        self.assertEqual(response.status_code, 422)
        provider.generate.assert_not_awaited()
        provider.close.assert_awaited_once()

    def create_profile(self, name="林女士"):
        response = self.client.post("/api/clients", json={"preferred_name":name,"relationship":"虚构测试客户"})
        self.assertEqual(response.status_code,201)
        return response.json()

    def test_client_profile_persists_and_stale_update_is_rejected(self):
        profile=self.create_profile()
        payload={"expected_revision":profile["revision"],"preferred_name":"小林","relationship":"客户指定新称呼","contact_status":"allowed"}
        response=self.client.patch(f"/api/clients/{profile['id']}",json=payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["revision"],2)
        self.assertEqual(self.client.patch(f"/api/clients/{profile['id']}",json=payload).status_code,409)
        self.assertEqual(self.client.get(f"/api/clients/{profile['id']}").json()["preferred_name"],"小林")

    def test_linked_draft_uses_authoritative_identity_and_saved_evidence(self):
        profile=self.create_profile()
        response=self.client.post(f"/api/clients/{profile['id']}/facts",json={"expected_revision":1,"kind":"style","topic":"表达风格","value":"直接、简短，不引用古诗","scope":"greeting","source":"虚构客户明确说明"})
        profile=response.json()
        self.request.update({"client_id":profile["id"],"client_revision":profile["revision"]})
        self.request["client"]["preferred_name"]="错误的另一位客户"
        provider=AsyncMock()
        output=json.dumps({"candidates":[{"strategy":"简短","message":"林女士，祝您生日快乐。"},{"strategy":"温暖","message":"林女士，愿您新一岁平安顺意。"},{"strategy":"轻松","message":"生日快乐，愿您度过愉快的一天。"}]},ensure_ascii=False)
        provider.generate.return_value=ProviderOutput(output,"test-double",{})
        with patch.object(api,"DeepSeekProvider",return_value=provider):
            response=self.client.post("/api/draft",json=self.request)
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result["client_name"],"林女士")
        self.assertEqual(result["client_memory"]["revision"],2)
        self.assertEqual(result["client_memory"]["facts"][0]["source"],"虚构客户明确说明")
        context=json.loads(provider.generate.call_args.args[1])
        self.assertEqual(context["request"]["client"]["preferred_name"],"林女士")
        self.assertIn("不引用古诗",context["client_memory"]["facts"][0]["value"])
        saved=self.client.get(f"/api/runs/{result['run_id']}").json()
        self.assertEqual(saved["client_memory"],result["client_memory"])
        after=self.client.get(f"/api/clients/{profile['id']}").json()
        self.assertEqual(after["revision"],profile["revision"])
        self.assertEqual(after["interactions"],[])

    def test_paused_or_stale_client_prevents_any_provider_creation(self):
        profile=self.create_profile()
        self.client.patch(f"/api/clients/{profile['id']}",json={"expected_revision":1,"preferred_name":"林女士","relationship":"暂停联系","contact_status":"paused"})
        for revision in (1,2):
            self.request.update({"client_id":profile["id"],"client_revision":revision})
            with patch.object(api,"DeepSeekProvider") as provider:
                response=self.client.post("/api/draft",json=self.request)
            self.assertEqual(response.status_code,409)
            provider.assert_not_called()
        self.assertEqual(self.client.get("/api/runs").json(),[])

    def test_profile_revision_and_dates_are_validated(self):
        profile=self.create_profile()
        self.request["client_id"]=profile["id"]
        self.assertEqual(self.client.post("/api/draft",json=self.request).status_code,422)
        response=self.client.post(f"/api/clients/{profile['id']}/facts",json={"expected_revision":1,"kind":"preference","topic":"配色","value":"灰色","source":"虚构原话","observed_at":"2026-11-07T10:00:00"})
        self.assertEqual(response.status_code,422)

    def test_demo_import_is_idempotent(self):
        first=self.client.post("/api/clients/seed-demo")
        second=self.client.post("/api/clients/seed-demo")
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(len(first.json()),3)
        self.assertEqual({row["id"] for row in first.json()},{row["id"] for row in second.json()})

    def test_profile_change_during_generation_is_recorded_but_not_returned_as_usable(self):
        profile=self.create_profile()
        self.request.update({"client_id":profile["id"],"client_revision":1})
        async def generate_and_pause(*args):
            api.client_store().update(profile["id"],api.ProfileUpdate(expected_revision=1,preferred_name="林女士",contact_status="paused"))
            text=json.dumps({"candidates":[{"strategy":"简短","message":"林女士，祝您生日快乐。"},{"strategy":"温暖","message":"林女士，愿您新一岁平安顺意。"},{"strategy":"轻松","message":"生日快乐，愿您度过愉快的一天。"}]},ensure_ascii=False)
            return ProviderOutput(text,"test-double",{})
        provider=AsyncMock()
        provider.generate.side_effect=generate_and_pause
        with patch.object(api,"DeepSeekProvider",return_value=provider):
            response=self.client.post("/api/draft",json=self.request)
        self.assertEqual(response.status_code,409,response.text)
        records=self.client.get("/api/runs").json()
        self.assertEqual(records[0]["profile_check"],"changed_during_generation")
        self.assertEqual(records[0]["candidate_count"],3)

    def test_new_client_background_reaches_model_with_or_without_saved_profile(self):
        background={"gender":"female","age":32,"occupation":"建筑设计师","source":"虚构客户自述","observed_on":"2026-11-01"}
        output=json.dumps({"candidates":[{"strategy":"轻便","message":"顾女士，您日常更看重轻便还是容量？"},{"strategy":"配色","message":"顾女士，您通常偏爱哪类配色？"},{"strategy":"使用","message":"顾女士，方便说说您这次的使用需求吗？"}]},ensure_ascii=False)
        for linked in (False,True):
            with self.subTest(linked=linked):
                request={"scenario":"recommendation","client":{"preferred_name":"顾女士","relationship":"首次咨询","preferences":[],"lifecycle_stage":"new","background":background},"scenario_details":{"background":"客户已说明需要随身携带A4图纸，尚未确认预算与配色。"}}
                profile=None
                if linked:
                    profile=self.client.post("/api/clients",json={"preferred_name":"顾女士","background":background}).json()
                    request.update({"client_id":profile["id"],"client_revision":profile["revision"]})
                    request["client"]["background"]={"age":70,"occupation":"错误的另一位客户","source":"错误的临时输入"}
                    request["client"]["lifecycle_stage"]="established"
                provider=AsyncMock()
                provider.generate.return_value=ProviderOutput(output,"test-double",{})
                with patch.object(api,"DeepSeekProvider",return_value=provider):
                    response=self.client.post("/api/draft",json=request)
                self.assertEqual(response.status_code,200,response.text)
                context=json.loads(provider.generate.call_args.args[1])
                self.assertEqual(context["request"]["client"]["background"],background)
                self.assertEqual(context["request"]["client"]["lifecycle_stage"],"new")
                self.assertEqual(context["request"]["client"]["preferences"],[])
                self.assertEqual(context["request"]["conversation_history"],[])
                if profile:
                    self.assertEqual(response.json()["client_memory"]["background"],background)
                    self.assertEqual(self.client.get(f"/api/clients/{profile['id']}").json()["revision"],1)
                else:
                    self.assertEqual(self.client.get("/api/clients").json(),[])

    def test_invalid_background_is_rejected_before_any_provider_creation(self):
        for background in ({"age":130,"source":"虚构"},{"age":32},{"occupation":"设计师","source":"虚构","observed_on":"2099-01-01"}):
            with self.subTest(background=background),patch.object(api,"DeepSeekProvider") as provider:
                self.request["client"]["background"]=background
                self.assertEqual(self.client.post("/api/draft",json=self.request).status_code,422)
                provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
