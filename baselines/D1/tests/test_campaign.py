import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from luxury_advisor.campaign import (BudgetExceeded, BudgetedProvider, CampaignLedger,
                                    digest, run_campaign)
from luxury_advisor.cli import read_cases
from luxury_advisor.service import ProviderOutput

ROOT=Path(__file__).resolve().parents[1]


class Provider:
    def __init__(self, fail=False): self.calls=0; self.fail=fail
    async def generate(self, instructions, context):
        self.calls+=1
        if self.fail: raise TimeoutError('not saved')
        return ProviderOutput(json.dumps({'candidates':[{'strategy':str(i),'message':f'陈女士，愿您生日欢喜，岁岁从容{i}。'} for i in range(3)]}), 'fake-offline', {'input_tokens':1,'output_tokens':2})


class CampaignTests(unittest.TestCase):
    def test_cap_charged_before_failure_and_per_invocation(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=CampaignLedger(Path(d)/'budget.db',2)
            inv=ledger.start('preflight','P','D001','input','version')
            p=Provider(True); b=BudgetedProvider(p,ledger,inv,'preflight')
            for _ in range(2):
                with self.assertRaises(TimeoutError): asyncio.run(b.generate('rules','context'))
            with self.assertRaises(BudgetExceeded): asyncio.run(b.generate('rules','context'))
            self.assertEqual(p.calls,2); self.assertEqual(ledger.summary()['total_charged'],2)
            self.assertEqual(CampaignLedger(ledger.path,2).summary()['total_charged'],2)

    def test_resume_skips_success_failed_and_interrupted_and_checks_hash(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=CampaignLedger(Path(d)/'budget.db')
            for i,status in enumerate(['generated','failed','running']):
                case=f'D00{i+1}'; inv=ledger.start('formal','R1',case,'input','version')
                if status!='running': ledger.finish(inv,{'status':status},Path(d)/'run.json')
                self.assertIsNone(ledger.start('formal','R1',case,'input','version',True))
                with self.assertRaises(ValueError): ledger.start('formal','R1',case,'changed','version',True)
                with self.assertRaises(ValueError): ledger.start('formal','R1',case,'input','changed',True)
                with self.assertRaises(ValueError): ledger.start('formal','R1',case,'input','version')

    def test_phase_cap_and_reserved_crash_are_charged(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=CampaignLedger(Path(d)/'budget.db')
            inv=ledger.start('clean','C','D001','i','m');ledger.reserve(inv,'clean','s','c')
            self.assertEqual(CampaignLedger(ledger.path).summary()['unresolved_requests'],1)
            inv2=ledger.start('clean','C','D002','i','m');ledger.reserve(inv2,'clean','s','c')
            with self.assertRaises(BudgetExceeded): ledger.reserve(inv2,'clean','s','c')

    def test_batch_failure_is_saved_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            data=ROOT/'data';case=read_cases(data)[0];meta={};ledger=CampaignLedger(Path(d)/'budget.db')
            args=([(case,meta)],data,Path(d)/'runs',Provider(True),ledger,{'label':'T','manifest_hash':'hash'},'preflight')
            self.assertEqual(asyncio.run(run_campaign(*args)),1)
            paths=list((Path(d)/'runs').glob('*.json'));self.assertEqual(len(paths),1)
            raw=paths[0].read_bytes();record=json.loads(raw);self.assertEqual(record['status'],'failed')
            self.assertEqual(len(record['attempts']),1)
            asyncio.run(run_campaign(*args,resume=True));self.assertEqual(paths[0].read_bytes(),raw)

    def test_digest_key_order(self): self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
