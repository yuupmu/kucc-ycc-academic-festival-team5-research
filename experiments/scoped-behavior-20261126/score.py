"""Offline comparison of every sealed submission against the same archived baseline."""
from collections import Counter
import itertools
import json

from trial import LAB, OLD, ROOT, call_model, content_hash, freeze, public_history, read, writer
from score_pairs import correct, evaluate


def cases(task):
    if task == 'upload':
        return [([n], {'A': 0 < n <= 16, 'B': 0 < n < 16}) for n in range(-2, 34)]
    result = []
    readings = [('x', 0), ('x', 1), ('y', 0), ('y', 1)]
    for length in range(5):
        for sequence in itertools.product(readings, repeat=length):
            result.append(([list(sequence)], {'A': dict(reversed(sequence)), 'B': dict(sequence)}))
    return result


def old_calls(dest):
    return [attempt['call'] for attempt in read(dest / 'submission.json')['attempts']]


def usage(dest, calls):
    totals = Counter(calls=len(calls))
    for key in calls:
        totals.update(read(dest / 'calls' / (key + '.json'))['usage'])
    return {k: totals[k] for k in ('calls', 'prompt_tokens', 'completion_tokens', 'total_tokens')}


def verify(design, seal):
    if content_hash(ROOT / 'design.json') != seal['design']:
        raise ValueError('Design changed')
    for path, checksum in design['files'].items():
        if content_hash(LAB / path) != checksum:
            raise ValueError(f'Frozen input changed: {path}')
    expected = {f'{task}/{seed}/{side}' for task, seeds in design['task_seeds'].items()
                for seed in seeds for side in design['sides']}
    if set(seal['submissions']) != expected:
        raise ValueError('Every submission is required before grading')
    historical = read(OLD / 'sealed-all.json')['submissions']
    for label, digests in seal['submissions'].items():
        dest, old = (directory / 'runs' / label for directory in (ROOT, OLD))
        if content_hash(old / 'solution.py') != historical[label]:
            raise ValueError(f'Historical submission changed: {label}')
        if digests != dict(source=content_hash(dest / 'solution.py'), record=content_hash(dest / 'writer.json')):
            raise ValueError(f'Submission changed: {label}')
        record = read(dest / 'writer.json')
        for key, checksum in record['logs'].items():
            if content_hash(dest / 'calls' / (key + '.json')) != checksum:
                raise ValueError(f'Raw model call changed: {label}')
        task, seed, side = label.split('/')
        state = read(OLD / 'frozen' / (task + '.json'))
        history = public_history(state, side)

        def replay(role, prompt, packet, schema, call_seed, limit):
            return call_model(dest, design, role, prompt, packet, schema, call_seed, limit, 0, audit=True)

        code, trace = writer.revise(state['brief'], state['code'], history, state['review'], int(seed), replay)
        if code != (dest / 'solution.py').read_text() or {**trace, 'logs': record['logs']} != record:
            raise ValueError(f'Could not reconstruct submitted code: {label}')
        old_first = read(old / 'calls' / (old_calls(old)[0] + '.json'))['request']
        new_first = read(dest / 'calls' / (record['attempts'][0]['call'] + '.json'))['request']
        old_packet, new_packet = (json.loads(r['messages'][1]['content']) for r in (old_first, new_first))
        for field in ('brief', 'code', 'dialogue', 'review', 'evidence', 'pending'):
            if old_packet[field] != new_packet[field]:
                raise ValueError(f'Writer inputs differ: {label} {field}')
        for field in ('model', 'temperature', 'top_p', 'top_k', 'seed', 'chat_template_kwargs', 'response_format'):
            if old_first[field] != new_first[field]:
                raise ValueError(f'Sampling or edit format differs: {label} {field}')


def main():
    design, seal = (read(ROOT / name) for name in ('design.json', 'sealed.json'))
    verify(design, seal)
    reports = {}
    for task, seeds in design['task_seeds'].items():
        state = read(OLD / 'frozen' / (task + '.json'))
        bank = cases(task)
        inputs = [args for args, _ in bank]
        cache, panel_counts, costs, pairs, runs = {}, {}, {'old': Counter(), 'new': Counter()}, [], []
        for seed in seeds:
            by_side = {}
            for side in design['sides']:
                label = f'{task}/{seed}/{side}'
                observed = {}
                for variant, directory in [('old', OLD), ('new', ROOT)]:
                    dest = directory / 'runs' / label
                    calls = old_calls(dest) if variant == 'old' else read(dest / 'writer.json')['calls']
                    costs[variant].update(usage(dest, calls))
                    source = (dest / 'solution.py').read_text()
                    if source not in cache:
                        cache[source] = []
                        for start in range(0, len(inputs), 100):
                            cache[source].extend(evaluate(source, state['function'], inputs[start:start+100]))
                        if len(cache[source]) != len(inputs):
                            raise ValueError('Evaluator did not return one result per input')
                    observed[variant] = cache[source]
                by_side[side] = observed
                for panel, indices in [('domain', range(len(bank)))] + (
                        [('boundary', [inputs.index([n]) for n in (15, 16, 17)])] if task == 'upload' else []):
                    counts = Counter()
                    for i in indices:
                        ok = [correct(observed[v][i], bank[i][1][side]) for v in ('old','new')]
                        counts['kept' if all(ok) else 'fixed' if ok[1] else 'lost' if ok[0] else 'still_wrong'] += 1
                    runs.append(dict(seed=seed, side=side, panel=panel, counts=dict(counts)))
                    panel_counts.setdefault(panel, Counter()).update(counts)
            for variant in ('old', 'new'):
                counts = Counter()
                for i, (_, answers) in enumerate(bank):
                    kind = 'changed_policy' if answers['A'] != answers['B'] else 'same_policy'
                    counts[kind + '_total'] += 1
                    counts[kind + '_both_correct'] += all(correct(by_side[s][variant][i], answers[s]) for s in 'AB')
                pairs.append(dict(seed=seed, variant=variant, **counts))
        reports[task] = dict(panels={p: dict(c) for p, c in panel_counts.items()}, per_submission=runs,
                             paired=pairs, writer_usage={v: dict(c) for v, c in costs.items()})
    freeze(ROOT / 'results.json', dict(seal=content_hash(ROOT / 'sealed.json'), tasks=reports))
    for task, report in reports.items():
        print(task, report['panels'], report['writer_usage'])


if __name__ == '__main__':
    main()
