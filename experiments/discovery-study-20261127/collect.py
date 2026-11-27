"""Export rows.json, drafts.json and the blinded pool.json from stored runs (no model calls).

  python3 -B experiments/discovery-study-20261127/collect.py main    # -> rows.json, drafts.json, pool.json
  python3 -B experiments/discovery-study-20261127/collect.py smoke   # -> smoke/{rows,drafts,pool}.json
Draft behaviour comes from an isolated run per input, as in festival-validation-20261127/assess.py evaluate().
"""
import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from functools import lru_cache

import run
from backend.isolated import run_cases
from backend.structured_output import decode
from experiments.local_transport import read
from experiments.rule_cycle_report import TRACE


@lru_cache(None)
def evaluate(code, function, inputs):
    """Copy of festival-validation-20261127/assess.py evaluate()."""
    if code is None:
        return ['미제출'] * len(inputs)
    jobs = [dict(initial_state=dict(call=function, args=list(x)), events=[]) for x in inputs]
    rows = run_cases(code + TRACE, jobs, 'allocation', hash_seed=0)
    assert len(rows) == len(inputs)
    result = []
    for row in rows:
        actual = row['actual'] or {}
        error = row['error'] or actual.get('exception')
        result.append('보류' if error == 'NotImplementedError' else '실행 오류' if error or
                      type(actual.get('value')) != bool else actual['value'])
    return result


def key(task, text):
    return hashlib.sha256((task + '\n' + text).encode()).hexdigest()[:12]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def collect(phase):
    root = run.OUT / 'smoke' if phase == 'smoke' else run.OUT
    call = lambda k: read(root / 'calls' / (k + '.json'))
    tokens = lambda keys: sum(call(k)['usage']['total_tokens'] for k in keys)
    rows, drafts, health = [], [], Counter()
    for task, meta, seed in run.cases(phase):
        unit = root / 'runs' / task / str(seed)
        preps = {arm: read(unit / arm / 'prepared.json') for arm in run.ARMS}
        failed = {arm for arm, p in preps.items() if p['status'] == 'draft_failed'}
        assert failed in (set(), set(run.ARMS)), (task, seed, failed)
        draft_keys = {p['calls'][0] for p in preps.values()}
        assert len(draft_keys) == 1, (task, seed, 'arms did not share the draft call')
        draft_key = draft_keys.pop()
        inputs = tuple(map(tuple, meta['inputs']))
        if failed:
            record = call(draft_key)
            parsed = decode(record['text'], run.draft_schema()) if record['finish_reason'] == 'stop' else None
            code = parsed['code'] if parsed else None
            drafts.append(dict(task=task, seed=seed, status='draft_failed', tokens=tokens([draft_key]),
                               code_sha256=hashlib.sha256(code.encode()).hexdigest() if code is not None else '',
                               behavior=[]))
            continue
        packets = {arm: read(unit / arm / 'handoff.json') for arm in run.ARMS}
        codes = {p['code'] for p in packets.values()}
        assert len(codes) == 1, (task, seed, 'arms reviewed different drafts')
        code = codes.pop()
        behavior = evaluate(code, meta['function'], inputs)
        assert all(v is True or v is False or v in ('보류', '실행 오류') for v in behavior), behavior
        drafts.append(dict(task=task, seed=seed, status='ok', tokens=tokens([draft_key]),
                           code_sha256=hashlib.sha256(code.encode()).hexdigest(), behavior=behavior))
        for arm in run.ARMS:
            packet, prep = packets[arm], preps[arm]
            reviews = packet['calls'][1:]
            assert packet['calls'][0] == draft_key and prep['calls'][:len(packet['calls'])] == packet['calls']
            agenda_calls = prep['calls'][len(packet['calls']):]
            schema = run.review_schema(run.MODE[arm])
            invalid = 0
            for k in reviews:
                r = call(k)
                invalid += (decode(r['text'], schema) if r['finish_reason'] == 'stop' else None) is None
            if prep['status'] in ('ready', 'no_open_decisions'):
                stored = read(unit / arm / 'agenda.json')['agenda']['calls']
                health['agenda_log_matches_agenda_json' if stored == agenda_calls else 'agenda_log_differs'] += 1
            rows.append(dict(task=task, seed=seed, arm=arm, status=prep['status'], raw=packet['questions'],
                             sent=prep['questions'] if prep['status'] in ('ready', 'no_open_decisions') else [],
                             review_calls=len(reviews), review_invalid=invalid,
                             tokens_review=tokens(reviews), tokens_agenda=tokens(agenda_calls)))
    pool = {}
    for r in rows:
        for q in r['raw'] + r['sent']:
            k = key(r['task'], q)
            assert pool.get(k, dict(task=r['task'], question=q)) == dict(task=r['task'], question=q), ('key collision', k)
            pool[k] = dict(task=r['task'], question=q)
    pool = dict(sorted(pool.items()))
    write(root / 'rows.json', rows)
    write(root / 'drafts.json', drafts)
    write(root / 'pool.json', pool)
    return rows, drafts, pool, health


def selfcheck(phase, rows, drafts, pool, health):
    units = sum(1 for _ in run.cases(phase))
    ok = {(d['task'], d['seed']) for d in drafts if d['status'] == 'ok'}
    assert len(drafts) == units, len(drafts)
    by_unit = Counter((r['task'], r['seed']) for r in rows)
    assert set(by_unit) == ok and all(n == 4 for n in by_unit.values())
    assert len({(r['task'], r['seed'], r['arm']) for r in rows}) == len(rows)
    metas = {t: m for t, m, _ in run.cases(phase)}
    assert all(len(d['behavior']) == len(metas[d['task']]['inputs']) for d in drafts if d['status'] == 'ok')
    assert all(key(r['task'], q) in pool for r in rows for q in r['raw'] + r['sent'])
    assert all(set(v) == {'task', 'question'} for v in pool.values())
    print('drafts', len(drafts), 'ok', len(ok), 'failed', len(drafts) - len(ok), '| rows', len(rows), '| pool', len(pool))
    print('health', dict(health))
    for arm in run.ARMS:
        sub = [r for r in rows if r['arm'] == arm]
        print(arm, dict(Counter(r['status'] for r in sub)), 'review_calls', sum(r['review_calls'] for r in sub),
              'invalid', sum(r['review_invalid'] for r in sub), 'raw_q', sum(len(r['raw']) for r in sub),
              'sent_q', sum(len(r['sent']) for r in sub), 'tok_review', sum(r['tokens_review'] for r in sub),
              'tok_agenda', sum(r['tokens_agenda'] for r in sub))
    print('draft tokens', sum(d['tokens'] for d in drafts))
    test = subprocess.run([sys.executable, '-B', str(run.OUT / 'analyze.py'), 'selftest'], capture_output=True, text=True)
    assert test.returncode == 0 and 'selftest ok' in test.stdout, test.stdout + test.stderr
    print('analyze.py selftest ok')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['main', 'smoke'])
    phase = parser.parse_args().phase
    selfcheck(phase, *collect(phase))


if __name__ == '__main__':
    main()
