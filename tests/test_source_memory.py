import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_experiment', ROOT/'experiments/source_memory/experiment.py')
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)


def test_hand_derived_semantics_and_gate():
    a = ['P','k','a',1,'A']; b = ['P','k','b',1,'A']
    cases = [([a,b], 'A'), ([a,b,['P','k','a',2,'B']], 'CONFLICT'),
        ([a,b,['R','k','a',1,None]], 'A'),
        ([a,b,['R','k','a',1,None],['R','k','b',1,None]], 'UNKNOWN'),
        ([a,b,['P','k','a',2,'B'],['R','k','a',2,None]], 'A'),
        ([a,b,['P','k','a',2,'B'],['P','k','b',2,'B'],a,b], 'B'),
        ([['R','k','a',1,None],a,b], 'A')]
    for events, target in cases:
        assert exp.oracle(events,'k')[0] == target
        for policy in ('source','gated','protected','event_window'):
            memory, peak = exp.retained_memory(events,policy,1536)
            assert exp.read_memory(memory,'k',policy) == target
    assert exp.read_memory([['k','a',1,'A']], 'k','source') == 'A'
    assert exp.read_memory([['k','a',1,'A']], 'k','gated') == 'ABSTAIN'
    collision=[a,b,['R','k','b',1,None]]
    assert exp.oracle(collision,'k')[0]=='A'
    memory,_=exp.retained_memory(collision,'latest',1536)
    assert exp.read_memory(memory,'k','latest')=='UNKNOWN'  # Deliberately weak source-blind diagnostic.


def test_budget_and_state_roundtrip():
    import json
    for task in exp.generate(11, 12) + exp.generate(10101, 12):
        for policy in exp.POLICIES:
            for budget in (384,768,1536):
                memory, peak = exp.retained_memory(task['events'],policy,budget)
                assert peak <= budget and len(exp.encode(memory)) <= budget
                restored = json.loads(exp.encode(memory))
                assert exp.read_memory(memory,task['query'],policy) == exp.read_memory(restored,task['query'],policy)


def test_replay_after_eviction_is_not_hidden():
    events = [['P','k','a',1,'A'],['P','k','b',1,'A'],['P','k','a',2,'B'],['P','k','b',2,'B']]
    events += [['P',f'd{i}',s,1,'distractor'] for i in range(20) for s in exp.SOURCES]
    events += [['P','k','a',1,'A'],['P','k','b',1,'A']]
    memory,_ = exp.retained_memory(events,'protected',384)
    assert exp.oracle(events,'k')[0] == 'B'
    assert exp.read_memory(memory,'k','protected') == 'A'  # Known impossibility boundary.


def test_oracle_never_leaks_into_policy_input():
    for task in exp.generate(101,12):
        assert 'answer' not in task and 'expected' not in task
        expected, active, history = exp.oracle(task['events'],task['query'])
        if task['family']=='revoke': assert expected=='UNKNOWN'
        if task['family']=='conflict': assert expected=='CONFLICT'
        if task['family'] in ('steady','update','resolve','replay'):
            assert expected not in ('UNKNOWN','CONFLICT')
        assert active <= history


def test_all_abstain_cannot_win_accuracy():
    rows=[{'expected':'A','predicted':'ABSTAIN','stale':False,'serialized_bytes':2,'peak_retained_bytes':2}]
    result=exp.score(rows)
    assert result['stale_rate']==0 and result['accuracy']==0 and result['abstain_rate']==1
