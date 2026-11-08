import tempfile
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError

from luxury_advisor.clients import ClientStore, ContactPaused, MissingClient, RevisionConflict
from luxury_advisor.models import ClientBackground, InteractionCreate, ProfileCreate, ProfileFact, ProfileUpdate

NOW=datetime(2026,11,7,12,tzinfo=timezone.utc)


class ClientMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/"clients.sqlite3"
        self.store=ClientStore(self.path)
        self.profile=self.store.create(ProfileCreate(preferred_name="周女士",relationship="虚构客户"))

    def tearDown(self):
        self.directory.cleanup()

    def add(self, **changes):
        body={"expected_revision":self.profile["revision"],"kind":"preference","topic":"配色","value":"灰色","source":"虚构客户明确表态","observed_at":"2026-01-01T00:00:00+00:00",**changes}
        self.profile=self.store.add_fact(self.profile["id"],ProfileFact(**body))
        return self.profile

    def snapshot(self, scenario="recommendation"):
        return self.store.snapshot(self.profile["id"],scenario,as_of=NOW)

    def test_persistence_and_same_name_clients_are_isolated(self):
        self.add()
        second=self.store.create(ProfileCreate(preferred_name="周女士",relationship="另一位同名虚构客户"))
        reopened=ClientStore(self.path)
        self.assertEqual(len(reopened.get(self.profile["id"])["facts"]),1)
        self.assertNotEqual(second["id"],self.profile["id"])
        self.assertEqual(reopened.snapshot(second["id"],"recommendation",as_of=NOW)["facts"],[])

    def test_new_statement_supersedes_old_and_backfill_does_not_undo_it(self):
        self.add(value="灰色")
        self.add(value="栗棕色",observed_at="2026-03-01T00:00:00+00:00")
        self.add(value="更早的黑色",observed_at="2025-12-01T00:00:00+00:00")
        self.assertEqual([item["value"] for item in self.snapshot()["facts"]],["栗棕色"])
        self.assertEqual(sum(item["status"]=="superseded" for item in self.profile["facts"]),2)
        self.assertEqual(self.profile["revision"],4)

    def test_scene_specific_need_does_not_erase_global_preference(self):
        self.add(value="通勤偏好灰色")
        self.add(value="本次活动希望明亮配色",scope="invitation",observed_at="2026-04-01T00:00:00+00:00")
        self.assertEqual([item["value"] for item in self.snapshot("invitation")["facts"]],["本次活动希望明亮配色"])
        self.assertEqual([item["value"] for item in self.snapshot("recommendation")["facts"]],["通勤偏好灰色"])

    def test_pending_expired_future_and_retired_facts_are_not_retrieved(self):
        self.add(topic="待核实",status="pending")
        self.add(topic="旧活动",valid_until="2026-02-01T00:00:00+00:00")
        with self.assertRaises(ValidationError):
            self.add(topic="未来资料",observed_at="2099-01-01T00:00:00+00:00")
        self.add(topic="停用资料")
        fact=next(item for item in self.profile["facts"] if item["topic"]=="停用资料")
        self.profile=self.store.change_fact(self.profile["id"],fact["id"],self.profile["revision"])
        self.assertEqual(self.snapshot()["facts"],[])

    def test_pending_fact_does_not_supersede_confirmed_until_human_confirmation(self):
        self.add(value="旧的明确偏好")
        self.add(value="待核实的新偏好",status="pending",observed_at="2026-02-01T00:00:00+00:00")
        self.assertEqual(self.snapshot()["facts"][0]["value"],"旧的明确偏好")
        pending=next(item for item in self.profile["facts"] if item["status"]=="pending")
        self.profile=self.store.change_fact(self.profile["id"],pending["id"],self.profile["revision"],confirm=True)
        self.assertEqual(self.snapshot()["facts"][0]["value"],"待核实的新偏好")

    def test_correction_keeps_original_evidence_and_excludes_superseded_fact(self):
        self.add()
        original=self.profile["facts"][0]
        self.add(value="明确改为棕色",source="客户最新纠正",observed_at="2026-02-01T00:00:00+00:00",replaces_fact_id=original["id"])
        before=next(item for item in self.profile["facts"] if item["id"]==original["id"])
        self.assertEqual(before["source"],"虚构客户明确表态")
        self.assertEqual(before["status"],"superseded")
        self.assertEqual(self.snapshot()["facts"][0]["source"],"客户最新纠正")

    def test_cannot_correct_other_clients_fact(self):
        self.add()
        other=self.store.create(ProfileCreate(preferred_name="林女士"))
        with self.assertRaises(MissingClient):
            self.store.add_fact(other["id"],ProfileFact(expected_revision=1,kind="style",topic="风格",value="简短",source="虚构",replaces_fact_id=self.profile["facts"][0]["id"]))
        self.assertEqual(self.store.get(other["id"])["revision"],1)

    def test_optimistic_revision_prevents_lost_updates(self):
        self.add()
        with self.assertRaises(RevisionConflict):
            self.store.update(self.profile["id"],ProfileUpdate(expected_revision=1,preferred_name="旧窗口的新称呼"))
        self.assertEqual(self.store.get(self.profile["id"])["preferred_name"],"周女士")

    def test_pause_is_enforced_before_memory_is_returned(self):
        self.profile=self.store.update(self.profile["id"],ProfileUpdate(expected_revision=1,preferred_name="周女士",contact_status="paused"))
        with self.assertRaises(ContactPaused):
            self.snapshot()

    def test_interactions_are_scoped_ordered_and_not_promoted_to_facts(self):
        for text,scenario,when in [("第一次通勤咨询","recommendation","2026-01-01T00:00:00+00:00"),("生日问候","greeting","2026-03-01T00:00:00+00:00"),("最新通勤咨询","recommendation","2026-02-01T00:00:00+00:00")]:
            self.profile=self.store.add_interaction(self.profile["id"],InteractionCreate(expected_revision=self.profile["revision"],speaker="client",text=text,source="虚构微信",scenario=scenario,occurred_at=when))
        memory=self.snapshot()
        self.assertEqual([item["text"] for item in memory["interactions"]],["第一次通勤咨询","最新通勤咨询"])
        self.assertEqual(memory["facts"],[])
        self.profile=self.store.retire_interaction(self.profile["id"],memory["interactions"][0]["id"],self.profile["revision"])
        self.assertEqual([item["text"] for item in self.snapshot()["interactions"]],["最新通勤咨询"])

    def test_old_constraint_is_not_dropped_when_other_facts_are_limited(self):
        self.add(kind="constraint",topic="联系边界",value="不要催促回复")
        for index in range(34):
            self.add(topic=f"资料{index}",value=f"虚构偏好{index}",observed_at="2026-05-01T00:00:00+00:00")
        memory=self.snapshot()
        self.assertEqual(memory["available_fact_count"],35)
        self.assertEqual(len(memory["facts"]),33)
        self.assertIn("不要催促回复",[item["value"] for item in memory["facts"]])

    def test_memory_snapshot_is_immutable_after_profile_changes(self):
        self.add()
        snapshot=self.snapshot()
        self.add(value="棕色",observed_at="2026-03-01T00:00:00+00:00")
        self.assertEqual(snapshot["revision"],2)
        self.assertEqual(snapshot["facts"][0]["value"],"灰色")
        self.assertEqual(self.snapshot()["revision"],3)

    def test_new_client_with_only_a_name_needs_no_history_or_demographics(self):
        profile=self.store.create(ProfileCreate(preferred_name="新客户小顾"))
        memory=self.store.snapshot(profile["id"],"recommendation")
        self.assertEqual(memory["lifecycle_stage"],"new")
        self.assertEqual(memory["background"]["gender"],"unknown")
        self.assertIsNone(memory["background"]["age"])
        self.assertEqual(memory["background"]["occupation"],"")
        self.assertEqual(memory["facts"],[])
        self.assertEqual(memory["interactions"],[])

    def test_background_is_persistent_sourced_and_kept_separate_from_preferences(self):
        background=ClientBackground(gender="female",age=32,occupation="建筑设计师",source="虚构客户自述",observed_on="2026-10-02")
        profile=self.store.create(ProfileCreate(preferred_name="小顾",background=background))
        memory=ClientStore(self.path).snapshot(profile["id"],"recommendation")
        self.assertEqual(memory["background"],background.model_dump(mode="json"))
        self.assertEqual(memory["background"]["age"],32)
        self.assertEqual(memory["background"]["observed_on"],"2026-10-02")
        self.assertEqual(memory["facts"],[])
        self.assertEqual(next(p for p in self.store.list() if p["id"]==profile["id"])["background"]["occupation"],"建筑设计师")

    def test_older_update_call_preserves_background_and_explicit_clear_is_audited(self):
        profile=self.store.create(ProfileCreate(preferred_name="小顾",lifecycle_stage="developing",background={"age":0,"source":"虚构客户明确资料"}))
        profile=self.store.update(profile["id"],ProfileUpdate(preferred_name="顾女士",expected_revision=1))
        self.assertEqual(profile["background"]["age"],0)
        self.assertEqual(profile["lifecycle_stage"],"developing")
        profile=self.store.update(profile["id"],ProfileUpdate(preferred_name="顾女士",expected_revision=2,background={},lifecycle_stage="unknown"))
        self.assertIsNone(profile["background"]["age"])
        self.assertEqual(profile["events"][0]["payload"]["before"]["background"]["age"],0)
        self.assertEqual(profile["events"][0]["payload"]["after"]["lifecycle_stage"],"unknown")

    def test_background_validation_preserves_unknown_and_rejects_invalid_known_data(self):
        for value in [{"age":-1,"source":"虚构"},{"age":121,"source":"虚构"},{"age":32.5,"source":"虚构"},{"age":True,"source":"虚构"},{"occupation":"设计师"},{"gender":"female"},{"age":32,"source":"虚构","observed_on":"2099-01-01"}]:
            with self.subTest(value=value),self.assertRaises(ValidationError):
                ClientBackground(**value)
        self.assertEqual(ClientBackground().gender,"unknown")
        self.assertIsNone(ClientBackground().observed_on)

    def test_legacy_database_migration_keeps_identity_history_and_unknown_stage(self):
        legacy_path=Path(self.directory.name)/"legacy.sqlite3"
        with sqlite3.connect(legacy_path) as db:
            db.execute("CREATE TABLE clients (id TEXT PRIMARY KEY, preferred_name TEXT NOT NULL, relationship TEXT NOT NULL, contact_status TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("INSERT INTO clients VALUES ('legacy-client','陈女士','旧资料原样保留','allowed',7,'2026-01-01','2026-01-01')")
        def read(_):
            return ClientStore(legacy_path).get("legacy-client")
        with ThreadPoolExecutor(max_workers=2) as pool:
            profiles=list(pool.map(read,range(2)))
        for profile in profiles:
            self.assertEqual(profile["id"],"legacy-client")
            self.assertEqual(profile["revision"],7)
            self.assertEqual(profile["relationship"],"旧资料原样保留")
            self.assertEqual(profile["lifecycle_stage"],"unknown")
            self.assertEqual(profile["background"]["gender"],"unknown")
        reopened=ClientStore(legacy_path)
        added=reopened.add_fact("legacy-client",ProfileFact(expected_revision=7,kind="style",topic="表达",value="简短",source="虚构明确表态"))
        self.assertEqual(added["revision"],8)
        self.assertEqual(reopened.get("legacy-client")["facts"][0]["value"],"简短")


if __name__=="__main__":
    unittest.main()
