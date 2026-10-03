"""Create predeclared study plans and bounded design-audit assignment."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import write_json

policies=['event_window','latest','source','no_revoke','no_version','gated','protected']
splits={'dev':[11,23,37], 'holdout':[101,211,307,401,503,607,709,809,907,1009],
        'stress':[10101,10211,10307,10401,10503,10607,10709,10809,10907,11009]}
for split,seeds in splits.items():
    for budget in (384,768,1536):
        plan={'schema_version':1,'title':f'Source memory {split}, {budget} bytes',
            'question':'How do explicit invalidation, source coverage and byte-limited eviction affect stale answers?',
            'hypothesis':'Completeness gating may reduce false concrete answers at a cost in recall; protecting tombstones may have mixed effects.',
            'experiment':'experiment.py','methods':[f'{p}_b{budget}' for p in policies],
            'baseline':f'source_b{budget}','seeds':seeds,'primary_metric':'stale_rate','direction':'minimize',
            'timeout_seconds':60,'max_attempts':1,
            'limitations':['Synthetic event semantics, not natural-language extraction or a real-world benchmark.',
                'Byte ceiling is retained serialized state, not Python heap or model tokenizer cost.',
                'Lower stale rate alone is not improvement: accuracy, coverage and abstention must be reported.',
                'Stress changes generator parameters; it does not establish external semantic generalization.',
                'Version watermark eviction permits stale replay even with completeness gating.'],
            'references':[{'title':'LongMemEval','url':'https://arxiv.org/abs/2410.10813','note':'Related work only; no dataset or reported scores reused.'}]}
        write_json(ROOT/f'experiments/source_memory/{split}_b{budget}.json',plan)
task={'schema_version':1,'task_id':'source_protocol_audit_001','model_alias':'kimi',
    'research_question':'Under byte-bounded memory, what can source coverage and revocation actually guarantee?',
    'objective':'Audit only the supplied protocol for one fairness flaw and one overclaim risk. Give at most two actionable corrections before holdout freeze. Do not invent experiments, results or citations.',
    'boundaries':['Do not replace the research direction or select methods.','Treat this as synthetic controlled evaluation, not novel general agent capability.'],
    'acceptance_checks':['Supervisor verifies suggestions against executable semantics.','No held-out results are available or requested.'],
    'context_files':['../../experiments/source_memory/protocol.md','../../research/memory_v3/related_work.md'],
    'evidence_ids':['protocol_v1','related_work'],'max_output_tokens':3072}
write_json(ROOT/'config/tasks/source_protocol_audit.json',task)
progress=json.loads((ROOT/'research/progress.json').read_text(encoding='utf-8'))
progress.update(team='能工智人',status='protocol_design',next_action='审核手算案例与协议，测试实现后冻结实验，再运行留出与压力测试。',
    note='新的字节预算研究正在执行；旧 v2 示例与本轮研究分别记录。')
progress['stages'][1].update(status='completed',detail='核查 LongMemEval、A-MEM、Mem0、RECON；收窄贡献，不宣称发明记忆更新。')
progress['stages'][2].update(status='in_progress',detail='明确版本、撤销、冲突、字节计费、固定拆分及拒答指标；提交 Kimi 有限审查。')
write_json(ROOT/'research/progress.json',progress)
print('Created 9 fixed plans and one bounded protocol-audit assignment.')
