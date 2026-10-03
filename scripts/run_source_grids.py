"""Run all predeclared CPU grids using the existing research pipeline."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.pipeline import run,verify_run
from research_lab.storage import read_json,digest

def execute(split,budget):
 output=ROOT/f'outputs/source-{split}-b{budget}'
 state=run(ROOT/f'experiments/source_memory/{split}_b{budget}.json',output,resume=(output/'state.json').exists())
 errors=verify_run(output)
 if errors: raise RuntimeError(str(errors))
 return {'split':split,'budget':budget,'status':state['status'],'jobs':len(state['jobs'])}

if __name__=='__main__':
 frozen=read_json(ROOT/'research/memory_v3/frozen.json')
 if digest(ROOT/'experiments/source_memory/experiment.py')!=frozen['experiment_sha256']: raise ValueError('Code changed after freeze')
 for path,hash_value in frozen['files'].items():
  if digest(ROOT/path)!=hash_value: raise ValueError('Frozen file changed: '+path)
 with ThreadPoolExecutor(max_workers=3) as pool:
  pending=[pool.submit(execute,s,b) for s in ('dev','holdout','stress') for b in (384,768,1536)]
  for future in as_completed(pending): print(future.result(),flush=True)
