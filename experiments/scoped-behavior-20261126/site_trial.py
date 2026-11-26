"""Second, separately sealed edit format. Keep the first trial's exact policy interpretations."""
import argparse
from collections import Counter
import os
from pathlib import Path

from trial import (LAB, OLD, ROOT, call_model, content_hash, freeze, local_server, locked_output,
                   public_history, read, sealed_text, writer)
from experiments import scoped_sites

OUT = ROOT / 'named-operations'


def labels(design):
    for task, seeds in design['task_seeds'].items():
        for i, seed in enumerate(seeds):
            for side in ('AB' if i % 2 else 'BA'):
                yield task, seed, side, f'{task}/{seed}/{side}'


def setup():
    parent = read(ROOT / 'design.json')
    files = [ROOT / name for name in ('design.json','sealed.json','results.json','trial.py','score.py','evaluate.py')]
    files += [Path(__file__), Path(scoped_sites.__file__)]
    freeze(OUT / 'design.json', dict(model=parent['model'], model_sha256=parent['model_sha256'],
           task_seeds=parent['task_seeds'], files={str(p.relative_to(LAB)): content_hash(p) for p in files},
           change='Only the code edit representation. Reuse exact recorded behavior plans; charge them at full cost.',
           grading=parent['grading'], independent_holdout=False))


def check_design(design, generating=False):
    for path, expected in design['files'].items():
        if generating and Path(path).name in ('results.json','score.py','evaluate.py'):
            continue
        if content_hash(LAB / path) != expected:
            raise ValueError(f'Registered file changed: {path}')
    parent = read(ROOT / 'design.json')
    for name, expected in parent['files'].items():
        if generating and Path(name).name == 'score.py':
            continue
        if content_hash(LAB / name) != expected:
            raise ValueError(f'Original source changed: {name}')


def edit_one(dest, parent, design, state, side, seed, port, audit=False):
    prior = read(parent / 'writer.json')
    def transport(out, policy, role, prompt, packet, schema, call_seed, limit, endpoint):
        if role == 'main-behavior' and not audit:
            key, value = call_model(parent, policy, role, prompt, packet, schema, call_seed, limit, 0, audit=True)
            path = dest / 'calls' / (key + '.json')
            path.parent.mkdir(exist_ok=True)
            if content_hash(parent / 'calls' / path.name) != prior['logs'][key]:
                raise ValueError('Stored reader response changed')
            freeze(path, read(parent / 'calls' / path.name))
            return key, value
        return call_model(out, policy, role, prompt, packet, schema, call_seed, limit, endpoint, audit=audit)

    send = scoped_sites.with_sites(transport)
    def ask(role, prompt, packet, schema, call_seed, limit):
        return send(dest, design, role, prompt, packet, schema, call_seed, limit, port)
    code, record = writer.revise(state['brief'], state['code'], public_history(state, side), state['review'], seed, ask)
    if record['behavior'] != prior['behavior'] or record['calls'][0] != prior['calls'][0]:
        raise ValueError('The reader interpretation differs between the two trials')
    record['logs'] = {key: content_hash(dest / 'calls' / (key + '.json')) for key in record['calls']}
    return code, record


def run():
    os.chdir(LAB)
    design = read(OUT / 'design.json')
    check_design(design, generating=True)
    if content_hash(LAB / design['model']) != design['model_sha256']:
        raise ValueError('Model weights changed')
    seals = {}
    port = 18954
    with local_server(port, design['model']):
        for task, seed, side, label in labels(design):
            state = read(OLD / 'frozen' / (task + '.json'))
            dest = OUT / 'runs' / label
            dest.mkdir(parents=True, exist_ok=True)
            code, record = edit_one(dest, ROOT / 'runs' / label, design, state, side, seed, port)
            signature = sealed_text(dest / 'solution.py', code)
            freeze(dest / 'writer.json', record)
            seals[label] = dict(code=signature, trace=content_hash(dest / 'writer.json'))
            print('sealed', label, flush=True)
    freeze(OUT / 'sealed.json', dict(design=content_hash(OUT / 'design.json'), submissions=seals))


def grade():
    from evaluate import token_usage
    from score import cases, correct, evaluate, old_calls, verify
    design, seal = (read(OUT / name) for name in ('design.json','sealed.json'))
    check_design(design)
    verify(read(ROOT / 'design.json'), read(ROOT / 'sealed.json'))
    if (content_hash(OUT / 'design.json') != seal['design'] or
            set(seal['submissions']) != {label for *_, label in labels(design)}):
        raise ValueError('Require the complete set of published submissions')
    for task, seed, side, label in labels(design):
        dest = OUT / 'runs' / label
        frozen = read(OLD / 'frozen' / (task + '.json'))
        code, record = edit_one(dest, ROOT / 'runs' / label, design, frozen, side, seed, 0, audit=True)
        if (code != (dest / 'solution.py').read_text() or read(dest / 'writer.json') != record or
                seal['submissions'][label] != dict(code=content_hash(dest / 'solution.py'), trace=content_hash(dest/'writer.json'))):
            raise ValueError(f'Cannot reproduce sealed submission: {label}')
    results = {}
    for task, seeds in design['task_seeds'].items():
        bank = cases(task)
        state = read(OLD / 'frozen' / (task + '.json'))
        inputs = [args for args, _ in bank]
        panels = {'domain': list(range(len(bank)))}
        if task == 'upload':
            panels['boundary'] = [inputs.index([n]) for n in (15,16,17)]
        cache, runs, pairs = {}, [], []
        totals = {p: Counter() for p in panels}
        cost = {v: Counter() for v in ('old','new')}
        for seed in seeds:
            correct_rows = {}
            for side in 'AB':
                correctness = {}
                for variant, directory in [('old',OLD),('new',OUT)]:
                    dest = directory / 'runs' / task / str(seed) / side
                    source = (dest / 'solution.py').read_text()
                    calls = old_calls(dest) if variant == 'old' else read(dest / 'writer.json')['calls']
                    cost[variant].update(token_usage(dest, calls))
                    if source not in cache:
                        values = []
                        for start in range(0, len(bank), 100):
                            values.extend(evaluate(source, state['function'], inputs[start:start+100]))
                        if len(values) != len(bank):
                            raise ValueError('Incomplete isolated evaluation')
                        cache[source] = values
                    correctness[variant] = [correct(v, answers[side]) for v, (_, answers) in zip(cache[source], bank)]
                correct_rows[side] = correctness
                for panel, indices in panels.items():
                    counts = Counter()
                    for i in indices:
                        before, after = (correctness[v][i] for v in ('old','new'))
                        counts['kept' if before and after else 'fixed' if after else 'lost' if before else 'still_wrong'] += 1
                    totals[panel].update(counts)
                    runs.append(dict(seed=seed, side=side, panel=panel, counts=dict(counts)))
            for variant in ('old','new'):
                c = Counter()
                for i, (_, answers) in enumerate(bank):
                    kind = 'changed_policy' if answers['A'] != answers['B'] else 'same_policy'
                    c[kind+'_total'] += 1
                    c[kind+'_both_correct'] += all(correct_rows[s][variant][i] for s in 'AB')
                pairs.append(dict(seed=seed, variant=variant, **c))
        results[task] = dict(panels=totals, runs=runs, paired=pairs, writer_usage=cost)
        print(task, {p:dict(c) for p,c in totals.items()}, {v:dict(c) for v,c in cost.items()}, flush=True)
    freeze(OUT / 'results.json', dict(seal=content_hash(OUT / 'sealed.json'), tasks=results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','run','grade'))
    with locked_output(OUT):
        {'prepare':setup, 'run':run, 'grade':grade}[parser.parse_args().action]()
