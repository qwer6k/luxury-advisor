"""Rebuild the self-contained editorial review page and CSVs without model calls."""
import csv
import hashlib
import json
from pathlib import Path

REVIEW = Path(__file__).resolve().parent
ROOT = REVIEW.parent
raw = (ROOT / 'data/editorial_review_samples.json').read_bytes()
data = json.loads(raw)
assert len(data['cases']) == 48
content = (REVIEW / 'template.html').read_text(encoding='utf-8')
content = content.replace('__SAMPLE_DATA__', raw.decode().replace('<', '\\u003c'))
content = content.replace('__DATA_HASH__', hashlib.sha256(raw).hexdigest())
(REVIEW / 'index.html').write_text(content, encoding='utf-8')
with (REVIEW / '审稿样本-盲审版.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['组号', '候选ID', '场景', '案例', '关系阶段', '已知资料', '最近客户表态', '沟通目标', '候选正文或行动', '你的结论', '问题标签', '你的修改稿', '备注'])
    for case in data['cases']:
        for slot, draft in case['drafts'].items():
            facts = '\n'.join(f"{fact['id']}：{fact['text']}" for fact in case['facts'])
            writer.writerow([case['id'], draft['sample_id'], case['scenario_name'], case['title'], case['lifecycle_stage'], facts, case['latest_client_message'], case['task'], draft['message'] if draft['action'] == 'draft' else '建议暂不主动发送', '', '', '', ''])
with (REVIEW / '审稿样本-初判与依据.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['组号', '初判较好候选', '另一候选', '初判问题标签', '较好稿依据', '另一稿问题', '难度', '证据ID', '人工状态'])
    for case in data['cases']:
        assessor = case['assessor']
        writer.writerow([case['id'], assessor['preferred_draft'], assessor['other_draft'], '；'.join(assessor['issue_tags']), assessor['positive_reason'], assessor['negative_reason'], assessor['difficulty'], '；'.join(assessor['evidence_refs']), '尚未审查'])
print('Built 48 review pairs / 96 candidates; no API calls.')
