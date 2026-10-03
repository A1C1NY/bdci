"""Bounded, resumable model-reader pilot over frozen synthetic memories."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import sys
import threading
import statistics
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.model_client import ModelClient
from research_lab.model_config import load_models
from research_lab.storage import read_json, write_json, event, digest, utc_now
from research_lab.framework import build_artifact_manifest


def run():
    frozen=read_json(ROOT/'research/memory_v3/frozen.json')
    source=ROOT/'experiments/source_memory/experiment.py'
    if digest(source)!=frozen['experiment_sha256']:
        raise ValueError('Frozen implementation changed')
    spec=importlib.util.spec_from_file_location('study',source)
    exp=importlib.util.module_from_spec(spec);spec.loader.exec_module(exp)
    tasks=exp.generate(101)[:12]
    config=load_models()
    for route in config['models'].values(): route['max_attempts']=1
    # Limit concurrency per model; no retries, fallback model, or alternate answers.
    gates={alias:threading.Semaphore(2) for alias in ('deepseek','kimi')}
    output=ROOT/'outputs/source-reader-pilot'
    output.mkdir(parents=True,exist_ok=True)
    state_path=output/'state.json'
    methods=[f'{a}_{p}' for a in gates for p in ('event_window','source','protected')]
    plan={'title':'Two-model memory-reader pilot (12 paired traces)',
          'methods':methods,'seeds':list(range(12)), 'primary_metric':'accuracy','direction':'maximize',
          'question':'Can model readers answer from the same byte-bounded memories?', 'baseline':'deepseek_source'}
    write_json(output/'inputs/plan.json',plan)
    if state_path.exists():
        state=read_json(state_path)
        if state['experiment_sha256']!=frozen['experiment_sha256']: raise ValueError('Pilot identity changed')
    else:
        state={'status':'running','created_at':utc_now(),'experiment_sha256':frozen['experiment_sha256'],
               'jobs':{f'{m}__{i}':{'status':'pending','attempts':[]} for m in methods for i in range(12)}}
        write_json(state_path,state)
    def worker(method,i):
        alias,policy=next((a,method[len(a)+1:]) for a in gates if method.startswith(a+'_'))
        task=tasks[i]
        memory,peak=exp.retained_memory(task['events'],policy,768)
        description=('Raw records [operation P=put/R=revoke,key,source,version,value]. Reconstruct only from these retained events.' if policy=='event_window' else
            'Current retained slots [key,source,version,value]. null is an explicit revoked state. Slots are already version-reduced; do not reinterpret list order as global authority.')
        gate=('For this conservative policy you MUST answer ABSTAIN unless slots for BOTH sources a and b of the query key are retained.' if policy=='protected' else
              'Missing source slots are treated as unavailable evidence; use the present slots. If no evidence for the query remains, answer ABSTAIN.')
        messages=[{'role':'system','content':'You are a memory reader. Sources a and b have equal authority. Within one source, highest version wins and an explicit revocation permanently cancels its referenced version. Never revive an earlier version. Ignore lower-version replays. Distinct active values mean CONFLICT; explicit revocations leaving no active value mean UNKNOWN. No query evidence means ABSTAIN. Return ONLY JSON {"answer":"value or UNKNOWN or CONFLICT or ABSTAIN"}. No explanation. '+description+' '+gate},
                  {'role':'user','content':json.dumps({'memory':memory,'query':task['query']},ensure_ascii=False)}]
        folder=output/'jobs'/f'{method}__{i}'/'attempt_1'
        folder.mkdir(parents=True,exist_ok=True)
        write_json(folder/'messages.json',messages)
        response=None;error=None;predicted='ERROR'
        with gates[alias]:
            try:
                response=ModelClient(config,notify=lambda *a,**k:None).generate(alias,messages,
                    purpose=f'source-reader:{method}:{i}',max_output_tokens=1800)
                write_json(folder/'response.json',response)
                if not response['complete']: raise ValueError('Incomplete response')
                text=response['text'].strip()
                if text.startswith('```'): text='\n'.join(text.splitlines()[1:-1]).strip()
                value=json.loads(text)
                if set(value)!= {'answer'} or not isinstance(value['answer'],str): raise ValueError('Invalid answer schema')
                predicted=value['answer']
            except Exception as exc:
                error=str(exc)
        expected,active,history=exp.oracle(task['events'],task['query'])
        record={'method':method,'seed':i,'task_id':task['id'],'family':task['family'],'expected':expected,
                'predicted':predicted,'correct':predicted==expected,'stale':predicted in history-active,
                'serialized_bytes':len(exp.encode(memory)),'peak_retained_bytes':peak,
                'request_id':response.get('request_id') if response else None,'usage':response.get('usage') if response else None,
                'error':error,'metrics':{'accuracy':float(predicted==expected)},
                'provenance':{'dataset_sha256':digest(source),'pilot':True}}
        write_json(folder/'result.json',record)
        return record, folder
    futures={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Round robin methods so the slower model does not block all slots.
        for i in range(12):
            for method in methods:
                key=f'{method}__{i}';job=state['jobs'][key]
                if job['status']=='completed': continue
                if job['attempts']:
                    # A crash may have sent a paid request. Do not silently retry.
                    result=output/'jobs'/key/'attempt_1/result.json'
                    if not result.exists(): raise RuntimeError(f'Interrupted request {key}; requires explicit reconciliation')
                    job.update(status='completed',result_path=result.relative_to(output).as_posix())
                    continue
                job.update(status='running',attempts=[f'jobs/{key}/attempt_1'])
                write_json(state_path,state)
                event(output/'events.jsonl','job_started',job=key)
                futures[pool.submit(worker,method,i)]=key
        for future in as_completed(futures):
            key=futures[future]
            record,folder=future.result()
            state['jobs'][key].update(status='completed', result_path=(folder/'result.json').relative_to(output).as_posix(),
                manifest=build_artifact_manifest(output,list(folder.iterdir())))
            write_json(state_path,state)
            event(output/'events.jsonl','job_finished',job=key,status='completed',error=record['error'])
            print(f"{key} correct={record['correct']} error={record['error']}",flush=True)
    records=[read_json(output/j['result_path']) for j in state['jobs'].values()]
    rows=[]
    for method in methods:
        selected=[r for r in records if r['method']==method]
        rows.append({'method':method,'n_seeds':12,'mean':statistics.mean(r['correct'] for r in selected),
                     'sample_stddev':statistics.stdev(r['correct'] for r in selected),
                     'stale_rate':statistics.mean(r['stale'] for r in selected),
                     'errors':sum(bool(r['error']) for r in selected)})
    write_json(output/'summary.json',{'metric':'accuracy','direction':'maximize','baseline':'deepseek_source','methods':rows,
        'inference':'12 paired synthetic traces only; errors counted incorrect. No model superiority inference.'})
    write_json(output/'resource_report.json',{'planned_calls':72,'failed_answers':sum(bool(r['error']) for r in records),
        'reported_tokens':sum(r['usage']['total_tokens'] for r in records if r['usage']),
        'note':'Canonical billing and any unknown reservations remain in shared token ledger.'})
    state.update(status='completed',finished_at=utc_now())
    files=[p for p in output.rglob('*') if p.is_file() and p.name not in ('state.json','events.jsonl','artifact_manifest.json')]
    write_json(output/'artifact_manifest.json',build_artifact_manifest(output,files))
    write_json(state_path,state)
    event(output/'events.jsonl','run_completed',jobs=len(records))


if __name__=='__main__': run()
