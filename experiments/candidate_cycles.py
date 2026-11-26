"""A/B/C submit runnable alternatives. D can choose only within the best verified tier."""
import argparse
import json
from pathlib import Path

from backend.isolated import grade_isolated
from experiments.local_baseline import BENCHMARK, SECONDS_ADAPTER, submission_text
from experiments.monitor_cycles import IDS, MAIN, MODEL, compact, locked_output, read, recorded, save
from experiments.verified_cycles import SEEDS, improves, observe, specification


NEW_SEEDS = (131, 157, 191, 223, 257, 293)
STAGES = ('direct', 'self_short', 'self_serial', 'abcd')
RECENT = ((1, 14400, True, '방금 만든 예약의 정정 시간은 생성 순간 이후에도 존재'),
          (1, 43200, True, '같은 예약 경과 시간, 다른 이용 시작 시각'))
METHODS = ('안내문의 규칙 순서를 결정한 뒤 간결한 함수를 작성하세요.',
           '각 인자가 측정하는 시간을 먼저 구분하고, 허용 조건을 조합해 함수를 작성하세요.',
           '규칙이 겹치는 상황의 우선순위부터 정한 뒤 함수를 작성하세요.')
PROPOSE = ('앞의 코드는 검토 대상입니다. 전체 요구사항을 만족하는 독립적인 대체 함수를 제안하세요. '
           '예시에만 맞는 분기를 만들지 마세요. 시간이 명시되지 않았으면 현실적인 양의 유예 기간을 '
           '하나 가정하고, 시간 단위와 가정임을 주석에 표시하세요. 명세에 있는 값은 그대로 따르세요. '
           '질문하지 말고 전체 allow_cancel 함수만 하나의 Python 코드 블록으로 제출하세요.')
FALLBACK_DESIGN = dict(condition='chosen candidate fails an available example',
                       prompt_information='specification and labeled visible examples only, no previous candidate text',
                       applies_to=list(STAGES[1:]), max_calls=1, max_tokens=800, accept='strict superset of retained passes')


def contenders(observations):
    passed = {k: {i for i, row in enumerate(rows) if row['passed']} for k, rows in observations.items()}
    eligible = [k for k, hits in passed.items() if passed['draft'] < hits]
    if not eligible:
        return ['draft']
    best = max(len(passed[k]) for k in eligible)
    return [k for k in eligible if len(passed[k]) == best]


def choose(d, arm, brief, candidates, observations, seed, port):
    eligible = contenders(observations)
    chosen = eligible[0]
    if len(eligible) > 1:
        fmt = {'type': 'json_schema', 'json_schema': {'name': 'selection', 'strict': True, 'schema': {
            'type': 'object', 'properties': {'chosen': {'type': 'string', 'enum': eligible}},
            'required': ['chosen'], 'additionalProperties': False}}}
        options = {k: dict(code=submission_text(candidates[k]['text']), execution=observations[k]) for k in eligible}
        system = '당신은 검토 편집자 D입니다.' if arm == 'abcd' else MAIN
        user = (brief + '\n공개 검사 결과가 동률인 후보\n' + compact(options) +
                '\n명세 전반과 일치하고, 입력에 일반화되며 미확정 가정을 분명히 한 후보 한 개를 고르세요.')
        record = recorded(d/'D.json', 'D', system, user, seed, 80, port, fmt)
        selected = json.loads(record['text'])['chosen']
        if selected not in eligible:
            raise ValueError('검사로 허용된 후보만 선택할 수 있습니다.')
        chosen = selected
    save(d/'decision.json', dict(eligible=eligible, chosen=chosen, observations=observations))
    return chosen


def generate(d, info, seed, port, index):
    system, prompt, brief, base_checks = specification(info)
    checks = base_checks + RECENT
    d.mkdir(parents=True, exist_ok=True)
    draft = recorded(d/'draft.json', 'main', system, prompt, seed, 1500, port)
    code = submission_text(draft['text'])
    observed = observe(code, checks)
    context = brief + '\n현재 초안\n' + code + '\n실행 결과\n' + compact(observed)
    candidates, observations = {'draft': draft}, {'draft': observed}
    if not all(r['passed'] for r in observed):
        candidates['A'] = recorded(d/'A.json', 'A', MAIN, context + '\n' + METHODS[0] + ' ' + PROPOSE, seed, 800, port)
        observations['A'] = observe(submission_text(candidates['A']['text']), checks)
    short = d/'self_short'
    short.mkdir(exist_ok=True)
    choose(short, 'self_short', brief, candidates, observations, seed, port)
    for arm in (('abcd', 'self_serial') if index % 2 == 0 else ('self_serial', 'abcd')):
        target = d/arm
        target.mkdir(exist_ok=True)
        pool, rows = candidates.copy(), observations.copy()
        if 'A' in pool:
            for role, method in zip(IDS[1:], METHODS[1:]):
                prior = ''
                if arm == 'self_serial':
                    previous = {k: submission_text(v['text']) for k, v in pool.items() if k != 'draft'}
                    prior = '\n같은 개발자로서 앞서 작성한 후보\n' + compact(previous)
                record = recorded(target/f'{role}.json', role, MAIN, context + prior + '\n' + method + ' ' + PROPOSE,
                                  seed, 800, port)
                pool[role] = record
                rows[role] = observe(submission_text(record['text']), checks)
        choose(target, arm, brief, pool, rows, seed, port)
    print('submitted', info, seed, flush=True)


def resolve_remaining(out, seeds, port):
    """If the retained code still fails, attempt one fresh implementation without the erroneous draft."""
    for info in ('public', 'full'):
        _, _, brief, base = specification(info)
        checks = base + RECENT
        examples = '\n'.join(f'allow_cancel({age}, {until}) → {expected} ({reason})'
                             for age, until, expected, reason in checks)
        for seed in seeds:
            d = out/info/str(seed)
            observed = None
            for arm in STAGES[1:]:
                target = d/arm
                first = read(target/'decision.json')
                chosen = first['chosen']
                current = first['observations'][chosen]
                pending = not all(r['passed'] for r in current)
                if pending:
                    if observed is None:
                        user = (brief + '\n명세에서 도출한 동작 예시\n' + examples +
                                '\n새 대화에서 함수를 처음부터 설계하세요. 규칙이 겹치면 무엇이 우선하는지 '
                                '결정한 뒤, 모든 입력에 적용되는 짧은 함수만 제출하세요. '
                                '시간이 미명시된 경우 실제로 쓸 수 있는 유예 기간을 가정해 주석에 표시하세요.')
                        call = recorded(d/'fresh.json', 'main', MAIN, user, seed, 800, port)
                        observed = observe(submission_text(call['text']), checks)
                    if improves(current, observed):
                        chosen = 'fresh'
                save(target/'final-decision.json', dict(chosen=chosen, previous=first['chosen'], attempted=pending,
                     retained_checks=observed if chosen == 'fresh' else current,
                     fresh_checks=observed if pending else None))


def grade(out, seeds, final=False):
    from experiments.cancellation_transfer import transfer_checks
    decision_file = 'final-decision.json' if final else 'decision.json'
    if not all((out/i/str(s)/a/decision_file).is_file() for i in ('public', 'full')
               for s in seeds for a in STAGES[1:]):
        raise ValueError('모든 제출이 고정된 뒤 채점합니다.')
    extra = transfer_checks(specification('full')[3] + RECENT)
    results = []
    for info in ('public', 'full'):
        for seed in seeds:
            d = out/info/str(seed)
            for arm in STAGES:
                target = d if arm == 'direct' else d/arm
                decision = None if arm == 'direct' else read(target/'decision.json')
                dispatch = read(target/decision_file) if decision and final else decision
                chosen = dispatch['chosen'] if dispatch else 'draft'
                parent = d if chosen in ('draft', 'A', 'fresh') else target
                source = submission_text(read(parent/f'{chosen}.json')['text'])
                report = grade_isolated(source + SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
                transfer = observe(source, extra)
                save(target/('final-score.json' if final else 'score.json'), report)
                save(target/('final-transfer.json' if final else 'transfer.json'), transfer)
                paths = [d/'draft.json']
                if decision and 'A' in decision['observations']:
                    paths.append(d/'A.json')
                    paths.extend(target/f'{role}.json' for role in IDS[1:] if role in decision['observations'])
                    if len(decision['eligible']) > 1:
                        paths.append(target/'D.json')
                if final and dispatch and dispatch['attempted']:
                    paths.append(d/'fresh.json')
                calls = [read(p) for p in paths]
                if arm == 'direct':
                    baseline = report
                if [r['id'] for r in baseline['results']] != [r['id'] for r in report['results']]:
                    raise ValueError('문항이 일치하지 않습니다.')
                changes = [b for a, b in zip(baseline['results'], report['results']) if a['passed'] != b['passed']]
                results.append(dict(info=info, seed=seed, arm=arm, chosen=chosen, score=report['score'],
                                    total=report['total'], transfer_score=sum(r['passed'] for r in transfer),
                                    transfer_total=len(extra), fixed=[r['id'] for r in changes if r['passed']],
                                    lost=[r['id'] for r in changes if not r['passed']], calls=len(calls),
                                    tokens=sum(c['usage']['total_tokens'] for c in calls),
                                    model_seconds=round(sum(c['elapsed_seconds'] for c in calls), 2)))
    save(out/('final-results.json' if final else 'results.json'), results)
    for info in ('public', 'full'):
        for arm in STAGES:
            rows = [r for r in results if (r['info'], r['arm']) == (info, arm) and r['seed'] in NEW_SEEDS]
            print(f"fresh seeds, {info} {arm}: {sum(r['score'] for r in rows)}/{sum(r['total'] for r in rows)}, "
                  f"{sum(r['calls'] for r in rows)} calls", flush=True)


def run(out, port):
    with locked_output(out):
        run_locked(out, port)


def run_locked(out, port):
    seeds = SEEDS + NEW_SEEDS
    design = dict(protocol='verified-candidates-v1', model=MODEL, development=list(SEEDS), fresh=list(NEW_SEEDS),
                  stages=list(STAGES), extra_notice_examples=list(map(list, RECENT)), candidate_limit=800,
                  selection='preserve all draft passes, maximize passed examples, D decides ties, otherwise retain draft',
                  score_feedback=False, thinking='off')
    path = out/'design.json'
    if (path.exists() and read(path) != design) or (not path.exists() and any(out.iterdir())):
        raise ValueError('새 폴더 또는 동일 조건의 실행 기록을 사용하세요.')
    save(path, design)
    fallback_plan = out/'fallback-design.json'
    if fallback_plan.exists() and read(fallback_plan) != FALLBACK_DESIGN:
        raise ValueError('기존 실행과 복구 조건이 다릅니다.')
    save(fallback_plan, FALLBACK_DESIGN)
    for i, seed in enumerate(seeds):
        for info in ('public', 'full'):
            generate(out/info/str(seed), info, seed, port, i)
    resolve_remaining(out, seeds, port)
    grade(out, seeds)
    grade(out, seeds, final=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18767)
    args = parser.parse_args()
    run(args.out, args.port)
