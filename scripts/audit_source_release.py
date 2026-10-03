"""Offline release audit: no credentials, network, model calls, or generated code."""
import importlib.util
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import read_json,write_json,digest,utc_now
from research_lab.pipeline import verify_run
from research_lab.framework import verify_artifact_manifest


def audit():
    started=time.monotonic();freeze=read_json(ROOT/'research/memory_v3/frozen.json')
    errors=[];checked=0;queries=0
    for path,expected in freeze['files'].items():
        if digest(ROOT/path)!=expected: errors.append('Changed frozen file: '+path)
    archived=ROOT/'outputs/source-holdout-b768/inputs/experiment.py'
    if digest(archived)!=freeze['experiment_sha256']: errors.append('Archived experiment hash changed')
    spec=importlib.util.spec_from_file_location('frozen_replay',archived)
    exp=importlib.util.module_from_spec(spec);spec.loader.exec_module(exp)
    tasks={}
    for split in ('dev','holdout','stress'):
      for budget in (384,768,1536):
        folder=ROOT/f'outputs/source-{split}-b{budget}'
        errors+=verify_run(folder)
        for job in read_json(folder/'state.json')['jobs'].values():
            r=read_json(folder/job['result_path']);seed=r['seed'];policy=r['provenance']['policy']
            if seed not in tasks: tasks[seed]=exp.generate(seed)
            for task,old in zip(tasks[seed],r['predictions'],strict=True):
                memory,peak=exp.retained_memory(task['events'],policy,budget)
                prediction=exp.read_memory(memory,task['query'],policy)
                truth,active,history=exp.oracle(task['events'],task['query'])
                expected={'id':task['id'],'family':task['family'],'expected':truth,'predicted':prediction,
                          'stale':prediction in history-active,'serialized_bytes':len(exp.encode(memory)), 'peak_retained_bytes':peak}
                if old!=expected: errors.append(f"Prediction mismatch: {r['method']}:{seed}:{task['id']}")
                queries+=1
            checked+=1
        print(f'replayed {split} B={budget}',flush=True)
    pilot=ROOT/'outputs/source-reader-pilot'
    errors+=verify_artifact_manifest(pilot,read_json(pilot/'artifact_manifest.json'))
    rows=[]
    for job in read_json(pilot/'state.json')['jobs'].values():
        record=read_json(pilot/job['result_path']);messages=read_json((pilot/job['result_path']).parent/'messages.json')
        payload=json.loads(messages[-1]['content'])
        if set(payload)!={'memory','query'}: errors.append('Pilot label leakage in payload')
        if record['correct']!=(record['predicted']==record['expected']): errors.append('Pilot score mismatch')
        rows.append(record)
    for row in read_json(pilot/'summary.json')['methods']:
        actual=[r for r in rows if r['method']==row['method']]
        if len(actual)!=12 or abs(sum(r['correct'] for r in actual)/12-row['mean'])>1e-12: errors.append('Pilot aggregate mismatch')
    report={'checked_at':utc_now(),'valid':not errors,'errors':errors,'cpu_jobs_replayed':checked,
        'predictions_replayed':queries,'pilot_responses_checked':len(rows),'audit_wall_seconds':time.monotonic()-started,
        'note':'Fresh-process replay of archived trusted implementation, not an independent algorithm or live API replication.'}
    write_json(ROOT/'research/memory_v3/release_audit.json',report)
    print(json.dumps(report))
    if errors: raise SystemExit(1)


if __name__=='__main__': audit()
