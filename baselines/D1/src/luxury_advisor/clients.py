"""Persistent, evidence-backed fictional client profiles. No model writes memory."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from luxury_advisor.models import ClientBackground, InteractionCreate, ProfileCreate, ProfileFact, ProfileUpdate


class MissingClient(LookupError):
    pass


class RevisionConflict(ValueError):
    pass


class ContactPaused(ValueError):
    pass


def stamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


class ClientStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY, preferred_name TEXT NOT NULL, relationship TEXT NOT NULL,
                contact_status TEXT NOT NULL DEFAULT 'allowed', revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                lifecycle_stage TEXT NOT NULL DEFAULT 'unknown',
                background_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
                kind TEXT NOT NULL, topic TEXT NOT NULL, value TEXT NOT NULL, scope TEXT NOT NULL,
                source TEXT NOT NULL, status TEXT NOT NULL, observed_at TEXT NOT NULL,
                valid_until TEXT, replaces_fact_id TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS facts_by_client ON facts(client_id, status);
            CREATE TABLE IF NOT EXISTS interactions (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
                speaker TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, scenario TEXT,
                occurred_at TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS interactions_by_client ON interactions(client_id, occurred_at);
            CREATE TABLE IF NOT EXISTS profile_events (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
                revision INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        try:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(clients)")}
            needs_migration = not {"lifecycle_stage", "background_json"}.issubset(columns)
            connection.execute("BEGIN IMMEDIATE" if write or needs_migration else "BEGIN")
            # Additive migration preserves all v0.3 profiles, facts and revisions.
            # A legacy relationship stage remains unknown rather than being inferred.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(clients)")}
            if "lifecycle_stage" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN lifecycle_stage TEXT NOT NULL DEFAULT 'unknown'")
            if "background_json" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN background_json TEXT NOT NULL DEFAULT '{}'")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _decode_client(row):
        profile = dict(row)
        profile["background"] = ClientBackground.model_validate(json.loads(profile.pop("background_json", "{}"))).model_dump(mode="json")
        return profile

    @staticmethod
    def _client(db, client_id, revision=None):
        row = db.execute("SELECT * FROM clients WHERE id = ?", (str(client_id),)).fetchone()
        if row is None:
            raise MissingClient("Client not found")
        if revision is not None and row["revision"] != revision:
            raise RevisionConflict("Client profile changed; refresh it before continuing")
        return ClientStore._decode_client(row)

    @staticmethod
    def _event(db, client_id, revision, action, payload):
        db.execute(
            "INSERT INTO profile_events VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), str(client_id), revision, action,
             json.dumps(payload, ensure_ascii=False), stamp()),
        )

    def _touch(self, db, profile, action, payload):
        revision = profile["revision"] + 1
        db.execute("UPDATE clients SET revision = ?, updated_at = ? WHERE id = ?",
                   (revision, stamp(), profile["id"]))
        self._event(db, profile["id"], revision, action, payload)

    def _create(self, db, value, client_id=None):
        client_id = client_id or str(uuid4())
        now = stamp()
        db.execute("""INSERT INTO clients
                   (id, preferred_name, relationship, contact_status, revision, created_at, updated_at,
                    lifecycle_stage, background_json) VALUES (?, ?, ?, 'allowed', 1, ?, ?, ?, ?)""",
                   (client_id, value.preferred_name, value.relationship, now, now, value.lifecycle_stage,
                    json.dumps(value.background.model_dump(mode="json"), ensure_ascii=False)))
        self._event(db, client_id, 1, "created", value.model_dump(mode="json"))
        return client_id

    def create(self, value: ProfileCreate):
        with self.connect(write=True) as db:
            client_id = self._create(db, value)
        return self.get(client_id)

    def list(self):
        with self.connect() as db:
            rows = db.execute("""SELECT c.*,
                (SELECT count(*) FROM facts f WHERE f.client_id=c.id AND f.status='confirmed'
                    AND f.observed_at <= ? AND (f.valid_until IS NULL OR f.valid_until > ?)) AS fact_count,
                (SELECT count(*) FROM interactions i WHERE i.client_id=c.id AND i.status='active') AS interaction_count
                FROM clients c ORDER BY c.updated_at DESC, c.id""", (stamp(), stamp())).fetchall()
        return [self._decode_client(row) for row in rows]

    def get(self, client_id):
        with self.connect() as db:
            profile = self._client(db, client_id)
            profile["fictional"] = True
            profile["facts"] = [dict(row) for row in db.execute(
                "SELECT * FROM facts WHERE client_id=? ORDER BY observed_at DESC, created_at DESC",
                (str(client_id),))]
            profile["interactions"] = [dict(row) for row in db.execute(
                "SELECT * FROM interactions WHERE client_id=? ORDER BY occurred_at DESC, created_at DESC LIMIT 100",
                (str(client_id),))]
            profile["events"] = [
                {**dict(row), "payload": json.loads(row["payload"])} for row in db.execute(
                    "SELECT * FROM profile_events WHERE client_id=? ORDER BY revision DESC LIMIT 60",
                    (str(client_id),))]
        return profile

    def update(self, client_id, value: ProfileUpdate):
        with self.connect(write=True) as db:
            profile = self._client(db, client_id, value.expected_revision)
            db.execute("UPDATE clients SET preferred_name=?, relationship=?, contact_status=? WHERE id=?",
                       (value.preferred_name, value.relationship, value.contact_status, str(client_id)))
            # Older callers can still edit identity/contact status without erasing new fields.
            stage = value.lifecycle_stage if "lifecycle_stage" in value.model_fields_set else profile["lifecycle_stage"]
            background = value.background.model_dump(mode="json") if "background" in value.model_fields_set else profile["background"]
            db.execute("UPDATE clients SET lifecycle_stage=?, background_json=? WHERE id=?",
                       (stage, json.dumps(background, ensure_ascii=False), str(client_id)))
            self._touch(db, profile, "profile_updated", {
                "before": {key: profile[key] for key in ("preferred_name", "relationship", "contact_status", "lifecycle_stage", "background")},
                "after": {**value.model_dump(exclude={"expected_revision"}, mode="json"), "lifecycle_stage": stage, "background": background},
            })
        return self.get(client_id)

    @staticmethod
    def _activate(db, client_id, fact_id):
        fact = db.execute("SELECT * FROM facts WHERE id=? AND client_id=?", (fact_id, str(client_id))).fetchone()
        # Backfilled older observations never silently replace a more recent statement.
        newer = db.execute("""SELECT id FROM facts WHERE client_id=? AND kind=? AND topic=?
            AND scope=? AND status='confirmed' AND observed_at > ? AND id != ? LIMIT 1""",
            (str(client_id), fact["kind"], fact["topic"], fact["scope"], fact["observed_at"], fact_id)).fetchone()
        if newer:
            db.execute("UPDATE facts SET status='superseded' WHERE id=?", (fact_id,))
            return
        db.execute("""UPDATE facts SET status='superseded' WHERE client_id=? AND kind=?
            AND topic=? AND scope=? AND status='confirmed' AND id!=?""",
            (str(client_id), fact["kind"], fact["topic"], fact["scope"], fact_id))
        db.execute("UPDATE facts SET status='confirmed' WHERE id=?", (fact_id,))
        if fact["replaces_fact_id"]:
            db.execute("UPDATE facts SET status='superseded' WHERE id=? AND client_id=?",
                       (fact["replaces_fact_id"], str(client_id)))

    def add_fact(self, client_id, value: ProfileFact):
        with self.connect(write=True) as db:
            profile = self._client(db, client_id, value.expected_revision)
            if value.replaces_fact_id:
                previous = db.execute("SELECT id FROM facts WHERE id=? AND client_id=?",
                                      (str(value.replaces_fact_id), str(client_id))).fetchone()
                if not previous:
                    raise MissingClient("Source fact does not belong to client")
            fact_id = str(uuid4())
            db.execute("INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                fact_id, str(client_id), value.kind, value.topic, value.value, value.scope,
                value.source, "pending", stamp(value.observed_at),
                stamp(value.valid_until) if value.valid_until else None,
                str(value.replaces_fact_id) if value.replaces_fact_id else None, stamp(),
            ))
            if value.status == "confirmed":
                self._activate(db, client_id, fact_id)
            self._touch(db, profile, "fact_added", {"fact_id": fact_id, **value.model_dump(mode="json", exclude={"expected_revision"})})
        return self.get(client_id)

    def change_fact(self, client_id, fact_id, expected_revision, confirm=False):
        with self.connect(write=True) as db:
            profile = self._client(db, client_id, expected_revision)
            fact = db.execute("SELECT * FROM facts WHERE id=? AND client_id=?",
                              (str(fact_id), str(client_id))).fetchone()
            if not fact:
                raise MissingClient("Fact not found")
            if confirm:
                if fact["status"] != "pending":
                    raise RevisionConflict("Only pending facts can be confirmed")
                self._activate(db, client_id, str(fact_id))
            else:
                db.execute("UPDATE facts SET status='retired' WHERE id=?", (str(fact_id),))
            self._touch(db, profile, "fact_confirmed" if confirm else "fact_retired", {"fact_id": str(fact_id)})
        return self.get(client_id)

    def add_interaction(self, client_id, value: InteractionCreate):
        with self.connect(write=True) as db:
            profile = self._client(db, client_id, value.expected_revision)
            interaction_id = str(uuid4())
            db.execute("INSERT INTO interactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')", (
                interaction_id, str(client_id), value.speaker, value.text, value.source,
                value.scenario.value if value.scenario else None, stamp(value.occurred_at), stamp(),
            ))
            self._touch(db, profile, "interaction_recorded", {"interaction_id": interaction_id, **value.model_dump(mode="json", exclude={"expected_revision"})})
        return self.get(client_id)

    def retire_interaction(self, client_id, interaction_id, expected_revision):
        with self.connect(write=True) as db:
            profile = self._client(db, client_id, expected_revision)
            row = db.execute("SELECT id FROM interactions WHERE id=? AND client_id=?",
                             (str(interaction_id), str(client_id))).fetchone()
            if not row:
                raise MissingClient("Interaction not found")
            db.execute("UPDATE interactions SET status='retired' WHERE id=?", (str(interaction_id),))
            self._touch(db, profile, "interaction_retired", {"interaction_id": str(interaction_id)})
        return self.get(client_id)

    def snapshot(self, client_id, scenario, expected_revision=None, as_of=None):
        now = stamp(as_of)
        with self.connect() as db:
            profile = self._client(db, client_id, expected_revision)
            if profile["contact_status"] == "paused":
                raise ContactPaused("客户已暂停主动沟通，请先在客户档案核实联系意愿。")
            rows = [dict(row) for row in db.execute("""SELECT * FROM facts WHERE client_id=?
                AND status='confirmed' AND scope IN ('all', ?) AND observed_at <= ?
                AND (valid_until IS NULL OR valid_until > ?) ORDER BY observed_at DESC, created_at DESC""",
                (str(client_id), str(scenario), now, now))]
            # A scenario-specific statement has precedence only within that scenario.
            scoped = {(row["kind"], row["topic"]) for row in rows if row["scope"] != "all"}
            rows = [row for row in rows if row["scope"] != "all" or (row["kind"], row["topic"]) not in scoped]
            constraints = [row for row in rows if row["kind"] == "constraint"]
            other = [row for row in rows if row["kind"] != "constraint"][:32]
            facts = constraints + other
            interactions = [dict(row) for row in db.execute("""SELECT * FROM interactions
                WHERE client_id=? AND status='active' AND occurred_at <= ?
                AND (scenario IS NULL OR scenario=?) ORDER BY occurred_at DESC, created_at DESC LIMIT 8""",
                (str(client_id), now, str(scenario)))][::-1]
        return {
            "client_id": profile["id"], "revision": profile["revision"],
            "preferred_name": profile["preferred_name"], "relationship": profile["relationship"],
            "lifecycle_stage": profile["lifecycle_stage"], "background": profile["background"],
            "retrieved_at": now, "scenario": str(scenario), "facts": facts,
            "interactions": interactions, "available_fact_count": len(rows),
            "selection_policy": "确认且未过期；全局或当前场景；场景内同主题优先；保留全部约束及最近32条其他资料；最近8条适用沟通。",
        }

    def seed_demo(self, path):
        seeds = json.loads(Path(path).read_text(encoding="utf-8"))
        with self.connect(write=True) as db:
            if db.execute("SELECT value FROM metadata WHERE key='demo_seed_v1'").fetchone():
                return self.list()
            for seed in seeds:
                client_id = self._create(db, ProfileCreate(**seed["profile"]), seed["id"])
                # Seed source facts are curated fictional fixtures, not inferred from model output.
                revision = 1
                for item in seed["facts"]:
                    value = ProfileFact(expected_revision=revision, **item)
                    fact_id = str(uuid4())
                    db.execute("INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, NULL, ?)", (
                        fact_id, client_id, value.kind, value.topic, value.value, value.scope,
                        value.source, stamp(value.observed_at),
                        stamp(value.valid_until) if value.valid_until else None, stamp(),
                    ))
                for item in seed.get("interactions", []):
                    value = InteractionCreate(expected_revision=revision, **item)
                    db.execute("INSERT INTO interactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')", (
                        str(uuid4()), client_id, value.speaker, value.text, value.source,
                        value.scenario.value if value.scenario else None, stamp(value.occurred_at), stamp(),
                    ))
                db.execute("UPDATE clients SET contact_status=? WHERE id=?", (seed.get("contact_status", "allowed"), client_id))
                self._event(db, client_id, 1, "fictional_demo_imported", {"fixture_version":"clients-0.1", "fact_count":len(seed["facts"])})
            db.execute("INSERT INTO metadata VALUES ('demo_seed_v1', ?)", (stamp(),))
        return self.list()
