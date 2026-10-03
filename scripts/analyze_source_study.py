"""Recompute metrics from raw predictions, pair seeds, and export auditable tables."""
import csv
import io
import json
from pathlib import Path
import random
import statistics
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import read_json,write_json,write_text,digest,utc_now
from research_lab.pipeline import verify_run


def bootstrap(values):
    rng=random.Random(20260929)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(10000))
    return [means[249],means[9749]]


def analyze():
    summaries=[];pairs=[];raw=[];family=[];errors=[];runtime=0;grids=[]
    for split in ('dev','holdout','stress'):
      for budget in (384,768,1536):
        folder=ROOT/f'outputs/source-{split}-b{budget}'
        errors+=verify_run(folder)
        state=read_json(folder/'state.json');by={}
        grids.append({'path':folder.relative_to(ROOT).as_posix(),'fingerprint':state['fingerprint'],'jobs':len(state['jobs'])})
        for job in state['jobs'].values():
            value=read_json(folder/job['result_path'])
            policy=value['provenance']['policy'];seed=value['seed']
            predictions=value['predictions'];n=len(predictions)
            # Independently verify primary and guardrail counts from per-query outputs.
            assert abs(value['metrics']['accuracy']-sum(p['predicted']==p['expected'] for p in predictions)/n)<1e-12
            assert abs(value['metrics']['stale_rate']-sum(p['stale'] for p in predictions)/n)<1e-12
            assert max(p['peak_retained_bytes'] for p in predictions)<=budget
            by.setdefault(policy,{})[seed]=value['metrics']
            raw.append({'split':split,'budget':budget,'policy':policy,'seed':seed,**value['metrics']})
            for f,m in value['family_metrics'].items():
                family.append({'split':split,'budget':budget,'policy':policy,'seed':seed,'family':f,**m})
            execution=read_json((folder/job['result_path']).parent/'execution.json')
            runtime+=execution['wall_seconds']
        for policy,seedmetrics in by.items():
            means={m:statistics.mean(v[m] for v in seedmetrics.values()) for m in next(iter(seedmetrics.values()))}
            summaries.append({'split':split,'budget':budget,'policy':policy,'seeds':len(seedmetrics),**means})
        if split!='dev':
            for treatment,control in [('gated','source'),('protected','gated')]:
                for metric in ('stale_rate','accuracy','abstain_rate','false_concrete_conflict_rate'):
                    values=[by[treatment][s][metric]-by[control][s][metric] for s in sorted(by[control])]
                    pairs.append({'split':split,'budget':budget,'treatment':treatment,'control':control,'metric':metric,
                                  'delta':statistics.mean(values),'ci95':bootstrap(values),'n_seeds':len(values)})
    if errors: raise RuntimeError(str(errors))
    out=ROOT/'research/memory_v3/results';out.mkdir(parents=True,exist_ok=True)
    for name,rows in [('aggregate',summaries),('per_seed',raw),('per_family_seed',family)]:
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        write_text(out/(name+'.csv'),stream.getvalue())
    result={'created_at':utc_now(),'summary':summaries,'paired':pairs,'grids':grids,'cpu_job_wall_seconds_sum':runtime,
            'cpu_jobs':sum(g['jobs'] for g in grids),'unique_standard_holdout_queries':1200,'unique_stress_queries':1200,
            'note':'Repeated method/budget predictions are paired, not independent data. Development is excluded from main results.'}
    write_json(out/'analysis.json',result)
    lines=['# Frozen source-memory results','', '| Split | Bytes | Policy | Accuracy | Stale | Abstain | False concrete on conflict |', '|---|---:|---|---:|---:|---:|---:|']
    for r in summaries:
        if r['split']=='dev': continue
        lines.append(f"| {r['split']} | {r['budget']} | {r['policy']} | {r['accuracy']:.4f} | {r['stale_rate']:.4f} | {r['abstain_rate']:.4f} | {r['false_concrete_conflict_rate']:.4f} |")
    lines+=['','All methods and negative results retained. Paired seed-bootstrap intervals: results/analysis.json.',
        'These are synthetic results, not an official Reviewer score or natural-language benchmark performance.']
    write_text(ROOT/'research/memory_v3/results_summary.md','\n'.join(lines)+'\n')
    print(json.dumps({'cpu_jobs':result['cpu_jobs'],'wall_seconds_sum':runtime,'summary':[r for r in summaries if r['split']!='dev']},indent=2))


if __name__=='__main__': analyze()
