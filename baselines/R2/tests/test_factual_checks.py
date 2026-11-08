import json
import unittest
from pathlib import Path
from luxury_advisor.factual_checks import factual_contract,factual_findings

ROOT=Path(__file__).resolve().parents[1]
def saved(case):
    for p in (ROOT/'outputs/campaign/formal').glob('*.json'):
        r=json.loads(p.read_text())
        if r['case_id']==case:return r
    raise AssertionError(case)

class FactualRegressionTests(unittest.TestCase):
    def test_actual_wrong_price_is_blocked_and_true_price_is_not(self):
        r=saved('D142')
        for c in r['candidates']:
            codes=[f['code'] for f in factual_findings(c['message'],r['context'],1)]
            self.assertIn('catalog_price_mismatch',codes)
            codes=[f['code'] for f in factual_findings(c['message'].replace('17,800','16,800'),r['context'],1)]
            self.assertNotIn('catalog_price_mismatch',codes)

    def test_actual_compound_question_checks_both_topics(self):
        r=saved('D115')
        for i in [0,1]:self.assertIn('incomplete_compound_answer',[x['code'] for x in factual_findings(r['candidates'][i]['message'],r['context'],1)])
        self.assertNotIn('incomplete_compound_answer',[x['code'] for x in factual_findings(r['candidates'][2]['message'],r['context'],1)])

    def test_actual_specific_care_expansions_are_not_routine_care(self):
        for case in ['D119','D120']:
            r=saved(case);self.assertTrue(factual_contract(r['context'])['specific_care_issue'])
            for c in r['candidates']:self.assertIn('unverified_specific_care',[x['code'] for x in factual_findings(c['message'],r['context'],1)])
        r=saved('D117');self.assertFalse(factual_contract(r['context'])['specific_care_issue'])
        self.assertFalse(factual_findings(r['candidates'][0]['message'],r['context'],1))

    def test_invented_prior_policy_and_sparse_taste_are_found(self):
        r=saved('D123')
        for c in r['candidates'][:2]:self.assertIn('invented_service_interpretation',[x['code'] for x in factual_findings(c['message'],r['context'],1)])
        r=saved('D101');self.assertIn('unprovided_preference',[x['code'] for x in factual_findings(r['candidates'][1]['message'],r['context'],1)])

    def test_information_only_request_is_not_a_general_invitation(self):
        r=saved('D136');self.assertTrue(factual_contract(r['context'])['information_only'])
        for c in r['candidates']:self.assertIn('event_information_only_drift',[x['code'] for x in factual_findings(c['message'],r['context'],1)])
        r=saved('D135');self.assertFalse(factual_contract(r['context'])['information_only'])

    def test_known_use_value_is_not_blanket_blocked(self):
        for case in ['D141','D145','D150']:
            r=saved(case)
            for c in r['candidates']:self.assertFalse(factual_findings(c['message'],r['context'],1))
