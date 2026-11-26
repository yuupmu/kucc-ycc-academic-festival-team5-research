"""Executable examples for disclosed basic-reservation decisions only."""
import re
from datetime import datetime, timedelta, timezone

CONTEXT_ANSWERS = {'휴무일은 없습니다', '모든 입력은 과제에 명시한 형식을 따릅니다',
                   '이 과제에 추가로 적용할 정책은 없습니다', '어떤 상황에서 판정이 달라지는지 구체적으로 말씀해 주세요'}


def context_only(text):
    clauses = {s.strip() for s in text.split('.') if s.strip()}
    return ('맥락만' in [line.strip() for line in text.splitlines()]
            or bool(clauses) and clauses <= CONTEXT_ANSWERS)


def reservation_case(age, until, expected):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    return {'now': now.isoformat(), 'booked_at': (now - timedelta(seconds=age)).isoformat(),
            'starts_at': (now + timedelta(seconds=until)).isoformat(), 'expected': expected}


def answer_cases(text):
    """Accept complete operator-card clauses or explicit operator-written example lines."""
    examples = []
    sentences = set()
    for line in text.splitlines():
        if re.match(r'^검사\s+[+\-\d]', line.strip()):
            match = re.fullmatch(r'검사\s+(\d{1,9})\s+(-?\d{1,9})\s+(허용|거부)', line.strip())
            if not match:
                raise ValueError('검사 행은 “검사 300 0 거부” 형식으로 입력하세요.')
            age, until = map(int, match.group(1, 2))
            if age + until <= 0:
                raise ValueError('예약 생성은 이용 시작보다 앞서야 합니다.')
            examples.append(reservation_case(age, until, match[3] == '허용'))
        elif line.strip() != '맥락만':
            sentences.update(s.strip() for s in line.split('.') if s.strip())
    # A free-form qualification can change a card rule; match only entire known clauses.
    general = '일반 취소 마감은 이용 시작 24시간 전입니다'
    cutoff = '정확히 이용 시작 24시간 전이면 일반 취소를 허용합니다'
    grace = '예약 생성 후 10분까지는 일반 취소 마감이 지나도 허용합니다'
    inclusive = '정확히 10분인 경우도 포함합니다'
    start = '현재 시각이 이용 시작 시각과 같거나 이후면, 정정 시간이 남아 있어도 거부합니다'
    if sentences <= ({general, cutoff, grace, inclusive, start} | CONTEXT_ANSWERS):
        if general in sentences:
            examples.append(reservation_case(172800, 172800, True))
        if cutoff in sentences:
            examples.append(reservation_case(172800, 86400, True))
        if grace in sentences:
            examples += [reservation_case(599, 7200, True), reservation_case(300, 1, True)]
            if general in sentences:
                examples.append(reservation_case(601, 7200, False))
            if inclusive in sentences:
                examples.append(reservation_case(600, 7200, True))
        if start in sentences:
            examples += [reservation_case(300, 0, False), reservation_case(300, -1, False)]
    distinct = {}
    for case in examples:
        key = case['booked_at'], case['starts_at']
        if key in distinct and distinct[key]['expected'] != case['expected']:
            raise ValueError('같은 사례에 허용과 거부가 함께 입력됐습니다.')
        distinct[key] = case
    if len(distinct) > 10:
        raise ValueError('한 답변의 검사는 최대 10개입니다.')
    return list(distinct.values())


def verification_status(correct, total, error=None):
    if not total and not error:
        return 'unverified'
    return 'passed' if total and correct == total and not error else 'failed'


def repair_feedback(results):
    return {'instruction': '실패한 입력의 기대값과 실제값을 비교해 분기와 경계를 수정하세요. 이미 통과한 검사도 다시 실행합니다.',
            'failures': [r for r in results if not r['passed']]}


def update_verification(result):
    status = verification_status(result['correct'], result['total'], result.get('error'))
    if result['needs_examples'] and status != 'failed':
        status = 'unverified'
    result.update(status=status, passed=status == 'passed')
    if result['passed']:
        result.pop('repair', None)
    else:
        result['repair'] = repair_feedback(result['results'])
        if not result['total'] and not result.get('error'):
            result['repair']['instruction'] = '실행한 검사가 0건입니다. 공개 요구사항으로 확인 가능한 입력과 기대값을 checks에 제출하세요.'
