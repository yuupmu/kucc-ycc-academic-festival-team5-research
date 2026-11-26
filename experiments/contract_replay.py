"""Replay the final main call with executable examples of already-disclosed rules."""
import argparse
import hashlib
import json

from backend.isolated import grade_isolated
from experiments.local_baseline import BENCHMARK, generate, submission_text
from experiments.monitor_pilot import OUTPUT, PILOT, SEEDS, execute_probes, save


GRACE = '예약 생성 후 10분까지는 일반 취소 마감이 지나도 허용합니다. 정확히 10분인 경우도 포함합니다.'
START = '현재 시각이 이용 시작 시각과 같거나 이후면, 정정 시간이 남아 있어도 거부합니다.'
INTRO = ('다음 사례의 기대값은 위 안내문과 이 대화에서 담당자가 확인해 준 규칙에서 도출했습니다. '
         'actual은 초안 실행 결과입니다. 불일치를 고치고 기존에 맞는 사례도 보존하세요.')


def confirmed_examples(public_brief, answers):
    if '일반 취소 마감은 이용 시작 24시간 전입니다' not in public_brief:
        raise ValueError('Expected the public deadline from the basic reservation task')
    def case(age, until, expected, rule):
        return dict(age_seconds=age, until_start_seconds=until, expected=expected, rule=rule)
    checks = [case(172800, 172800, 'allow', '일반 취소 마감 전')]
    if GRACE in answers:
        for age, expected in [(599, 'allow'), (600, 'allow'), (601, 'deny')]:
            checks.append(case(age, 7200, expected, '일반 마감 후 정정 시간'))
        checks.append(case(172800, 86399, 'deny', '일반 마감 후 정정 시간 경과'))
    if START in answers and GRACE in answers:
        for until, expected in [(1, 'allow'), (0, 'deny'), (-1, 'deny')]:
            checks.append(case(300, until, expected, '정정 시간 중 이용 시작'))
    return checks


def observe(source, checks):
    rows = execute_probes(source, [dict(checks=checks)])
    for row in rows:
        del row['monitor']
        if not row.pop('valid_input'):
            raise ValueError('Invalid contract example')
        row['passed'] = row['error'] is None and row['actual'] is (row['expected'] == 'allow')
    return rows


def replay(series, seed, port):
    path = OUTPUT / f'{series}-monitors-{seed}.json'
    destination = OUTPUT / f'{series}-contract-{seed}.json'
    original = json.loads(path.read_text())
    draft_path = PILOT / original['source']
    if hashlib.sha256(draft_path.read_bytes()).hexdigest() != original['draft_sha256']:
        raise ValueError('The original draft changed')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if destination.exists():
        record = json.loads(destination.read_text())
        if record['source_sha256'] != digest:
            raise ValueError('The original monitor run changed')
        if record['status'] == 'scored':
            return
    draft = json.loads(draft_path.read_text())
    last = original['calls'][-1]
    request = last['request']
    messages = request['messages'][:]
    answers = draft['operator_answer'] + '\n' + original['operator_answer']
    checks = confirmed_examples(messages[1]['content'], answers)
    before = observe(draft['submission'], checks)
    suffix = '\n' + INTRO + '\n' + json.dumps(before, ensure_ascii=False)
    messages[-1] = dict(messages[-1], content=messages[-1]['content'] + suffix)
    if not destination.exists():
        response = generate(port, draft['model_file'], messages, seed, request['max_tokens'], draft.get('thinking'))
        if response['model'] != last['model'] or dict(response['request'], messages=request['messages']) != request:
            raise ValueError('The model or sampling configuration changed')
        record = dict(source=path.name, source_sha256=digest, arm='contract', seed=seed,
                      draft_checks=before, calls=[response], submission=submission_text(response['text']), status='submitted')
        save(destination, record)
    record['final_checks'] = observe(record['submission'], checks)
    record['verified'] = all(row['passed'] for row in record['final_checks'])
    record['report'] = grade_isolated(record['submission'] + draft['input_adapter'], BENCHMARK, 'cancellation_basic')
    record['status'] = 'scored'
    save(destination, record)
    print(destination.name, record['report']['score'], 'verified', record['verified'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('series', choices=['7b-seconds', '14b-seconds', 'qwen3-8b-off'])
    parser.add_argument('--port', type=int, default=18751)
    options = parser.parse_args()
    for seed in SEEDS:
        replay(options.series, seed, options.port)
