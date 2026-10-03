"""Freeze protocol and code before held-out study. Never overwrite a freeze."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import digest,write_json,read_json,utc_now
from research_lab.token_ledger import TokenLedger
from research_lab.model_config import load_models
p=ROOT/'research/memory_v3/frozen.json'
if p.exists(): raise RuntimeError('Freeze exists; do not overwrite')
for name,decision in [('deepseek-memory-cases-001','partially_accepted'),('kimi-source-protocol-audit-001','partially_accepted')]:
 state=read_json(ROOT/f'outputs/{name}/state.json')
 state.update(status='supervisor_reviewed',supervisor_decision=decision,applied_to_research=False)
 write_json(ROOT/f'outputs/{name}/state.json',state)
files=list((ROOT/'experiments/source_memory').glob('*.json'))+[ROOT/'experiments/source_memory/protocol.md',ROOT/'scripts/source_reader_pilot.py',ROOT/'tests/test_source_memory.py']
write_json(p,{'frozen_at':utc_now(),'experiment_sha256':digest(ROOT/'experiments/source_memory/experiment.py'),
 'files':{x.relative_to(ROOT).as_posix():digest(x) for x in files},'notes':'Development b768 inspected; no holdout or stress result observed. No tuning after this freeze.'})
write_json(ROOT/'research/memory_v3/usage_before_evaluation.json',TokenLedger(load_models()).snapshot())
progress=read_json(ROOT/'research/progress.json')
progress.update(status='experiments',next_action='运行冻结的留出/压力网格及72次真实模型读取试验；同时准备英文ICLR论文。')
progress['stages'][2].update(status='completed',detail='协议和源码已冻结；Kimi/DeepSeek意见已审核，错误规则已拒绝。')
progress['stages'][3].update(status='in_progress',detail='7种策略 × 3字节上限；开发、留出、压力分开；模型读取试验保留失败。')
write_json(ROOT/'research/progress.json',progress)
print('Frozen',p)
