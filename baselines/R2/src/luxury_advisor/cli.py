"""Validate fictional inputs offline; require --live for paid model calls."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from luxury_advisor.campaign import (CampaignLedger, freeze, read_case_file, run_campaign,
                                    verify_manifest)
from luxury_advisor.models import TestCase
from luxury_advisor.service import draft, load_context, save_run


def read_cases(data_dir: Path) -> list[TestCase]:
    return [c for c, _ in read_case_file(data_dir / "dev_cases.json", data_dir)]


async def run_live(cases, data_dir, output_dir):
    from luxury_advisor.provider import DeepSeekProvider
    provider = DeepSeekProvider()
    failures = 0
    try:
        for case in cases:
            record = await draft(case.input, provider, data_dir, case.case_id)
            save_run(record, output_dir)
            failures += record["status"] != "generated"
            print(f"{case.case_id}: {record['status']}", flush=True)
    finally:
        await provider.close()
    return 1 if failures else 0


async def campaign_live(args, cases, manifest):
    from luxury_advisor.provider import DeepSeekProvider
    provider = DeepSeekProvider()
    try:
        ledger = CampaignLedger(args.ledger, args.max_calls)
        return await run_campaign(cases, args.data_dir, args.output_dir, provider, ledger,
                                  manifest, args.phase, args.resume)
    finally:
        await provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/runs"))
    parser.add_argument("--case", help="Run only one case, e.g. D001")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cases-file", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-calls", type=int, default=144)
    parser.add_argument("--ledger", type=Path, default=Path("outputs/campaign/budget.sqlite3"))
    parser.add_argument("--phase", choices=["preflight", "formal", "supplemental", "clean"], default="formal")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--freeze", metavar="LABEL", help="Write a new immutable manifest; no model calls")
    args = parser.parse_args()
    try:
        file = args.cases_file or args.data_dir / "dev_cases.json"
        cases = read_case_file(file, args.data_dir)
        if args.case:
            cases = [(c, m) for c, m in cases if c.case_id == args.case]
            if not cases:
                raise ValueError("Unknown case ID")
        root = args.data_dir.resolve().parent
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        manifest = None
        if args.freeze:
            if not args.manifest or args.live:
                raise ValueError("--freeze requires --manifest and cannot be combined with --live")
            manifest = freeze(root, file, args.manifest, args.freeze, model)
            print(f"Frozen {args.freeze}: {manifest['manifest_hash']}")
        elif args.manifest:
            manifest = json.loads(args.manifest.read_text())
            verify_manifest(root, file, manifest, model)
        if not args.live:
            print(f"Validated {len(cases)} fictional input cases. No model calls or evaluations made.")
            return
        if args.cases_file:
            if not manifest:
                raise ValueError("Campaign --live requires a frozen --manifest")
            code = asyncio.run(campaign_live(args, cases, manifest))
        else:
            code = asyncio.run(run_live([c for c, _ in cases], args.data_dir, args.output_dir))
        raise SystemExit(code)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
