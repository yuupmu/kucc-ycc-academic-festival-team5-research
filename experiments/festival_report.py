"""Post-run evaluator for the fixed 20-item sample. The generation protocol has no dependency on it."""
import csv
import difflib
from collections import Counter, defaultdict
from datetime import datetime

from backend.isolated import run_cases
from pathlib import Path

from experiments import festival_protocol as protocol, festival_refinement
from experiments.festival_mini import CONFIG, FIXTURES, STUDY, checksum, compose, executed_refinement_hash, preregister, selection_path
from experiments.local_baseline import SECONDS_ADAPTER
from experiments.local_transport import read, save
from reservation_benchmark.score import load_cases


NAMES = {'solo': '① 메인 단독', 'self': '② 메인 자체 검토', 'p1': '③ P1 공통 관점',
         'p2': '③ P2 역할 분담', 'p3': '③ P3 역할 분담·질문 근거', 'p4': '③ P4 질문 정리·답변 반영 확인',
         'p4-guarded': '③ P4 수정 보류 재생'}
TASK_NAMES = {'reservation': '예약 취소', 'triage': '문의 배정'}
TYPES = ('prompt_tokens', 'completion_tokens', 'total_tokens')
STATUS = {'one_shot': '단독 산출물', 'reviewed_complete': '검토 완료', 'open_limit': '미해결 종료',
          'invalid_output': '응답 형식 실패'}


def select_cases(config, task):
    selected = config['sample'][task]
    if task == 'reservation':
        cases, answers, _, _ = load_cases(basic=True)
        index = {c['id']: c for c in cases}
        return [(k, {s: index[k][s] for s in ('now', 'booked_at', 'starts_at')}, answers[k]['allowed'])
                for k in selected]
    data = read(FIXTURES / 'private-cases.json')[task]
    return [(str(i), {'initial_state': {'args': data[i-1]['args']}, 'events': []}, data[i-1]['expected']) for i in selected]


def evaluate(task, files, rows):
    code = next(iter(files.values()))
    adapter = SECONDS_ADAPTER if task == 'reservation' else (
        '\n\ndef simulate(initial_state, events):\n    return {"value": triage(*initial_state["args"])}\n')
    outputs = run_cases(code + adapter, [case for _, case, _ in rows], 'cancellation' if task == 'reservation' else 'allocation')
    result = {}
    for (case_id, _, expected), row in zip(rows, outputs):
        actual = row['actual']
        if task == 'triage' and type(actual) is dict:
            actual = actual.get('value')
        decision = 'unanswered' if row['error'] or type(actual) is not type(expected) else 'correct' if actual == expected else 'wrong'
        result[case_id] = {'actual': actual, 'expected': expected, 'status': decision, 'error': row['error']}
    return result


def token_sum(calls):
    return {k: sum(c['usage'][k] for c in calls) for k in TYPES}


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def item_table(config, arms, research, results):
    lines = ['# 고정한 20문항의 실제 반환값', '', '괄호 안의 값은 오답으로 반환한 값이다. '
             '미판정의 오류 기록은 과제·조건·버전별 cases.json에 있다.', '',
             '| 과제·문항 | 입력 | 기대값 | ' + ' | '.join(NAMES[a] for a in arms) + ' |',
             '|---|---|---|' + '---|'*len(arms)]
    for task in config['sample']:
        latest = {}
        for arm in arms:
            n = results[task][arm]['metrics']['versions']
            latest[arm] = read(research / task / arm / f'v{n}' / 'cases.json')['verdicts']
        for case_id, case, expected in select_cases(config, task):
            if task == 'reservation':
                now, booked, start = (datetime.fromisoformat(case[k]) for k in ('now', 'booked_at', 'starts_at'))
                detail = f"생성 후 {int((now-booked).total_seconds()):,}초 · 시작까지 {int((start-now).total_seconds()):,}초"
            else:
                detail = ', '.join(case['initial_state']['args'][0]) or '빈 목록'
            cells = [TASK_NAMES[task]+' '+case_id, detail, str(expected)]
            for arm in arms:
                row = latest[arm][case_id]
                cells.append({'unanswered': '미판정', 'wrong': f"오답 ({row['actual']})", 'correct': '정답'}[row['status']])
            lines.append('| '+' | '.join(cells)+' |')
    (research / 'items.md').write_text('\n'.join(lines)+'\n')


def observe_arm(config, out, task, arm, info, state, measured, cases, call_bank, research):
    receipts = {a['version']: a for a in state['answers'] if a['arm'] == arm}
    role_calls, obtained, history, all_calls = defaultdict(list), set(), [], []
    prior_files = read(out / 'design.json')['project']['files']
    for n in range(1, info['version'] + 1):
        folder = out / arm / f'v{n}'
        snapshot, review = read(folder / 'snapshot.json'), read(folder / 'review.json')
        key = snapshot['sha256']
        if key not in measured:
            measured[key] = evaluate(task, snapshot['files'], cases)
        rows = measured[key]
        counts = Counter(r['status'] for r in rows.values())
        probes = {}
        for case_id, requirements in config['policy_probes_within_sample'][task].items():
            missing = [alternatives for alternatives in requirements if obtained.isdisjoint(alternatives)]
            probes[case_id] = dict(required_but_unreceived=missing, returned=rows[case_id]['status'] != 'unanswered')
        patch = ''.join(line for name, code in snapshot['files'].items() for line in
                        difflib.unified_diff(prior_files[name].splitlines(True), code.splitlines(True),
                                             f'v{n-1}/{name}', f'v{n}/{name}'))
        target = research / task / arm / f'v{n}'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'change.diff').write_text(patch)
        save(target / 'cases.json', {'code_sha256': key, 'verdicts': rows})
        for identifier in review['calls']:
            call = call_bank[identifier]
            role_calls[call['role']].append(call)
            all_calls.append(call)
        receipt = receipts.get(n)
        if receipt:
            selection = read(selection_path(task, arm, n))
            if (receipt['source'] != 'delegated_policy_card' or receipt['questions'] != selection['questions']
                    or receipt['text'] != compose(task, selection['selections']) or selection['text'] != receipt['text']):
                raise ValueError('전달한 답변과 담당자 카드가 다릅니다.')
            obtained.update(k for group in selection['selections'] for k in group)
        history.append(dict(version=n, correct=counts['correct'], wrong=counts['wrong'], unanswered=counts['unanswered'],
                            ids={k: r['status'] for k, r in rows.items()}, probes=probes, status=review['status'],
                            questions=review['questions'], reply=receipt['text'] if receipt else None, calls=review['calls'],
                            sha256=key))
        prior_files = snapshot['files']
    baseline, last = history[0], history[-1]
    got_better = [k for k in baseline['ids'] if last['ids'][k] == 'correct' and baseline['ids'][k] != 'correct']
    got_worse = [k for k in baseline['ids'] if last['ids'][k] != 'correct' and baseline['ids'][k] == 'correct']
    stats = dict(task=task, arm=arm, model=config['model'].split('/')[-1], seed=config['seed'],
                 correct=last['correct'], total=len(cases), wrong=last['wrong'], unanswered=last['unanswered'],
                 status=info['status'], versions=info['version'], human_windows=len(receipts),
                 questions_answered=sum(len(a['questions']) for a in receipts.values()), calls=len(all_calls),
                 author_tokens=token_sum(role_calls['main-author'])['total_tokens'],
                 main_self_review_tokens=token_sum(role_calls['main-self'])['total_tokens'],
                 watcher_tokens=sum(token_sum(role_calls[r])['total_tokens'] for r in (*protocol.SLOTS, 'C-intake')),
                 **token_sum(all_calls),
                 unsupported_returns=sum(bool(p['required_but_unreceived'] and p['returned']) for p in last['probes'].values()),
                 policy_probes=len(last['probes']), gained=len(got_better), regressed=len(got_worse))
    if stats['total_tokens'] != sum(stats[k] for k in ('author_tokens', 'main_self_review_tokens', 'watcher_tokens')):
        raise ValueError('역할별 사용량이 전체와 다릅니다.')
    return dict(metrics=stats, history=history, improved_ids=got_better, regressed_ids=got_worse,
                role_usage={r: token_sum(v) for r, v in role_calls.items()})


def report():
    config = read(CONFIG)
    preregister(config)
    tasks = config['sample']
    states = {task: read(STUDY / 'runs' / task / 'state.json') for task in tasks}
    refinement = read(STUDY / 'refinement-v2-manifest.json')
    if (refinement['same_sample_sha256'] != checksum(CONFIG) or
            refinement['implementation_sha256'] != executed_refinement_hash(Path(festival_refinement.__file__))):
        raise ValueError('P4의 비교 표본이나 절차가 변경되었습니다.')
    refined = {task: read(STUDY / 'refined-v2' / task / 'state.json') for task in tasks}
    arms = [*config['arms'], 'p4']
    if any(info['status'] not in protocol.TERMINAL for s in (states, refined) for state in s.values() for info in state['arms'].values()):
        raise ValueError('비교 조건 전체의 최종 코드가 고정되어야 채점할 수 있습니다.')
    research = STUDY / 'research'
    research.mkdir(exist_ok=True)
    results, summaries, physical, smoke_only = {}, [], [], []
    for task, state in states.items():
        out = STUDY / 'runs' / task
        used = protocol.audit(out)
        calls = {k: read(out / 'calls' / (k + '.json')) for k in used}
        measured, results[task] = {}, {}
        cases = select_cases(config, task)
        for arm, info in state['arms'].items():
            observation = observe_arm(config, out, task, arm, info, state, measured, cases, calls, research)
            results[task][arm] = observation
            summaries.append(observation['metrics'])
        fork = STUDY / 'refined-v2' / task
        audited = festival_refinement.stage(out, fork, audit=True)
        extra = {p.stem: read(p) for p in (fork / 'calls').glob('*.json')}
        observation = observe_arm(config, fork, task, 'p4', audited['arms']['p4'], audited, measured, cases, extra, research)
        results[task]['p4'] = observation
        summaries.append(observation['metrics'])
        if set(extra) != {k for v in observation['history'] for k in v['calls']}:
            raise ValueError('연결되지 않은 P4 호출입니다.')
        if any(extra[k] != calls[k] for k in calls.keys() & extra.keys()):
            raise ValueError('재사용한 응답의 원문이 다릅니다.')
        physical.extend({**calls, **extra}.values())
        smoke_only.extend(read(p) for p in (STUDY/'refined'/task/'calls').glob('*.json') if p.stem not in calls.keys() | extra.keys())
        drafts = [(a['history'][0]['sha256'], a['history'][0]['calls'][0]) for a in results[task].values()]
        if len(set(drafts)) != 1:
            raise ValueError('초안 또는 첫 메인 호출이 동일하지 않습니다.')
    write_csv(research / 'metrics.csv', summaries)
    totals = []
    for arm in arms:
        selected = [s for s in summaries if s['arm'] == arm]
        fields = ('correct', 'total', 'wrong', 'unanswered', 'calls', 'questions_answered', 'human_windows', 'author_tokens',
                  'main_self_review_tokens', 'watcher_tokens', *TYPES, 'unsupported_returns', 'policy_probes', 'gained', 'regressed')
        totals.append({'arm': arm, **{k: sum(s[k] for s in selected) for k in fields}})
    write_csv(research / 'totals.csv', totals)
    item_table(config, arms, research, results)
    summary = dict(sample_size=sum(len(v) for v in tasks.values()), tasks=results, totals=totals,
                   physical={'unique_calls': len(physical), **token_sum(physical)},
                   logical_calls=sum(s['calls'] for s in summaries), shared_references=sum(s['calls'] for s in summaries)-len(physical),
                   discarded_punctuation_trial={'extra_calls': len(smoke_only), **token_sum(smoke_only)})
    save(research / 'comparison.json', summary)
    lines = ['# 핵심 20문항의 실측 결과', '', '각 조건의 마지막 코드로 계산했다. 두 과제는 각각 10문항이다. '
             '미판정은 반환값이 없거나 요구한 자료형으로 반환하지 못한 경우다.', '',
             '| 조건 | 예약 | 배정 | 정답 / 20 | 오답 | 미판정 | 답한 질문 | 입력 토큰 | 출력 토큰 | 합계 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in totals:
        arm = row['arm']
        values = [NAMES[arm], *[str(results[t][arm]['metrics']['correct']) for t in tasks],
                  *[f'{row[k]:,}' for k in ('correct', 'wrong', 'unanswered', 'questions_answered', *TYPES)]]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '## 회차와 최종 검토 상태', '', '| 과제 | 조건 | 초안 → 마지막 | 마지막 상태 | 답변 회차 | '
              '작성 / 자체 검토 / 감시 토큰 | 근거가 덜 확보된 판정¹ |', '|---|---|---|---|---:|---:|---:|']
    for s in summaries:
        first = results[s['task']][s['arm']]['history'][0]['correct']
        lines.append(f"| {TASK_NAMES[s['task']]} | {NAMES[s['arm']]} | {first} → {s['correct']} | {STATUS[s['status']]} | "
                     f"{s['human_windows']} | {s['author_tokens']:,} / {s['main_self_review_tokens']:,} / {s['watcher_tokens']:,} "
                     f"| {s['unsupported_returns']} / {s['policy_probes']} |")
    usage = summary['physical']
    lines += ['', '¹ 각 과제에서 사전 지정한 3문항의 입력이 반환값을 내면서, 그 결정을 위해 지정한 담당자 답변 중 일부를 '
              '받지 못한 경우다. 관찰자 지표이며 모델의 의도는 측정하지 않는다.', '',
              f"조건별로 초안 및 정확히 같은 요청은 한 번씩 전액 계산했다. 전체 장비 실측은 {len(physical)}회 호출, "
              f"입력 {usage['prompt_tokens']:,} · 출력 {usage['completion_tokens']:,} · 합계 {usage['total_tokens']:,}토큰이다. "
              f"조건별 호출 {summary['logical_calls']}개 중 원문이 동일한 {summary['shared_references']}개는 저장된 응답을 함께 썼다.",
              f"물음표 때문에 질문을 누락한 기술 예비 실행에만 쓰인 비용은 {len(smoke_only)}회, "
              f"{token_sum(smoke_only)['total_tokens']:,}토큰이다.",
              '', '연구용 진행자가 실제 질문에 해당하는 고정 문장을 골라 답했다. 실사용자 답변은 0회다. 시드 하나의 진단용 표본이다.']
    (research / 'results.md').write_text('\n'.join(lines) + '\n')
    return summary


def guard_replay():
    from experiments.festival_guarded import finalize
    research = STUDY / 'research'
    config, original = read(CONFIG), read(research/'comparison.json')
    rows, receipts = [], {}
    for task, arms in original['tasks'].items():
        files, receipt = finalize(STUDY/'refined-v2'/task)
        if protocol.core.digest(files) != receipt['retained_sha256']:
            raise ValueError('확정된 파일의 식별값이 다릅니다.')
        match = next(((arm, v) for arm, item in arms.items() for v in item['history']
                      if v['sha256'] == receipt['retained_sha256']), None)
        if match is None:
            raise ValueError('이미 동일 표본으로 측정된 코드와 일치하지 않습니다.')
        arm, version = match
        verified = read(research/task/arm/('v'+str(version['version']))/'cases.json')
        if verified['code_sha256'] != receipt['retained_sha256']:
            raise ValueError('원래 문항 기록의 코드 식별값이 다릅니다.')
        folder = research/task/'p4-guarded/v2'
        folder.mkdir(parents=True, exist_ok=True)
        save(folder/'cases.json', verified)
        stats = dict(arms['p4']['metrics'])
        baseline = arms['solo']['history'][0]['ids']
        ids = version['ids']
        stats.update(arm='p4-guarded', status=receipt['status'], correct=version['correct'], wrong=version['wrong'],
                     unanswered=version['unanswered'], gained=sum(ids[k]=='correct' and baseline[k]!='correct' for k in ids),
                     regressed=sum(ids[k]!='correct' and baseline[k]=='correct' for k in ids),
                     unsupported_returns=sum(bool(p['required_but_unreceived'] and ids[k]!='unanswered')
                                             for k, p in arms['p4']['history'][-1]['probes'].items()),
                     additional_model_calls=0, additional_tokens=0)
        receipts[task] = dict(guard=receipt, verdict_source={'arm': arm, 'version': version['version']}, metrics=stats)
        rows.append(stats)
        arms['p4-guarded'] = {'metrics': stats}
    totals = {k: sum(r[k] for r in rows) for k in ('correct','total','wrong','unanswered','gained','regressed',
              'unsupported_returns','policy_probes','prompt_tokens','completion_tokens','total_tokens','additional_model_calls','additional_tokens')}
    write_csv(research/'guarded.csv', rows)
    save(research/'guarded.json', {'tasks': receipts, 'totals': totals, 'type': 'post_hoc_replay_of_frozen_outputs'})
    festival_rows = []
    for arm, record, stage in [*[(m['arm'], m, 'model_run') for m in original['totals']],
                               ('p4-guarded', totals, 'post_hoc_replay')]:
        festival_rows.append(dict(stage=stage, condition=NAMES[arm], model=Path(config['model']).name,
                                  seed=config['seed'], reservation=original['tasks']['reservation'][arm]['metrics']['correct'],
                                  triage=original['tasks']['triage'][arm]['metrics']['correct'],
                                  **{k: record[k] for k in ('correct','total','wrong','unanswered',*TYPES,
                                                            'unsupported_returns','policy_probes','gained','regressed')}))
    write_csv(research/'summary.csv', festival_rows)
    item_table(config, [*config['arms'],'p4','p4-guarded'], research, original['tasks'])
    return totals
