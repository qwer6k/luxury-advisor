"""Local API scaffold; the future WebUI reuses the same drafting function."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from luxury_advisor import __version__
from luxury_advisor.cli import read_cases
from luxury_advisor.clients import ClientStore, ContactPaused, MissingClient, RevisionConflict
from luxury_advisor.models import DraftRequest, InteractionCreate, ProfileCreate, ProfileFact, ProfileUpdate, RevisionRequest, Scenario
from luxury_advisor.provider import DeepSeekProvider
from luxury_advisor.service import draft, save_run

app = FastAPI(title="XUYU Advisor", version=__version__)
request_gate = asyncio.Semaphore(1)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "outputs" / "runs"
CLIENT_DB = PROJECT_ROOT / "outputs" / "clients.sqlite3"


def client_store() -> ClientStore:
    return ClientStore(CLIENT_DB)


def client_action(action):
    try:
        return action(client_store())
    except MissingClient:
        raise HTTPException(404, "客户或记录不存在。") from None
    except RevisionConflict:
        raise HTTPException(409, "客户档案已更新，请刷新档案后继续。") from None
    except ContactPaused as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok", "version": __version__,
        "api_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        "capabilities": {"client_memory": True, "client_background": True, "reply_quality": True, "review_samples": (DATA_DIR / "editorial_review_samples.json").is_file()},
    }


@app.get("/api/clients")
def list_clients() -> list[dict]:
    return client_store().list()


@app.post("/api/clients", status_code=201)
def create_client(request: ProfileCreate) -> dict:
    return client_store().create(request)


@app.post("/api/clients/seed-demo")
def seed_clients() -> list[dict]:
    return client_store().seed_demo(DATA_DIR / "client_seeds.json")


@app.get("/api/clients/{client_id}")
def get_client(client_id: UUID) -> dict:
    return client_action(lambda store: store.get(client_id))


@app.patch("/api/clients/{client_id}")
def update_client(client_id: UUID, request: ProfileUpdate) -> dict:
    return client_action(lambda store: store.update(client_id, request))


@app.post("/api/clients/{client_id}/facts", status_code=201)
def add_client_fact(client_id: UUID, request: ProfileFact) -> dict:
    return client_action(lambda store: store.add_fact(client_id, request))


@app.post("/api/clients/{client_id}/facts/{fact_id}/{action}")
def change_client_fact(client_id: UUID, fact_id: UUID, action: str, request: RevisionRequest) -> dict:
    if action not in ("confirm", "retire"):
        raise HTTPException(404, "Unknown action")
    return client_action(lambda store: store.change_fact(client_id, fact_id, request.expected_revision, action == "confirm"))


@app.post("/api/clients/{client_id}/interactions", status_code=201)
def add_client_interaction(client_id: UUID, request: InteractionCreate) -> dict:
    return client_action(lambda store: store.add_interaction(client_id, request))


@app.post("/api/clients/{client_id}/interactions/{interaction_id}/retire")
def retire_client_interaction(client_id: UUID, interaction_id: UUID, request: RevisionRequest) -> dict:
    return client_action(lambda store: store.retire_interaction(client_id, interaction_id, request.expected_revision))


@app.get("/api/clients/{client_id}/memory")
def get_client_memory(client_id: UUID, scenario: Scenario, revision: int | None = None) -> dict:
    return client_action(lambda store: store.snapshot(client_id, scenario, revision))


@app.get("/api/bootstrap")
async def bootstrap() -> dict:
    return {
        **await health(),
        "brand": json.loads((DATA_DIR / "brand.json").read_text(encoding="utf-8")),
        "products": json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8")),
        "cases": [case.model_dump(mode="json") for case in read_cases(DATA_DIR)],
    }


def public_run(record: dict, detail: bool = False) -> dict:
    attempts = record.get("attempts", [])
    result = {
        key: record.get(key)
        for key in (
            "run_id", "created_at", "case_id", "tool_version", "prompt_version",
            "brand_version", "status", "elapsed_ms", "semantic_evaluation",
            "profile_check", "comparison_mode", "comparison_baseline_run_id",
        )
    }
    result.update({
        "scenario": record.get("input", {}).get("scenario"),
        "client_name": record.get("input", {}).get("client", {}).get("preferred_name", ""),
        "client_id": record.get("input", {}).get("client_id"),
        "client_revision": record.get("input", {}).get("client_revision"),
        "candidate_count": len(record.get("candidates", [])),
        "attempt_count": len(attempts),
        "model": next((a.get("model") for a in reversed(attempts) if a.get("model")), None),
        "quality_status": (record.get("quality_review") or {}).get("status"),
    })
    if detail:
        result["input"] = record.get("input")
        result["candidates"] = record.get("candidates", [])
        result["client_memory"] = record.get("context", {}).get("client_memory")
        result["quality_review"] = record.get("quality_review")
        brief = record.get("context", {}).get("reply_brief")
        result["reply_brief"] = {key: brief[key] for key in ("goal", "approaches", "focus_evidence")} if brief else None
        result["usage"] = {
            "input_tokens": sum(a.get("usage", {}).get("input_tokens", 0) for a in attempts),
            "output_tokens": sum(a.get("usage", {}).get("output_tokens", 0) for a in attempts),
        }
    return result


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    records = []
    for path in RUNS_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("run_id"):
                records.append(public_run(record))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda r: r.get("created_at") or "", reverse=True)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: UUID) -> dict:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.is_file():
        raise HTTPException(404, "Run not found")
    try:
        return public_run(json.loads(path.read_text(encoding="utf-8")), detail=True)
    except (OSError, ValueError):
        raise HTTPException(500, "Run record could not be read") from None


@app.post("/api/draft")
async def create_draft(request: DraftRequest) -> dict:
    if os.environ.get("LUXURY_DEMO_READONLY") == "1":
        raise HTTPException(403, "当前为保存结果演示模式。实时生成请按启动说明配置。")
    # Keep this scaffold local until anonymous-demo rate limits are implemented.
    async with request_gate:
        memory = None
        if request.client_id:
            memory = client_action(lambda store: store.snapshot(request.client_id, request.scenario, request.client_revision))
        try:
            provider = DeepSeekProvider()
        except ValueError:
            raise HTTPException(503, "DeepSeek API key is not configured") from None
        try:
            record = await draft(request, provider, DATA_DIR, client_memory=memory)
        except ValueError:
            raise HTTPException(422, "Unknown product ID") from None
        finally:
            await provider.close()
        profile_changed = False
        if request.client_id:
            latest = client_store().get(request.client_id)
            profile_changed = latest["revision"] != request.client_revision or latest["contact_status"] == "paused"
            record["profile_check"] = "changed_during_generation" if profile_changed else "current_at_completion"
        save_run(record, RUNS_DIR)
        if profile_changed:
            raise HTTPException(409, "客户档案在生成期间有更新，本次结果仅留作记录；请刷新档案后重新准备消息。")
        if record["status"] != "generated":
            raise HTTPException(502, "Generation failed; the attempt was recorded")
        return public_run(record, detail=True)


if (PROJECT_ROOT / "formal-review").is_dir():
    app.mount("/formal-review", StaticFiles(directory=PROJECT_ROOT / "formal-review", html=True), name="formal-review")


if (PROJECT_ROOT / "review").is_dir():
    app.mount("/review", StaticFiles(directory=PROJECT_ROOT / "review", html=True), name="review")


if (PROJECT_ROOT / "web" / "dist").is_dir():
    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "web" / "dist", html=True), name="web")
