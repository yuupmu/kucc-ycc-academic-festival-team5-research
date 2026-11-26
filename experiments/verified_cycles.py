"""Compare one-shot, self-review and A/B/C/D using the same draft and executable evidence."""
import argparse
import hashlib
from pathlib import Path

from backend.isolated import grade_isolated, run_cases
from experiments.local_baseline import BENCHMARK, ROOT, SECONDS_ADAPTER, submission_text
from experiments.monitor_cycles import (
    EDITOR, IDS, MAIN, MERGE_FORMAT, MODEL, SUBMIT, compact, editor_groups, public_brief,
    locked_output, read, recorded, save,
)
from experiments.monitor_pilot import FORMAT, parsed_feedback


SEEDS = (17, 29, 43, 71, 89, 113)
ARMS = ('self_short', 'self_serial', 'abcd')
EXPERIMENTS = ROOT / 'experiments'
VIEWS = (
    '어떤 요구사항의 실패가 관측됐는지 입력 쌍을 비교하세요.',
    '같은 입력에서 처음 적용되는 조건과 반환을 확인하고 최소 수정의 근거를 설명하세요.',
    '확정된 규칙과 가정을 구분하고 수정으로 깨질 수 있는 기존 동작을 하나 확인하세요.',
)
REVISION = ('실행 표의 actual은 Python에서 관측한 값입니다. 실패 사례의 원인을 고치고 통과한 동작을 '
            '보존하세요. 특정 입력을 하드코딩하지 마세요. 규정되지 않은 수치가 필요하면 한 곳에 '
            '가정이라고 표시하세요. ' + SUBMIT)
REVIEW = (' 공개된 명세와 실행 표를 근거로 삼으세요. question에 남은 정책 질문을, feedback에 '
          '수정에 필요한 근거를 간결하게 적으세요.')
REPAIR_DESIGN = dict(max_extra_main_calls=1, applies_to=list(ARMS),
                     trigger='retained candidate fails an available specification example',
                     evidence='all observed assertions and contrasting pairs with one identical argument',
                     selection='strict superset of passing specification examples', feedback_from_grader=False)

# Examples derived from the customer notice. Neither boundary inclusion nor the duration of the
# unspecified correction period is tested in the public-only condition.
NOTICE_CHECKS = (
    (259200, 129600, True, '일반 마감 전'),
    (259200, 21600, False, '일반 마감 후 오래된 예약'),
    (0, 21600, True, '같은 시각에 방금 생성한 예약의 정정'),
    (259200, -3600, False, '오래된 예약, 이용 시작 후'),
)
# Only available alongside the previously published full-information *model prompt*.
DISCLOSED_CHECKS = (
    (259200, 86400, True, '일반 마감 정각 포함'),
    (600, 21600, True, '정정 기한 정각 포함'),
    (601, 21600, False, '정정 기한 초과'),
    (90, 0, False, '이용 시작 정각 우선'),
    (90, -30, False, '이용 시작 이후 우선'),
)


def specification(info):
    if info == 'public':
        brief = public_brief()
        return MAIN, brief + '\n\n' + SUBMIT, brief, NOTICE_CHECKS
    design = read(EXPERIMENTS / 'full-information-single-20261125/design.json')
    system, user = design['tasks']['cancellation_basic']['messages']
    return system['content'], user['content'], user['content'], NOTICE_CHECKS + DISCLOSED_CHECKS


def observe(code, checks):
    adapter = '\n\ndef can_cancel(age, until, unused):\n    return allow_cancel(age, until)\n'
    # The isolated runner calls can_cancel(now, booked_at, starts_at) positionally.
    inputs = [dict(now=age, booked_at=until, starts_at=0) for age, until, _, _ in checks]
    actuals = run_cases(code + adapter, inputs)
    return [dict(age_seconds=age, until_start_seconds=until, expected=expected, basis=basis,
                 **row, passed=row['error'] is None and row['actual'] is expected)
            for (age, until, expected, basis), row in zip(checks, actuals)]


def improves(before, after):
    old = {i for i, row in enumerate(before) if row['passed']}
    new = {i for i, row in enumerate(after) if row['passed']}
    return old < new


def review_packet(d, arm, context, seed, port):
    reviews = {}
    for role, view in zip(IDS, VIEWS):
        independent = arm == 'abcd'
        system = '당신은 메인 코드의 독립 감시자입니다.' if independent else MAIN
        prior = '' if independent else '\n내 앞선 검토\n' + compact(reviews)
        call = recorded(d/f'{role}.json', role, system, context + prior + '\n' + view + REVIEW,
                        seed, 320, port, FORMAT)
        reviews[role] = parsed_feedback(call)
    instruction = EDITOR if arm == 'abcd' else '같은 개발자로서 세 차례의 자체 검토를 출처 ID별로 요약하세요.'
    call = recorded(d/'D.json', 'D', instruction, context + '\n검토 원문\n' + compact(reviews),
                    seed, 800, port, MERGE_FORMAT)
    groups, missing = editor_groups(call['text'], reviews)
    return dict(groups=groups, verbatim_reviews=reviews, fallback_ids=missing)


def run_arm(d, arm, brief, code, checks, before, seed, port):
    d.mkdir(exist_ok=True)
    if all(row['passed'] for row in before):
        decision = dict(selected='draft', reason='all_public_checks_passed', checks=before)
    else:
        context = compact({'명세': brief, '현재 코드': code, '실행 표': before})
        packet = {} if arm == 'self_short' else review_packet(d, arm, context, seed, port)
        prompt = (context + ('\n검토 전달문\n' + compact(packet) if packet else '') + '\n' + REVISION)
        revised = recorded(d/'revision.json', 'main', MAIN, prompt, seed, 1500, port)
        after = observe(submission_text(revised['text']), checks)
        accepted = improves(before, after)
        decision = dict(selected='revision' if accepted else 'draft',
                        reason='improved_without_regression' if accepted else 'no_strict_improvement', checks=after)
        save(d/'handoff.json', packet)
    save(d/'decision.json', decision)


def generate_all(out, port, seeds):
    for info in ('public', 'full'):
        system, prompt, brief, checks = specification(info)
        for index, seed in enumerate(seeds):
            d = out/info/str(seed)
            d.mkdir(parents=True, exist_ok=True)
            draft = recorded(d/'draft.json', 'main', system, prompt, seed, 1500, port)
            code = submission_text(draft['text'])
            before = observe(code, checks)
            save(d/'checks.json', before)
            # Rotate order across seeds. All arms use fresh contexts and one shared draft.
            offset = index % len(ARMS)
            for arm in ARMS[offset:] + ARMS[:offset]:
                run_arm(d/arm, arm, brief, code, checks, before, seed, port)
                print(info, seed, arm, read(d/arm/'decision.json')['reason'], flush=True)


def contrast_report(rows):
    lines = []
    for i, row in enumerate(rows):
        state = '통과' if row['passed'] else '실패'
        lines.append(f"{i + 1}. [{state}] assert allow_cancel({row['age_seconds']}, "
                     f"{row['until_start_seconds']}) is {row['expected']}  # 실제 {row['actual']!r}, "
                     f"{row['basis']}" + (f", {row['error']}" if row['error'] else ''))
    for i, left in enumerate(rows):
        for j, right in enumerate(rows[i + 1:], i + 1):
            if left['expected'] == right['expected'] or (left['passed'] and right['passed']):
                continue
            for fixed, changed in (('until_start_seconds', 'age_seconds'), ('age_seconds', 'until_start_seconds')):
                if left[fixed] == right[fixed]:
                    lines.append(f"{i + 1}번과 {j + 1}번은 {fixed}={left[fixed]}로 같다. "
                                 f"{changed}만 달라 기대값이 달라진다.")
    return '\n'.join(lines)


def repair_remaining(out, seeds, port):
    """One additional main call only if the first retained candidate still fails public checks."""
    for info in ('public', 'full'):
        _, _, brief, checks = specification(info)
        for seed in seeds:
            d = out/info/str(seed)
            for arm in ARMS:
                target = d/arm
                first = read(target/'decision.json')
                selected = first['selected']
                rows = read(d/'checks.json') if selected == 'draft' else first['checks']
                final = dict(selected=selected, reason='all_public_checks_passed', checks=rows)
                if not all(r['passed'] for r in rows):
                    path = d/'draft.json' if selected == 'draft' else target/'revision.json'
                    code = submission_text(read(path)['text'])
                    user = (brief + '\n현재 채택한 함수\n' + code +
                            '\n이 함수에서 실제로 실행한 검사의 기대값과 관측값\n' + contrast_report(rows) +
                            '\n실패한 검사와 짝이 되는 통과 검사를 한꺼번에 만족하도록 분기를 고치세요. '
                            '명세에서 범위가 정해지지 않았다면 합리적인 가정을 명시하고 일반화하세요. '
                            '검사에 나온 입력만 예외 처리하지 마세요. ' + SUBMIT)
                    call = recorded(target/'repair.json', 'main', MAIN, user, seed, 1500, port)
                    after = observe(submission_text(call['text']), checks)
                    accepted = improves(rows, after)
                    final = dict(selected='repair' if accepted else selected,
                                 reason='improved_without_regression' if accepted else 'repair_limit',
                                 checks=after if accepted else rows, attempted_checks=after)
                save(target/'final-decision.json', final)


def score_all(out, seeds, repaired=False):
    dirs = [(info, seed, out/info/str(seed)) for info in ('public', 'full') for seed in seeds]
    decision = 'final-decision.json' if repaired else 'decision.json'
    if not all((d/arm/decision).is_file() for _, _, d in dirs for arm in ARMS):
        raise ValueError('모든 조건의 제출을 고정한 뒤 채점합니다.')
    if repaired:
        from experiments.cancellation_transfer import transfer_checks
        extra_checks = transfer_checks(NOTICE_CHECKS + DISCLOSED_CHECKS)
    results = []
    for info, seed, d in dirs:
        draft = read(d/'draft.json')
        for arm in ('direct',) + ARMS:
            calls = [draft]
            final = draft
            if arm != 'direct':
                stages = (*IDS, 'D', 'revision', 'repair') if repaired else (*IDS, 'D', 'revision')
                for name in stages:
                    path = d/arm/f'{name}.json'
                    if path.exists():
                        calls.append(read(path))
                selected = read(d/arm/decision)['selected']
                if selected != 'draft':
                    final = read(d/arm/f'{selected}.json')
            source = submission_text(final['text'])
            report = grade_isolated(source + SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
            target = d if arm == 'direct' else d/arm
            save(target/('final-score.json' if repaired else 'score.json'), report)
            if arm == 'direct':
                baseline = report
            if ([r['id'] for r in baseline['results']] != [r['id'] for r in report['results']]
                    or baseline['policy_sha256'] != report['policy_sha256']):
                raise ValueError('채점 기준이 일치하지 않습니다.')
            changes = [b for a, b in zip(baseline['results'], report['results']) if a['passed'] != b['passed']]
            results.append(dict(info=info, seed=seed, arm=arm, score=report['score'], total=report['total'],
                                fixed=[r['id'] for r in changes if r['passed']],
                                lost=[r['id'] for r in changes if not r['passed']], calls=len(calls),
                                tokens=sum(c['usage']['total_tokens'] for c in calls),
                                model_seconds=round(sum(c['elapsed_seconds'] for c in calls), 2),
                                code_sha256=hashlib.sha256(source.encode()).hexdigest()))
            if repaired:
                extra = observe(source, extra_checks)
                save(target/'transfer-score.json', extra)
                results[-1].update(transfer_score=sum(r['passed'] for r in extra), transfer_total=len(extra))
    save(out/('final-results.json' if repaired else 'results.json'), results)
    if repaired:
        for info in ('public', 'full'):
            for arm in ('direct',) + ARMS:
                group = [r for r in results if (r['info'], r['arm']) == (info, arm)]
                print(f"{info} {arm}: {sum(r['score'] for r in group)}/{sum(r['total'] for r in group)}, "
                      f"{sum(r['calls'] for r in group)} calls, {sum(r['tokens'] for r in group)} tokens",
                      flush=True)


def run(out, port, seeds=SEEDS):
    with locked_output(out):
        run_locked(out, port, seeds)


def run_locked(out, port, seeds):
    design = dict(protocol='executable-review-v1', model=MODEL, seeds=list(seeds), arms=['direct', *ARMS],
                  task='cancellation_basic', rounds=1, operator_answers=False,
                  specs={i: dict(checks=list(map(list, specification(i)[3])),
                                 draft_prompt=specification(i)[1]) for i in ('public', 'full')})
    path = out/'design.json'
    if path.exists():
        if read(path) != design:
            raise ValueError('실행 조건이 다른 폴더입니다.')
    elif any(out.iterdir()):
        raise ValueError('새 결과 폴더 또는 같은 설계로 시작한 폴더를 사용하세요.')
    else:
        save(path, design)
    repair_plan = out/'repair-design.json'
    if repair_plan.exists() and read(repair_plan) != REPAIR_DESIGN:
        raise ValueError('기존 실행의 추가 수정 조건이 다릅니다.')
    save(repair_plan, REPAIR_DESIGN)
    generate_all(out, port, seeds)
    repair_remaining(out, seeds, port)
    score_all(out, seeds)
    score_all(out, seeds, repaired=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18767, help='Already running local llama-server')
    args = parser.parse_args()
    run(args.out, args.port)
