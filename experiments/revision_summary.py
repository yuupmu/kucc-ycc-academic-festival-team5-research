"""Describe sealed runs using the recorded grades, paired by seed and input."""
from collections import Counter, defaultdict

from experiments.monitor_cycles import read
from experiments.rule_edits import inspect_draft


def case_key(row):
    return row['id'] if 'id' in row else (row['age_seconds'], row['until_start_seconds'])


def pair_changes(before, after):
    old = {case_key(r):r for r in before}
    new = {case_key(r):r for r in after}
    if old.keys() != new.keys() or len(old) != len(before) or len(new) != len(after):
        raise ValueError('같은 채점 입력끼리만 대조할 수 있습니다.')
    corrected = regressed = changed = 0
    for key, b in old.items():
        a = new[key]
        if a['expected'] != b['expected']:
            raise ValueError('같은 입력의 기대값이 다릅니다.')
        corrected += a['passed'] and not b['passed']
        regressed += b['passed'] and not a['passed']
        changed += (a['actual'], a['error']) != (b['actual'], b['error'])
    return dict(corrected=corrected, regressed=regressed, changed=changed)


def age_changes_answer(rows):
    by_start = defaultdict(set)
    for row in rows:
        if row['error'] is None:
            by_start[row['until_start_seconds']].add(row['actual'])
    return any(len(values) > 1 for values in by_start.values())


DEFAULT_PAIRS = [('direct','abcd'), ('self_final','abcd'), ('direct','self_final'),
                 ('direct','B'), ('B','C'), ('C','abcd')]


def summarize(out, pairs_to_compare=DEFAULT_PAIRS, include_stages=True):
    design = read(out/'design.json')
    previously, fresh = design['previously_used'], design['new']
    seeds, arms = previously + fresh, design['arms']
    submissions = {(r['seed'],r['arm']):r for r in read(out/'submissions.json')}
    results = {(r['seed'],r['arm']):r for r in read(out/'results.json')}
    cases = {}
    for seed in seeds:
        for arm in arms:
            key = (seed,arm)
            report = read(out/str(seed)/f'{arm}-score.json')
            if report['sha256'] != submissions[key]['sha256']:
                raise ValueError('채점 대상과 제출 코드가 다릅니다.')
            cases[key] = {'official':report['report']['results'], 'transfer':report['transfer']}
            for kind, prefix in [('official',''), ('transfer','transfer_')]:
                rows = cases[key][kind]
                if (len(rows) != results[key][prefix+'total']
                        or sum(r['passed'] for r in rows) != results[key][prefix+'score']):
                    raise ValueError('개별 판정과 결과 합계가 다릅니다.')
    groups = {}
    for name, group in [('previous', previously), ('fresh',fresh), ('all',seeds)]:
        totals, pairs = {}, {}
        for arm in arms:
            total = Counter()
            for seed in group:
                key = (seed,arm)
                row = results[key]
                total.update({k: row[k] for k in ('score','total','transfer_score','transfer_total','calls','tokens')})
                unused = inspect_draft(submissions[key]['code']).get('unread_parameters')
                total['age_read_seeds'] += unused is not None and 'age_seconds' not in unused
                total['age_sensitive_seeds'] += age_changes_answer(cases[key]['transfer'])
                total['case_errors'] += sum(r['error'] is not None for rows in cases[key].values() for r in rows)
            totals[arm] = dict(total)
        for old, new in pairs_to_compare:
            pair = {}
            for kind in ('official','transfer'):
                count = Counter()
                for seed in group:
                    delta = pair_changes(cases[seed,old][kind], cases[seed,new][kind])
                    count.update(delta)
                    count['changed_seeds'] += delta['changed'] > 0
                    net = delta['corrected'] - delta['regressed']
                    count['wins' if net > 0 else 'losses' if net < 0 else 'ties'] += 1
                pair[kind] = dict(count)
            pairs[old+'->'+new] = pair
        groups[name] = dict(seeds=group, totals=totals, paired=pairs)
    stages = {}
    for arm in ('self','serial') if include_stages else ():
        by_role = defaultdict(Counter)
        for seed in seeds:
            for step in read(out/str(seed)/arm/'changes.json'):
                count = by_role[step['role']]
                count[step['state']] += 1
                count['emitted_code_changed'] += step['after_sha256'] != step['before_sha256']
                count.update(r['status'] for r in step['edits'].values())
        stages[arm] = {role:dict(counts) for role,counts in by_role.items()}
    return dict(groups=groups, stages=stages)
