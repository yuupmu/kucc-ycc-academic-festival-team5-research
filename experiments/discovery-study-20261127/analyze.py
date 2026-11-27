"""Pre-registered analysis of the discovery study. Fixed before any model call; see PROTOCOL.md.

Inputs (same folder): design.json, rows.json, drafts.json, labels-A.json, labels-B.json
Output: analysis.json and a Markdown summary on stdout.  `python3 analyze.py selftest` checks the arithmetic.
"""
import hashlib
import itertools
import json
import random
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
ARMS = ('self1', 'ind1', 'same3', 'split3')
STAGES = ('raw', 'sent')
BOOT, BOOT_SEED = 10000, 20261127


def key(task, text):
    """Same de-identified key as festival-validation owner.key: the judge never sees arm or seed."""
    return hashlib.sha256((task + '\n' + text).encode()).hexdigest()[:12]


def mean(values):
    return sum(values) / len(values) if values else None


def bootstrap(values):
    """Percentile 95% interval of the mean, resampling tasks."""
    if not values:
        return None
    rng, k = random.Random(BOOT_SEED), len(values)
    stats = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(BOOT))
    return [stats[int(.025 * BOOT)], stats[int(.975 * BOOT) - 1]]


def sign_flip_p(diffs):
    """Exact two-sided sign-flip permutation test on task-level paired differences."""
    observed, hits = abs(sum(diffs)), 0
    for signs in itertools.product((1, -1), repeat=len(diffs)):
        hits += abs(sum(s * d for s, d in zip(signs, diffs))) >= observed - 1e-12
    return hits / 2 ** len(diffs)


def holm(ps):
    adjusted, running = {}, 0.0
    for rank, name in enumerate(sorted(ps, key=ps.get)):
        running = max(running, min(1.0, (len(ps) - rank) * ps[name]))
        adjusted[name] = running
    return adjusted


def kappa(pairs):
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    return None if chance == 1 else (agree - chance) / (1 - chance)


def analyze(design, rows, drafts, label_a, label_b):
    # Judges may attach a one-line reason: {key: {'labels': [...], 'reason': ...}} or plain {key: [...]}.
    label_a, label_b = ({k: v['labels'] if isinstance(v, dict) else v for k, v in lab.items()} for lab in (label_a, label_b))
    tasks = design['tasks']
    hidden = [t for t, m in tasks.items() if m['kind'] == 'hidden']
    control = [t for t, m in tasks.items() if m['kind'] == 'complete']
    seeds = design['seeds']
    draft_of = {(d['task'], d['seed']): d for d in drafts}
    valid = {u for u, d in draft_of.items() if d['status'] == 'ok'}
    row_of = {(r['task'], r['seed'], r['arm']): r for r in rows}
    missing = [(t, s, a) for (t, s) in sorted(valid) for a in ARMS if (t, s, a) not in row_of]
    if missing or len(draft_of) != len(tasks) * len(seeds):
        raise SystemExit(f'incomplete data: {len(draft_of)} drafts, missing rows {missing[:5]}')
    unlabeled = sorted({key(r['task'], q) for r in rows for st in STAGES for q in r[st]} - (label_a.keys() & label_b.keys()))
    if unlabeled:
        raise SystemExit(f'{len(unlabeled)} questions lack a label from both judges: {unlabeled[:5]}')

    def tags(task, question, mode):
        a, b = set(label_a[key(task, question)]), set(label_b[key(task, question)])
        chosen = {'both': a & b, 'either': a | b, 'A': a, 'B': b}[mode]
        return chosen & {d['id'] for d in tasks[task]['decisions']}

    def units(task):
        return [s for s in seeds if (task, s) in valid]

    def recall(arm, task, stage, mode):
        hits = sum(len(set().union(*[tags(task, q, mode) for q in row_of[task, s, arm][stage]]))
                   for s in units(task))
        return hits / (len(tasks[task]['decisions']) * len(units(task)))

    used = [t for t in hidden if units(t)]
    patterns = sorted({tasks[t]['pattern'] for t in used})
    result = dict(valid_units=len(valid), dropped_units=sorted(map(list, set(draft_of) - valid)),
                  hidden_tasks=used, control_tasks=[t for t in control if units(t)], recall={}, contrasts={})
    for mode in ('both', 'either', 'A', 'B'):
        for stage in STAGES:
            name = f'{stage}/{mode}'
            per_task = {arm: {t: recall(arm, t, stage, mode) for t in used} for arm in ARMS}
            result['recall'][name] = {arm: dict(mean=mean(list(v.values())), ci95=bootstrap(list(v.values())), by_task=v)
                                      for arm, v in per_task.items()}
            block = {}
            for c in design['contrasts']:
                diffs = [per_task[c['to']][t] - per_task[c['from']][t] for t in used]
                by_pattern = [mean([per_task[c['to']][t] - per_task[c['from']][t] for t in used if tasks[t]['pattern'] == p])
                              for p in patterns]
                block[c['id']] = dict(diff=mean(diffs), ci95=bootstrap(diffs), p=sign_flip_p(diffs),
                                      tasks_up=sum(d > 1e-12 for d in diffs), tasks_down=sum(d < -1e-12 for d in diffs),
                                      tasks_tie=sum(abs(d) <= 1e-12 for d in diffs), pattern_p=sign_flip_p(by_pattern))
            for cid, adjusted in holm({cid: v['p'] for cid, v in block.items()}).items():
                block[cid]['p_holm'] = adjusted
            result['contrasts'][name] = block

    # Pre-registered primary reading: raw questions, labels both judges agree on, Holm over the three contrasts.
    result['primary'] = {cid: dict(v, verdict='supported' if v['p_holm'] < .05 and v['diff'] > 0 else
                                   'reversed' if v['p_holm'] < .05 and v['diff'] < 0 else 'not distinguished')
                         for cid, v in result['contrasts']['raw/both'].items()}

    def per_unit(arm, pool, value):
        return mean([value(row_of[t, s, arm], t) for t in pool for s in units(t)])

    result['questions'] = {arm: dict(
        raw_per_unit=per_unit(arm, used, lambda r, t: len(r['raw'])),
        off_target_per_unit=per_unit(arm, used, lambda r, t: sum(not tags(t, q, 'both') for q in r['raw'])),
        sent_per_unit=per_unit(arm, used, lambda r, t: len(r['sent'])),
        control_raw_per_unit=per_unit(arm, control, lambda r, t: len(r['raw'])),
        control_units_with_question=per_unit(arm, control, lambda r, t: bool(r['raw'])),
        control_sent_per_unit=per_unit(arm, control, lambda r, t: len(r['sent'])),
        tokens_review_per_unit=per_unit(arm, list(tasks), lambda r, t: r['tokens_review']),
        tokens_agenda_per_unit=per_unit(arm, list(tasks), lambda r, t: r['tokens_agenda']),
        status=dict(Counter(row_of[t, s, arm]['status'] for t in tasks for s in units(t))),
    ) for arm in ARMS}

    at_decision, public = Counter(), Counter()
    for t in tasks:
        meta = tasks[t]
        targets = [d['input'] for d in meta['decisions']]
        for s in units(t):
            for x, got in zip(meta['inputs'], draft_of[t, s]['behavior']):
                if x in targets:
                    at_decision['asserted' if isinstance(got, bool) else 'deferred' if got == '보류' else 'error'] += 1
                else:
                    public['correct' if got is (x in meta['public_true']) else 'wrong'] += 1
    result['drafts'] = dict(at_hidden_decisions=dict(at_decision), on_public_inputs=dict(public))

    pool = {(r['task'], q) for r in rows if r['task'] in used for st in STAGES for q in r[st]}
    pairs = [(d['id'] in label_a[key(t, q)], d['id'] in label_b[key(t, q)]) for t, q in sorted(pool) for d in tasks[t]['decisions']]
    result['judges'] = dict(questions=len(pool), pairs=len(pairs), agreement=mean([a == b for a, b in pairs]), kappa=kappa(pairs),
                            a_yes=sum(a for a, _ in pairs), b_yes=sum(b for _, b in pairs))
    return result


def render(result):
    def pct(v):
        return '—' if v is None else f'{100 * v:.0f}%'

    def ci(v):
        return '—' if v is None else f'{100 * v[0]:.0f}~{100 * v[1]:.0f}%'
    lines = [f"유효 단위 {result['valid_units']} · 숨은 결정 과제 {len(result['hidden_tasks'])}개 · 대조 과제 {len(result['control_tasks'])}개", '',
             '| 조건 | 발견율(1차) | 95% 구간 | 전달율 | 질문/단위 | 과녁 밖 질문/단위 | 대조 과제에서 질문한 단위 | 검토 토큰/단위 |',
             '|---|---|---|---|---|---|---|---|']
    for arm in ARMS:
        raw, sent, q = result['recall']['raw/both'][arm], result['recall']['sent/both'][arm], result['questions'][arm]
        lines.append(f"| {arm} | {pct(raw['mean'])} | {ci(raw['ci95'])} | {pct(sent['mean'])} | {q['raw_per_unit']:.2f} | "
                     f"{q['off_target_per_unit']:.2f} | {pct(q['control_units_with_question'])} | {q['tokens_review_per_unit']:.0f} |")
    lines += ['', '| 비교 | 발견율 차이 | 95% 구간 | 과제 ↑/↓/= | p | Holm p | 유형 단위 p | 판정 |', '|---|---|---|---|---|---|---|---|']
    for cid, v in result['primary'].items():
        lines.append(f"| {cid} | {100 * v['diff']:+.0f}%p | {100 * v['ci95'][0]:+.0f}~{100 * v['ci95'][1]:+.0f}%p | "
                     f"{v['tasks_up']}/{v['tasks_down']}/{v['tasks_tie']} | {v['p']:.4f} | {v['p_holm']:.4f} | {v['pattern_p']:.4f} | {v['verdict']} |")
    j, d = result['judges'], result['drafts']
    lines += ['', f"판정자 일치: 질문 {j['questions']}개 · 판정 쌍 {j['pairs']}개 · 일치율 {pct(j['agreement'])} · 카파 "
              + ('—' if j['kappa'] is None else f"{j['kappa']:.2f}"),
              f"초안이 숨은 결정에서 한 행동: {d['at_hidden_decisions']} · 공개 입력: {d['on_public_inputs']}"]
    return '\n'.join(lines)


def selftest():
    names = [f't{i}' for i in range(12)]
    design = dict(seeds=[1, 2], contrasts=[dict(id='framing', **{'from': 'self1', 'to': 'ind1'}),
                                           dict(id='calls', **{'from': 'ind1', 'to': 'same3'}),
                                           dict(id='lenses', **{'from': 'same3', 'to': 'split3'})],
                  tasks={n: dict(kind='hidden', pattern='p' + str(i // 2), inputs=[[1], [2], [3]], public_true=[[3]],
                                 decisions=[dict(id='a', input=[1]), dict(id='b', input=[2])]) for i, n in enumerate(names)})
    design['tasks']['c'] = dict(kind='complete', pattern='control', inputs=[[1]], public_true=[], decisions=[])
    asked = dict(self1=[], ind1=['qa'], same3=['qa', 'noise'], split3=['qa', 'qb'])
    rows = [dict(task=t, seed=s, arm=arm, status='ready', raw=list(qs), sent=list(qs[:1]), tokens_review=10, tokens_agenda=5)
            for t in design['tasks'] for s in (1, 2) for arm, qs in asked.items()]
    drafts = [dict(task=t, seed=s, status='ok', behavior=[True, '보류', True] if t != 'c' else [False]) for t in design['tasks'] for s in (1, 2)]
    drafts[0]['status'] = 'draft_failed'   # one unit is dropped for every arm alike
    label_a = {key(t, q): tag for t in design['tasks'] for q, tag in (('qa', ['a']), ('qb', ['b']), ('noise', []))}
    label_b = dict(label_a)
    label_b[key('t1', 'qb')] = dict(labels=[], reason='disagrees once; reason form is accepted')
    r = analyze(design, rows, drafts, label_a, label_b)
    got = {arm: r['recall']['raw/both'][arm]['mean'] for arm in ARMS}
    assert got['self1'] == 0 and got['ind1'] == .5 and got['same3'] == .5, got
    assert abs(got['split3'] - (11 + .5) / 12) < 1e-9 and r['recall']['raw/either']['split3']['mean'] == 1, got
    p = r['primary']
    assert p['framing']['p'] == 2 / 4096 and abs(p['framing']['p_holm'] - 6 / 4096) < 1e-12 and p['framing']['verdict'] == 'supported'
    assert p['calls']['p'] == 1 and p['calls']['verdict'] == 'not distinguished' and p['calls']['tasks_tie'] == 12
    # t1 ties under the agreed labels, so both signs of that zero count: 4 of 4096 arrangements.
    assert p['lenses']['p'] == 4 / 4096 and p['lenses']['pattern_p'] == 2 / 64 and p['lenses']['verdict'] == 'supported'
    assert r['recall']['sent/both']['split3']['mean'] == .5 and r['valid_units'] == 25
    assert r['questions']['same3']['off_target_per_unit'] == 1 and r['questions']['ind1']['control_units_with_question'] == 1
    assert r['drafts']['at_hidden_decisions'] == dict(asserted=23, deferred=23) and r['drafts']['on_public_inputs'] == dict(correct=25)
    assert r['judges']['pairs'] == 72 and 0 < r['judges']['kappa'] < 1
    assert holm(dict(a=.01, b=.04, c=.03)) == dict(a=.03, c=.06, b=.06)
    assert sign_flip_p([.2, .2, -.2, 0]) == 1.0 and kappa([(True, True), (False, False)]) == 1
    print(render(r))
    print('selftest ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['selftest']:
        selftest()
    else:
        load = lambda name: json.loads((OUT / name).read_text())
        outcome = analyze(load('design.json'), load('rows.json'), load('drafts.json'), load('labels-A.json'), load('labels-B.json'))
        (OUT / 'analysis.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + '\n')
        print(render(outcome))
