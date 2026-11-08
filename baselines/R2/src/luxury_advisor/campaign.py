"""Auditable, bounded local validation campaigns. No network at import time."""

import hashlib
import json
import os
import sqlite3
import shutil
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from luxury_advisor.models import DraftRequest, TestCase
from luxury_advisor.service import draft, load_context, save_run

PHASE_LIMITS = {"preflight": 24, "formal": 100, "supplemental": 18, "clean": 2}
TOTAL_LIMIT = 144
FREEZE_FILES = ["brand.json", "products.json", "reply_playbooks.json",
                "reply_calibration.json", "product_value_notes.json", "evaluation_rubric.json"]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def read_case_file(path: Path, data_dir: Path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows["cases"]
    result = []
    for row in rows:
        metadata = row.get("metadata", {})
        case = TestCase.model_validate({k: v for k, v in row.items() if k != "metadata"})
        memory = metadata.get("profile_snapshot")
        load_context(data_dir, case.input, memory)
        result.append((case, metadata))
    if len({c.case_id for c, _ in result}) != len(result):
        raise ValueError("Duplicate case IDs")
    return result


def build_manifest(root: Path, cases_file: Path, label: str, model: str):
    paths = [*sorted((root / "src/luxury_advisor").glob("*.py")),
             *[root / "data" / f for f in FREEZE_FILES], root / "pyproject.toml", root / "uv.lock",
             *sorted((root / "web/src").glob("*")),
             *sorted((root / "web/dist").rglob("*")),
             root / "web/package.json", root / "web/package-lock.json",
             root / "web/tsconfig.json", root / "web/vite.config.ts",
             root / "formal-review/index.html",
             *sorted((root / "tests").glob("test_*.py"))]
    paths = [p for p in paths if p.is_file()]
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    body = {"label": label, "files": hashes,
            "cases_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
            "configuration": {"provider": "DeepSeek Responses API", "requested_model": model,
                              "max_attempts": 2, "sdk_retries": 0, "timeout_seconds": 60,
                              "max_output_tokens": 2048, "reasoning_effort": "none"},
            "dependencies": {p: version(p) for p in ("openai", "pydantic", "fastapi", "uvicorn")}}
    return {**body, "manifest_hash": digest(body), "frozen_at": stamp()}


def freeze(root: Path, cases_file: Path, destination: Path, label: str, model: str):
    manifest = build_manifest(root, cases_file, label, model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    archive = destination.parent / "versions" / label
    for name in manifest["files"]:
        target = archive / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    target = archive / cases_file.resolve().relative_to(root.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cases_file, target)
    return manifest


def verify_manifest(root, cases_file, manifest, model):
    current = build_manifest(root, cases_file, manifest["label"], model)
    if current["manifest_hash"] != manifest["manifest_hash"]:
        raise ValueError("Frozen version/input/configuration mismatch; create a new version")


class BudgetExceeded(RuntimeError):
    pass


class CampaignLedger:
    def __init__(self, path, max_calls=TOTAL_LIMIT):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not 1 <= max_calls <= TOTAL_LIMIT:
            raise ValueError("--max-calls must be between 1 and 144")
        self.max_calls = max_calls
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS invocations (
                    id TEXT PRIMARY KEY, phase TEXT, label TEXT, case_id TEXT,
                    input_hash TEXT, manifest_hash TEXT, started_at TEXT, status TEXT,
                    record_path TEXT, finished_at TEXT);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, invocation_id TEXT, phase TEXT, reserved_at TEXT,
                    status TEXT, finished_at TEXT, model TEXT, usage_json TEXT,
                    error_type TEXT, instructions_hash TEXT, context_hash TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def start(self, phase, label, case_id, input_hash, manifest_hash, resume=False):
        if phase not in PHASE_LIMITS:
            raise ValueError("Unknown campaign phase")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT input_hash,manifest_hash,status,record_path FROM invocations "
                              "WHERE phase=? AND label=? AND case_id=? ORDER BY started_at DESC",
                              (phase, label, case_id)).fetchall()
            if rows:
                if any(r[0] != input_hash or r[1] != manifest_hash for r in rows):
                    raise ValueError("Resume input/version mismatch")
                if not resume:
                    raise ValueError("Case already attempted; use --resume")
                if any(r[2] == "generated" for r in rows):
                    return None
                # Failed/crashed invocations remain immutable and charged. Resume never retries
                # them silently: a later targeted phase must explicitly select the case.
                db.execute("UPDATE invocations SET status='interrupted',finished_at=? "
                           "WHERE phase=? AND label=? AND case_id=? AND status='running'",
                           (stamp(), phase, label, case_id))
                return None
            invocation = str(uuid4())
            db.execute("INSERT INTO invocations VALUES (?,?,?,?,?,?,?,'running',NULL,NULL)",
                       (invocation, phase, label, case_id, input_hash, manifest_hash, stamp()))
            return invocation

    def reserve(self, invocation, phase, instructions, context):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT count(*) FROM requests").fetchone()[0]
            phase_count = db.execute("SELECT count(*) FROM requests WHERE phase=?", (phase,)).fetchone()[0]
            attempt_count = db.execute("SELECT count(*) FROM requests WHERE invocation_id=?", (invocation,)).fetchone()[0]
            if total >= self.max_calls or phase_count >= PHASE_LIMITS[phase] or attempt_count >= 2:
                raise BudgetExceeded("Persistent campaign budget reached")
            request_id = str(uuid4())
            db.execute("INSERT INTO requests VALUES (?,?,?,?,'reserved',NULL,NULL,NULL,NULL,?,?)",
                       (request_id, invocation, phase, stamp(), digest(instructions), digest(context)))
            return request_id

    def finish_request(self, request_id, output=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE requests SET status=?,finished_at=?,model=?,usage_json=?,error_type=? WHERE id=?",
                       ("failed" if error else "completed", stamp(), output.model if output else None,
                        json.dumps(output.usage) if output else None, type(error).__name__ if error else None, request_id))

    def finish(self, invocation, record, path):
        with self.connect() as db:
            db.execute("UPDATE invocations SET status=?,record_path=?,finished_at=? WHERE id=?",
                       (record["status"], str(path), stamp(), invocation))

    def summary(self):
        with self.connect() as db:
            count = db.execute("SELECT count(*) FROM requests").fetchone()[0]
            return {"total_charged": count, "limit": self.max_calls,
                    "phases": {p: db.execute("SELECT count(*) FROM requests WHERE phase=?", (p,)).fetchone()[0] for p in PHASE_LIMITS},
                    "unresolved_requests": db.execute("SELECT count(*) FROM requests WHERE status='reserved'").fetchone()[0]}


class BudgetedProvider:
    def __init__(self, provider, ledger, invocation, phase):
        self.provider, self.ledger, self.invocation, self.phase = provider, ledger, invocation, phase

    async def generate(self, instructions, context):
        request_id = self.ledger.reserve(self.invocation, self.phase, instructions, context)
        try:
            output = await self.provider.generate(instructions, context)
        except BaseException as exc:
            self.ledger.finish_request(request_id, error=exc)
            raise
        self.ledger.finish_request(request_id, output=output)
        return output


async def run_campaign(cases, data_dir, output_dir, provider, ledger, manifest, phase, resume=False):
    failures = 0
    for case, metadata in cases:
        input_hash = digest({"input": case.input.model_dump(mode="json"), "metadata": metadata})
        invocation = ledger.start(phase, manifest["label"], case.case_id, input_hash,
                                  manifest["manifest_hash"], resume)
        if invocation is None:
            print(f"{case.case_id}: skipped (already recorded)", flush=True)
            continue
        bounded = BudgetedProvider(provider, ledger, invocation, phase)
        record = await draft(case.input, bounded, data_dir, case.case_id,
                             client_memory=metadata.get("profile_snapshot"))
        record["campaign"] = {"invocation_id": invocation, "phase": phase, "label": manifest["label"],
                              "input_hash": input_hash, "manifest_hash": manifest["manifest_hash"],
                              "test_metadata": metadata}
        path = save_run(record, output_dir)
        ledger.finish(invocation, record, path)
        failures += record["status"] != "generated"
        print(json.dumps({"case": case.case_id, "status": record["status"], "attempts": len(record["attempts"]),
                          "run_id": record["run_id"], "budget": ledger.summary()}, ensure_ascii=False), flush=True)
    return 1 if failures else 0
