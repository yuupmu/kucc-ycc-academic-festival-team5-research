"""Open the evaluator only after every submission and owner exchange has been sealed."""
import ast
import difflib
from collections import Counter
from trial import LAB, NAMES, OUT, design, digest, freeze, read, sha
from backend.isolated import run_cases
from experiments.rule_cycle_report import TRACE

DEFER = 'NotImplementedError'
CASES = LAB/'experiments/transfer100-20261126/evaluator/cases.json'


def expected(x, boundary):
    return boundary if x == 16 else 0 < x < 16


def equivalent_domain(sources):
    # An independent check on the actual submitted source: within this language a branch
    # predicate is constant between consecutive literal thresholds, including the two tails.
    values = {0, 16}
    for code in sources:
        module = ast.parse(code)
        assert len(module.body) == 1
        fn = module.body[0]
        assert isinstance(fn, ast.FunctionDef) and fn.name == 'allow_upload' and len(fn.args.args) == 1
        assert not fn.decorator_list and not fn.args.defaults
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.stmt) and stmt is not fn:
                assert isinstance(stmt, (ast.If, ast.Return, ast.Raise))
                if isinstance(stmt, ast.Raise):
                    assert isinstance(stmt.exc, ast.Call) and stmt.exc.func.id == DEFER
                    assert all(isinstance(a, ast.Constant) for a in stmt.exc.args)
                if isinstance(stmt, ast.Return):
                    assert isinstance(stmt.value, ast.Constant) and type(stmt.value.value) is bool
                if isinstance(stmt, ast.If):
                    assert isinstance(stmt.test, ast.Compare)
                    assert all(isinstance(o, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for o in stmt.test.ops)
                    for arg in [stmt.test.left, *stmt.test.comparators]:
                        if isinstance(arg, ast.Name):
                            assert arg.id == fn.args.args[0].arg
                        else:
                            integer = ast.literal_eval(arg)
                            assert type(integer) is int
                            values.add(integer)
    points = sorted(values)
    return sorted({points[0]-1, points[-1]+1, *points, *(a+1 for a,b in zip(points,points[1:]) if a+1<b)})


def execute(source, xs):
    jobs = [dict(initial_state=dict(call='allow_upload', args=[x]), events=[]) for x in xs]
    rows = run_cases(source+TRACE, jobs, 'allocation', hash_seed=0)
    result = {}
    for x, row in zip(xs, rows):
        actual = row['actual'] or {}
        error = row['error'] or actual.get('exception')
        value = actual.get('value')
        result[x] = error if error else (value if type(value) is bool else 'invalid return: '+repr(value))
    assert len(result) == len(xs)
    return result


def collect():
    config = design()
    first, questions, final = (read(OUT/path) for path in ('initial-seal.json', 'question-seal.json', 'final-seal.json'))
    assert first['scope'] == sha(OUT/'scope.json') and first['design'] == sha(OUT/'design.json')
    assert questions['initial'] == sha(OUT/'initial-seal.json') and final['questions'] == sha(OUT/'question-seal.json')
    assert final['owner'] == sha(OUT/'owner-delivery.json')
    owner = read(OUT/'owner-delivery.json')
    assert owner['requests'] == final['questions']
    receipts, programs, logs, all_keys = {}, {}, {}, []
    for name in NAMES:
        folder = OUT/name
        assert questions['requests'][name] == sha(folder/'question.json')
        request = read(folder/'question.json')
        receipts[name] = request['question']
        for stage in dict.fromkeys(['initial', final['snapshots'][name]['stage']]):
            path = folder/stage
            seal = first['snapshots'][name] if stage == 'initial' else final['snapshots'][name]
            assert seal['code'] == sha(path/'solution.py') and seal['trace'] == sha(path/'trace.json')
            if stage == final['snapshots'][name]['stage']:
                assert final['snapshots'][name]['code'] == seal['code'] and final['snapshots'][name]['trace'] == seal['trace']
            label = name+'/'+stage
            programs[label] = (path/'solution.py').read_text()
            keys = read(path/'trace.json')['calls'] + (request['calls'] if stage == 'initial' else [])
            logs[label] = keys
            all_keys.extend(keys)
    assert set(all_keys) == set(final['calls'])
    records = {}
    for key in set(all_keys):
        path = OUT/'calls'/(key+'.json')
        assert final['calls'][key] == sha(path)
        raw = read(path)
        assert digest([raw['role'], raw['request']]) == key and raw['model'] == config['model']
        assert raw['request']['seed'] == config['seed']
        records[key] = raw
    def cost(keys):
        return dict(calls=len(keys), **{key: sum(records[k]['usage'][key] for k in keys)
                                       for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
    return programs, receipts, owner, dict(by_stage={k: cost(v) for k,v in logs.items()},
        unique=cost(records), roles=dict(Counter(rec['role'] for rec in records.values())))


def assess():
    programs, questions, owner, cost = collect()
    items = [r for r in read(CASES) if r['task'] == 'upload']
    assert len(items) == 20 and all(expected(r['args'][0], True) is r['expected'] for r in items)
    controls = sorted({*range(-2, 34), -1000000, 1000000})
    witnesses = equivalent_domain(programs.values())
    xs = sorted({*controls, *witnesses, *(r['args'][0] for r in items)})
    actual = {k: execute(code, xs) for k,code in programs.items()}
    measures = {}
    for k, results in actual.items():
        name, stage = k.split('/')
        boundary = {'include': True, 'exclude': False, 'unmentioned': DEFER if stage=='initial' else False}[name]
        wrong = [x for x in xs if results[x] != expected(x, boundary)]
        measures[k] = dict(policy_20=sum(results[r['args'][0]] == expected(r['args'][0], boundary) for r in items),
            official_inclusive_20=sum(results[r['args'][0]] == r['expected'] for r in items),
            controls_38=sum(x not in wrong for x in controls), integer_classes_all=all(x not in wrong for x in witnesses),
            wrong=wrong, deferred=[x for x in xs if results[x] == DEFER],
            neighbors=[results[x] for x in (15, 16, 17)])
    a, b, m = (n+'/initial' for n in NAMES)
    f = 'unmentioned/after-reply'
    def differences(one, two):
        return [x for x in xs if actual[one][x] != actual[two][x]]
    comparisons = dict(direct_answers=differences(a,b))
    if f in programs:
        comparisons.update(before_after_follow=differences(m,f), final_vs_direct_exclude=differences(f,b),
                           changed_lines=list(difflib.unified_diff(programs[m].splitlines(), programs[f].splitlines(),
                                                                    n=0, lineterm='')))
    protocol_ok = (not questions['include'] and not questions['exclude'] and bool(questions['unmentioned'])
                   and owner['focus'].get('unmentioned') == 'one equality-only question' and set(owner['replies']) == {'unmentioned'})
    passed = bool(protocol_ok and f in programs and all(r['integer_classes_all'] for r in measures.values())
                  and comparisons['direct_answers'] == comparisons['before_after_follow'] == [16])
    report = dict(seal=sha(OUT/'final-seal.json'), passed=passed, questions=questions, owner=owner,
                  policy_reference='inclusive / exclusive / abstention until the exclusive follow-up',
                  costs=cost, checks=measures, differences=comparisons, controls=controls, integer_witnesses=witnesses,
                  tested_inputs=xs, outputs={k:[v[x] for x in xs] for k,v in actual.items()})
    freeze(OUT/'results.json', report)
    print('SUCCESS', passed, 'Questions', questions, 'Checks', measures, 'Differences', comparisons, 'Tokens', cost)


if __name__ == '__main__':
    assess()
