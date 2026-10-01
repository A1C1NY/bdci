"""Self-contained byte-bounded memory mechanism study; standard library only."""
import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import random
import time

POLICIES = ('event_window', 'latest', 'source', 'no_revoke', 'no_version', 'gated', 'protected')
FAMILIES = ('steady', 'update', 'revoke', 'conflict', 'resolve', 'replay')
SOURCES = ('a', 'b')


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def answer_values(values):
    unique = set(x for x in values if x is not None)
    return 'UNKNOWN' if not unique else next(iter(unique)) if len(unique) == 1 else 'CONFLICT'


def oracle(events, query):
    """Independent batch specification, not the policy's streaming reducer."""
    values = []
    for source in SOURCES:
        subset = [e for e in events if e[1] == query and e[2] == source]
        if not subset:
            continue
        version = max(e[3] for e in subset)
        if any(e[0] == 'R' and e[3] == version for e in subset):
            continue
        puts = [e for e in subset if e[0] == 'P' and e[3] == version]
        if puts:
            values.append(puts[-1][4])
    history = {e[4] for e in events if e[0] == 'P' and e[1] == query}
    return answer_values(values), set(values), history


def reduce_event(rows, event, *, revoke=True, version_check=True, collapse=False):
    op, key, source, version, value = event
    source = '*' if collapse else source
    if op == 'R' and not revoke:
        return rows
    index = next((i for i, r in enumerate(rows) if r[:2] == [key, source]), None)
    old = rows[index] if index is not None else None
    if old and version_check:
        if version < old[2] or (version == old[2] and old[3] is None and op == 'P'):
            return rows
    if old and op == 'R' and version < old[2]:
        return rows
    if index is not None:
        rows.pop(index)
    rows.append([key, source, version, None if op == 'R' else value])
    return rows


def retained_memory(events, policy, budget):
    rows, maximum = [], 2
    for event in events:
        if policy == 'event_window':
            rows.append(list(event))
        else:
            reduce_event(rows, event, revoke=policy != 'no_revoke',
                         version_check=policy not in ('latest', 'no_version'), collapse=policy == 'latest')
        while len(encode(rows)) > budget and rows:
            index = 0
            if policy == 'protected':
                index = next((i for i, row in enumerate(rows) if row[3] is not None), 0)
            rows.pop(index)
        maximum = max(maximum, len(encode(rows)))
    return rows, maximum


def read_memory(rows, query, policy):
    if policy == 'event_window':
        reduced = []
        for event in rows:
            reduce_event(reduced, event)
        rows = reduced
    matching = [row for row in rows if row[0] == query]
    if not matching:
        return 'ABSTAIN'
    if policy in ('gated', 'protected') and {r[1] for r in matching} != set(SOURCES):
        return 'ABSTAIN'
    return answer_values(row[3] for row in matching)


def generate(seed, episodes=120):
    rng = random.Random(seed)
    shift = seed >= 10000
    count = 24 if shift else 12
    keys = [f'warehouse_item_{i:02}' if shift else f'k{i:02}' for i in range(count)]
    tasks = []
    for number in range(episodes):
        family = FAMILIES[number % len(FAMILIES)]
        query = rng.choice(keys)
        prefix = 'shipment_code_' if shift else 'x'
        old = prefix + str(rng.randrange(100000, 999999))
        new = prefix + str(rng.randrange(100000, 999999))
        while new == old:
            new = prefix + str(rng.randrange(100000, 999999))
        initial = []
        for key in keys:
            value = old if key == query else prefix + str(rng.randrange(100000, 999999))
            initial.extend([['P', key, source, 1, value] for source in SOURCES])
        rng.shuffle(initial)
        versions = {(key, source): 1 for key in keys for source in SOURCES}
        background = []
        for _ in range(128 if shift else 64):
            key = rng.choice([k for k in keys if k != query])
            source = rng.choice(SOURCES)
            if rng.random() < .16:
                background.append(['R', key, source, versions[key, source], None])
            else:
                versions[key, source] += 1
                background.append(['P', key, source, versions[key, source], prefix + str(rng.randrange(100000,999999))])
        transitions = {
            'steady': [],
            'update': [['P', query, s, 2, new] for s in SOURCES],
            'revoke': [['R', query, s, 1, None] for s in SOURCES],
            'conflict': [['P', query, 'b', 2, new]],
            'resolve': [['P', query, 'b', 2, new], ['R', query, 'b', 2, None]],
            'replay': [['P', query, s, 2, new] for s in SOURCES] + [['P', query, s, 1, old] for s in SOURCES],
        }[family]
        lag = rng.choice([0, 4, 12, 36])
        point = len(background) - lag
        events = initial + background[:point] + transitions + background[point:]
        # Stress replay specifically tests lost watermarks between update and replay.
        if shift and family == 'replay':
            events = initial + transitions[:2] + background + transitions[2:]
        tasks.append({'id': f'{seed}_{number:03}', 'family': family, 'events': events, 'query': query, 'lag': lag})
    return tasks


def score(rows):
    total = len(rows)
    concrete = [r for r in rows if r['expected'] not in ('UNKNOWN', 'CONFLICT')]
    unknown = [r for r in rows if r['expected'] == 'UNKNOWN']
    conflict = [r for r in rows if r['expected'] == 'CONFLICT']
    return {'accuracy': sum(r['predicted'] == r['expected'] for r in rows) / total,
            'stale_rate': sum(r['stale'] for r in rows) / total,
            'abstain_rate': sum(r['predicted'] == 'ABSTAIN' for r in rows) / total,
            'concrete_recall': sum(r['predicted'] == r['expected'] for r in concrete) / max(1, len(concrete)),
            'unknown_accuracy': sum(r['predicted'] == 'UNKNOWN' for r in unknown) / max(1, len(unknown)),
            'conflict_accuracy': sum(r['predicted'] == 'CONFLICT' for r in conflict) / max(1, len(conflict)),
            'false_concrete_conflict_rate': sum(r['predicted'] not in ('UNKNOWN','CONFLICT','ABSTAIN') for r in conflict) / max(1,len(conflict)),
            'mean_bytes': sum(r['serialized_bytes'] for r in rows) / total,
            'max_bytes': max(r['peak_retained_bytes'] for r in rows), 'total': total}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--method', required=True)
    parser.add_argument('--seed', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    policy, size = args.method.rsplit('_b', 1)
    budget = int(size)
    if policy not in POLICIES or budget not in (384,768,1536):
        raise ValueError('Unregistered policy or budget')
    tasks, predictions = generate(args.seed), []
    start = time.perf_counter()
    for task in tasks:
        memory, peak = retained_memory(task['events'], policy, budget)
        prediction = read_memory(memory, task['query'], policy)
        expected, active, history = oracle(task['events'], task['query'])
        predictions.append({'id':task['id'], 'family':task['family'], 'expected':expected,
            'predicted':prediction, 'stale':prediction in history - active,
            'serialized_bytes':len(encode(memory)), 'peak_retained_bytes':peak})
    metrics = score(predictions)
    metrics['wall_seconds'] = time.perf_counter() - start
    result = {'method':args.method, 'seed':args.seed, 'metrics':metrics,
        'family_metrics':{f:score([r for r in predictions if r['family']==f]) for f in FAMILIES},
        'provenance':{'dataset':'source-memory-v1', 'dataset_sha256':hashlib.sha256(encode(tasks)).hexdigest(),
            'budget_bytes':budget,'policy':policy,'split':'stress' if args.seed>=10000 else 'standard',
            'llm_calls':0,'llm_tokens':0}, 'predictions':predictions}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),encoding='utf-8')
    print(json.dumps(metrics))


if __name__ == '__main__':
    main()
