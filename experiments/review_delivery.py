"""Deliver complete reviews to the operator and verify only explicitly confirmed findings."""
import json
from datetime import datetime

from backend.decision_checks import answer_cases, context_only
from backend.isolated import check_code
from experiments.local_baseline import SECONDS_ADAPTER, submission_text


def packet(history, reviews):
    return {'conversation': history, 'reviews': {f'R{i}': r for i, r in enumerate(reviews, 1)},
            'operator_instruction': '각 ID의 의견과 질문 전문을 읽으세요. 지적된 문제나 질문이 없으면 빈 문자열로 두세요. '
                                    '기존 안내문으로 확인되는 지적은 해당 검사 행을, 운영 판단이 필요한 지적은 담당자 답을 쓰세요. '
                                    '동작을 확정하면 고정 답변 또는 해당 답에서 도출한 검사 행을 쓰고, 설명만 전달하려면 별도 행에 맥락만을 적으세요. '
                                    '형식은 검사 예약후경과초 시작까지남은초 허용/거부 입니다.'}


def delivery_message(packet, answers):
    if not isinstance(answers, dict) or set(answers) != set(packet['reviews']):
        raise ValueError('각 검토 ID에 답변 또는 빈 문자열이 필요합니다.')
    if any(not isinstance(a, str) for a in answers.values()):
        raise ValueError('검토별 답변은 문자열이어야 합니다.')
    for key, answer in answers.items():
        if answer.strip() and not answer_cases(answer) and not context_only(answer):
            raise ValueError(f'{key} 답변에 검사 사례를 추가하거나 설명이면 맥락만으로 표시하세요.')
    entries = [dict(id=k, review=r, operator_answer=answers[k]) for k, r in packet['reviews'].items()]
    return json.dumps(entries, ensure_ascii=False)


def confirmed_answers(answers, baseline):
    confirmed = dict(answers)
    if any(answer_cases(a) for a in answers.values()) and answer_cases(baseline):
        confirmed['initial_answer'] = baseline
    return confirmed


def submission_status(result):
    return {'verified': 'verified', 'failed': 'paused_unresolved', 'needs_example': 'awaiting_example',
            'no_confirmed_checks': 'submitted_no_confirmed_findings'}[result['status']]


def verify(source, answers):
    results = []
    missing = []
    for key, answer in answers.items():
        if not answer.strip():
            continue
        cases = answer_cases(answer)
        if not cases:
            if not context_only(answer):
                missing.append(key)
            continue
        try:
            checked = check_code(source + SECONDS_ADAPTER, cases, 'cancellation_basic')
        except (RuntimeError, SyntaxError, ValueError) as exc:
            results.append(dict(id=key, error=str(exc), passed=False))
            continue
        for row in checked['results']:
            now, booked, starts = [datetime.fromisoformat(row[k]) for k in ('now', 'booked_at', 'starts_at')]
            results.append(dict(id=key, age_seconds=int((now-booked).total_seconds()),
                                until_start_seconds=int((starts-now).total_seconds()), expected=row['expected'],
                                actual=row['actual'], error=row['error'], passed=row['passed']))
    if missing:
        status = 'needs_example'
    elif any(not row['passed'] for row in results):
        status = 'failed'
    else:
        status = 'verified' if results else 'no_confirmed_checks'
    return dict(status=status, results=results, needs_example=missing)


def enforce(answers, calls, generate_revision, checkpoint, limit=5, first_submission=None):
    """Keep the first submission, recheck the full confirmed suite on every revision."""
    history = []
    first = len(calls) - 1 if first_submission is None else first_submission
    original_messages = calls[first]['request']['messages']
    for attempt in range(limit + 1):
        last = calls[first + attempt]
        result = verify(submission_text(last['text']), answers)
        history.append(result)
        checkpoint(history)
        if result['status'] != 'failed' or attempt == limit:
            return history
        if first + attempt + 1 < len(calls):
            continue  # Resume a saved submission with the original retry budget.
        failures = []
        for row in result['results']:
            if row['passed']:
                continue
            evidence = f"[{row['id']}] 담당자 답변: {answers[row['id']]}"
            if 'age_seconds' in row:
                assertion = f"assert allow_cancel({row['age_seconds']}, {row['until_start_seconds']}) is {row['expected']}"
                evidence += f"\n{assertion}\n실행 결과 {row['actual']!r}"
            if row.get('error'):
                evidence += '\n' + row['error']
            failures.append(evidence)
        prompt = (f'수정 {attempt + 1}회차. 아래는 현재 함수에서 실제로 실패한 검사입니다.\n' + '\n'.join(failures) +
                  '\n실패 입력을 현재 함수의 조건문에 대입해 어떤 줄에서 잘못된 값을 반환하는지 먼저 한 문장으로 짚으세요. '
                  '담당자의 규칙에 맞게 그 조건식을 고친 뒤, 수정한 전체 함수를 하나의 Python 코드 블록으로 제출하세요. '
                  '입력을 하드코딩하지 말고 기존에 통과한 사례의 동작을 유지하세요.')
        if attempt and submission_text(last['text']) == submission_text(calls[first + attempt - 1]['text']):
            prompt += '\n직전 두 제출의 코드가 같습니다. 동일한 코드에서는 위 검사가 다시 실패합니다.'
        messages = original_messages + [
            dict(role='assistant', content=last['text']),
            dict(role='user', content=prompt)]
        calls.append(generate_revision(messages, 1500))
