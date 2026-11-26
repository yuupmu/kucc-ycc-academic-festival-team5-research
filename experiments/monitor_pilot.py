"""Compare three independent local monitors with three same-budget self-review turns."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.isolated import grade_isolated, run_cases
from experiments.local_transport import msg, save
from experiments.local_baseline import BENCHMARK, generate, submission_text
from experiments.review_delivery import packet, delivery_message, confirmed_answers, enforce, submission_status


PILOT = Path(__file__).resolve().parent / 'pilot-qwen'
OUTPUT = PILOT / 'three-monitors'
ARMS = ('monitors', 'self')
SEEDS = (17, 29, 43)
PERSPECTIVES = (
    '개입 판단의 태도. 판단의 위험, 되돌릴 수 있는 범위, 사용자 의도를 검토한다.',
    '집중하는 근거. 문서·테스트의 근거, 원래 목표, 작업 간 의존성을 검토한다. 직접 검증 가능한 문제는 확인을 요청한다.',
    '인간에게 필요한 기여. 문서에 없는 현장 맥락, 가치 우선순위, 사용 경험을 구분한다. 인간에게 필요한 사실이나 판단만 요청한다.',
)
REVIEW_SYSTEM = '당신은 메인 개발자의 코드를 독립적으로 검토하는 감시자입니다.'
REVIEW_TASK = ('한 가지 중요한 문제 또는 계속 진행해도 되는 근거를 짧게 적으세요. '
               '초안과 주어진 정보에 근거해 메인이 확인할 구체적인 상황을 제시하세요. '
               '담당자에게 새로 물어야 할 것이 있으면 question에 한 질문을 적고, 없으면 빈 문자열로 두세요. '
               '이미 받은 답을 반복해서 묻지 마세요. feedback에는 의견을 두 문장 이내로 적으세요.')
FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'review', 'strict': True, 'schema': {
    'type': 'object', 'properties': {'question': {'type': 'string'}, 'feedback': {'type': 'string'}},
    'required': ['question', 'feedback'], 'additionalProperties': False}}}
REVISE = ('아래 세 검토 의견은 오류가 있을 수 있습니다. 고객 안내문과 담당자 답변에 비추어 필요한 변경만 반영하세요. '
          '정상 동작하는 부분을 보존하고, 수정할 부분이 없어도 전체 실행 가능한 Python 함수를 하나의 코드 블록으로 제출하세요.')
PROBE_METHODS = (
    '안내문에서 독립된 요구사항을 찾고 하나씩 적용되는 사례를 만들어라. 허용될 사례와 거부될 사례로 초안의 누락을 찾아라.',
    '한 입력만 바뀌는 사례 한 쌍을 만들어라. 값이 경계에 닿거나 두 규칙이 겹칠 때의 우선순위를 검토하라.',
    '서로 다른 두 해석이 다른 결과를 내는 입력을 찾아라. 문서만으로 결정할 수 없으면 구체적인 input을 놓고 담당자에게 질문하라.',
)
PROBE_TASK = ('초안은 아직 실행하지 않았다. 실제 함수를 실행할 checks를 최대 2개 제출하라. '
              '두 인자는 계약에 맞는 정수 초이다. expected는 안내문과 기존 답변만으로 확정되면 allow 또는 deny, '
              '결정할 수 없으면 unknown이다. 미확정 정책은 question으로 묻고 그 외에는 빈 문자열로 둔다. '
              'feedback에 기대 판정의 문서 근거를 짧게 적어라.')
CHECK_SCHEMA = {'type': 'object', 'properties': {
    'age_seconds': {'type': 'integer'}, 'until_start_seconds': {'type': 'integer'},
    'expected': {'type': 'string', 'enum': ['allow', 'deny', 'unknown']}},
    'required': ['age_seconds', 'until_start_seconds', 'expected'], 'additionalProperties': False}
PROBE_FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'case_review', 'strict': True, 'schema': {
    'type': 'object', 'properties': {'checks': {'type': 'array', 'items': CHECK_SCHEMA, 'maxItems': 2},
                                     'question': {'type': 'string'}, 'feedback': {'type': 'string'}},
    'required': ['checks', 'question', 'feedback'], 'additionalProperties': False}}}


def execute_probes(source, reviews):
    # Route the two integers to allow_cancel using the existing isolated Python runner.
    adapter = '\n\ndef can_cancel(age, until, unused):\n    return allow_cancel(age, until)\n'
    probes = []
    for index, review in enumerate(reviews, 1):
        for check in review.get('checks', []):
            age, until = check['age_seconds'], check['until_start_seconds']
            valid = type(age) is int and type(until) is int and age >= 0 and age + until > 0
            probes.append({'monitor': index, **check, 'valid_input': valid})
    valid = [p for p in probes if p['valid_input']]
    if valid:
        inputs = [{'now': p['age_seconds'], 'booked_at': p['until_start_seconds'], 'starts_at': 0} for p in valid]
        for probe, row in zip(valid, run_cases(source + adapter, inputs)):
            probe.update(row)
    return probes


def review_messages(history, arm, index, prior):
    instruction = PERSPECTIVES[index] + '\n' + REVIEW_TASK
    if arm == 'probes':
        instruction = PERSPECTIVES[index] + '\n' + PROBE_METHODS[index] + '\n' + PROBE_TASK
    if arm != 'self':
        # Each monitor sees exactly the public draft exchange; no grader or sibling feedback.
        return [msg('system', REVIEW_SYSTEM),
                msg('user', '메인과 담당자의 대화 및 코드 초안\n' +
                    json.dumps(history[1:], ensure_ascii=False) + '\n\n' + instruction)]
    messages = list(history)
    for call in prior:
        messages.extend([call['request']['messages'][-1], msg('assistant', call['text'])])
    return messages + [msg('user', '같은 개발자로서 다음 관점으로 초안을 자체 검토하세요.\n' + instruction)]


def parsed_feedback(call):
    try:
        review = json.loads(call['text'])
        if all(isinstance(review[k], str) for k in ('question', 'feedback')):
            return review
    except (TypeError, KeyError, ValueError):
        pass
    # Keep malformed output available to the operator as verbatim feedback.
    return {'question': '', 'feedback': call['text'], 'incomplete': True}


def condition(args, seed, arm, answers):
    draft_path = PILOT / f'{args.series}-{seed}.json'
    draft = json.loads(draft_path.read_text())
    if (draft['status'], draft['architecture'], draft['inputs'], len(draft['calls'])) != ('scored', 'main-only', 'seconds', 2):
        raise ValueError(f'Expected a completed first submission: {draft_path}')
    implementation = draft['calls'][1]
    history = implementation['request']['messages'] + [msg('assistant', implementation['text'])]
    digest = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    path = OUTPUT / f'{args.series}-{arm}-{seed}.json'
    if path.exists():
        record = json.loads(path.read_text())
        if record['draft_sha256'] != digest:
            raise ValueError(f'Original draft has changed: {draft_path}')
    else:
        record = {'source': draft_path.name, 'draft_sha256': digest, 'arm': arm, 'seed': seed,
                  'model_file': draft['model_file'], 'thinking': draft.get('thinking'), 'calls': [], 'status': 'started'}

    def call(messages, limit, fmt=None):
        response = generate(args.port, draft['model_file'], messages, seed, limit, draft.get('thinking'), fmt)
        if response['model'] != implementation['model']:
            raise ValueError(f"Expected {implementation['model']}, received {response['model']}")
        return response

    if record['status'] == 'scored' or record.get('report') is not None:
        return
    if args.stage == 'review':
        for index in range(len(record['calls']), 3):
            messages = review_messages(history, arm, index, record['calls'])
            response = call(messages, 320, PROBE_FORMAT if arm == 'probes' else FORMAT)
            response['role'] = f'monitor-{index+1}' if arm != 'self' else 'main-self-review'
            response['review'] = parsed_feedback(response)
            record['calls'].append(response)
            record['status'] = 'awaiting_operator' if index == 2 else 'reviewing'
            save(path, record)
        packet_path = path.with_suffix('.reviews.json')
        save(packet_path, packet(history, [c['review'] for c in record['calls'][:3]]))
        print('OPERATOR', packet_path, flush=True)
        return

    if len(record['calls']) < 3:
        raise ValueError(f'Complete all three reviews before final submission: {path}')
    answer = answers[f'{arm}-{seed}']
    reports = [c['review'] for c in record['calls'][:3]]
    batch = packet(history, reports)
    sent = delivery_message(batch, answer)
    if len(record['calls']) == 3:
        final = REVISE + '\n검토별 원문과 담당자 결정\n' + sent
        if arm == 'probes':
            observations = execute_probes(draft['submission'], reports)
            record['draft_probes'] = observations
            final += ('\n실험자가 초안을 격리 실행한 결과입니다. actual은 관측한 반환값이며 expected는 감시자의 가설입니다. '
                      '확인된 정책에 비추어 불일치를 검토하고, 기존에 맞는 사례도 보존하세요.\n' +
                      json.dumps(observations, ensure_ascii=False))
        response = call(history + [msg('user', final)], 1500)
        response['role'] = 'main-revise'
        record.update(operator_answer='\n'.join(a for a in answer.values() if a), status='submitted',
                      delivery=dict(operator_packet=batch, decisions=answer, first_submission_call=3))
        record['calls'].append(response)
        save(path, record)
    elif record.get('delivery', {}).get('decisions') != answer:
        raise ValueError('저장된 제출과 검토별 답변이 일치하지 않습니다. 이 기록을 보존하고 새 출력 폴더에서 실행하세요.')
    def checkpoint(history):
        record['delivery']['verification'] = history
        record['status'] = submission_status(history[-1])
        save(path, record)
    enforce(confirmed_answers(answer, draft['operator_answer']), record['calls'], call, checkpoint, first_submission=3)
    record['submission'] = submission_text(record['calls'][-1]['text'])
    if arm == 'probes':
        record['final_probes'] = execute_probes(record['submission'], [c['review'] for c in record['calls'][:3]])
    record['report'] = grade_isolated(record['submission'] + draft['input_adapter'], BENCHMARK, 'cancellation_basic')
    save(path, record)
    print(path.name, record['status'], record['report']['score'], '/', record['report']['total'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['review', 'finish'])
    parser.add_argument('series', choices=['7b-seconds', '14b-seconds', 'qwen3-8b-off'])
    parser.add_argument('--port', type=int, default=18751)
    parser.add_argument('--answers', type=Path, help='JSON map of arm-seed to R1/R2/R3 operator replies')
    parser.add_argument('--out', type=Path, default=OUTPUT, help='Separate directory for new pilot records')
    parser.add_argument('--probes', action='store_true', help='Run the independent executable-case monitor condition')
    args = parser.parse_args()
    if args.stage == 'finish' and not args.answers:
        parser.error('finish requires --answers')
    answers = json.loads(args.answers.read_text()) if args.answers else {}
    OUTPUT = args.out
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        for arm in (('probes',) if args.probes else ARMS):
            condition(args, seed, arm, answers)
