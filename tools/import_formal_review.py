"""Validate and archive an authentic formal-review export; never call a model."""
import argparse,hashlib,json
from pathlib import Path

def ingest(root,source):
    dataset=json.loads((root/'formal-review/dataset.json').read_text());raw=source.read_bytes();export=json.loads(raw)
    if export.get('qa') is not False:raise ValueError('QA or unknown-mode exports cannot become human evidence')
    if export.get('dataset_sha256')!=dataset['dataset_sha256'] or export.get('dataset_id')!=dataset['dataset_id']:raise ValueError('Dataset mismatch')
    valid={f"{c['case_id']}-{i}":(c,x) for c in dataset['cases'] for i,x in enumerate(c['candidates'],1)}
    statuses=json.loads((root/'outputs/campaign/human_review_status.json').read_text());bykey={f"{r['case_id']}-{r['candidate_index']}":r for r in statuses['judgments']}
    for key,review in export['judgments'].items():
        if key not in valid:raise ValueError('Unknown candidate')
        c,cand=valid[key]
        if review.get('run_id')!=c['run_id'] or review.get('candidate_sha256')!=cand['message_sha256']:raise ValueError('Run or candidate hash mismatch')
        if review.get('decision') not in ['',None,'可采用','需小改','需重写','不应发送','暂不确定']:raise ValueError('Unknown judgment')
        if any(type(v) is not int or not 1<=v<=5 for v in review.get('scores',{}).values()):raise ValueError('Invalid optional score')
        existing=bykey[key]
        if review.get('updated_at','')<existing.get('updated_at',''):continue
        existing.update({**review,'status':'reviewed' if review.get('decision') else 'not_reviewed','source_export_sha256':hashlib.sha256(raw).hexdigest()})
    archive=root/'outputs/campaign/human_reviews'/f'{hashlib.sha256(raw).hexdigest()}.json';archive.parent.mkdir(parents=True,exist_ok=True)
    if archive.exists():assert archive.read_bytes()==raw
    else:archive.write_bytes(raw)
    (root/'outputs/campaign/human_review_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2))
    print('Human decisions recorded:',sum(r['status']=='reviewed' for r in statuses['judgments']))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('file',type=Path);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args();ingest(args.root,args.file)
