"""Post-submission diagnostic for new input pairs under the disclosed basic policy."""
from datetime import datetime

from reservation_benchmark.score import load_cases


AGES = (37, 277, 587, 600, 613, 1537, 7943, 169021)
STARTS = (-13, 0, 13, 8937, 86393, 86400, 86407)


def permitted(age, until):
    return until > 0 and (until >= 24 * 3600 or age <= 10 * 60)


def transfer_checks(visible):
    cases, answers, _, _ = load_cases(basic=True)
    used = {(age, until) for age, until, _, _ in visible}
    for row in cases:
        now, booked, starts = [datetime.fromisoformat(row[k]) for k in ('now', 'booked_at', 'starts_at')]
        age, until = int((now-booked).total_seconds()), int((starts-now).total_seconds())
        if permitted(age, until) is not answers[row['id']]['allowed']:
            raise ValueError('추가 입력의 판정 규칙이 기존 채점 기준과 다릅니다.')
        used.add((age, until))
    pairs = [(age, until) for age in AGES for until in STARTS]
    if any((age, until) in used or age + until <= 0 for age, until in pairs):
        raise ValueError('추가 평가 입력이 겹치거나 유효하지 않습니다.')
    return [(age, until, permitted(age, until), '별도 입력 평가') for age, until in pairs]
