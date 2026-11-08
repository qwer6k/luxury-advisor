#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
command -v uv >/dev/null 2>&1 || { echo 'Install uv from https://docs.astral.sh/uv/ then retry.'; exit 1; }
uv sync --frozen
uv run --no-sync python -c 'from pathlib import Path; from luxury_advisor.clients import ClientStore; p=Path("outputs/clients.sqlite3"); ClientStore(p).seed_demo(Path("data/client_seeds.json")) if not p.exists() else None'
export LUXURY_DEMO_READONLY="${LUXURY_DEMO_READONLY:-1}"
if [ -f .env ]; then
  exec uv run --no-sync --env-file .env uvicorn luxury_advisor.api:app --host 127.0.0.1 --port "${PORT:-8002}"
fi
exec uv run --no-sync uvicorn luxury_advisor.api:app --host 127.0.0.1 --port "${PORT:-8002}"
