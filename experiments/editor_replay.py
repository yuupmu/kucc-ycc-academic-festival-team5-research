"""Compare two D instructions on fixed code and reviewer messages from the cycle run."""
import argparse
import json
from pathlib import Path

from experiments.local_baseline import BENCHMARK, ROOT, SECONDS_ADAPTER, submission_text
from experiments.monitor_cycles import (
    EDITOR, IDS, MAIN, MERGE_FORMAT, SUBMIT, compact, editor_groups, read, recorded, save,
)


ARCHIVE = ROOT / 'experiments/qwen3-review-cycles-20261125'
# Counterbalance condition order. Each pair starts from exactly one archived checkpoint.
PAIRS = [(29, 2, ('summary', 'trace')), (43, 3, ('trace', 'summary'))]
TRACE = (
    '당신은 검토 편집자 D입니다. 현재 코드와 A·B·C의 원문을 모두 읽고 겹치는 지적은 합치고 '
    '출처와 이견을 보존하세요. 코드 동작에 관한 의견은 입력 사례를 골라 함수 맨 위부터 조건을 '
    '순서대로 따라가며 검증하세요. 감시자가 든 사례가 있으면 우선 쓰세요. 어떤 조건에서 처음 '
    '반환되고 결과가 무엇인지, 지적한 조건이 실제 판정에 영향을 주는지 근거와 함께 summary에 '
    '기록하세요. 한 사례로 전체 입력의 동작을 일반화하지 마세요. 현재 동작과 문서상 기대를 '
    '구분하세요. 확인할 수 없는 사항은 판단 불가로 남기고 새 정책이나 수정 코드를 만들지 마세요. '
    '구체적 결함을 찾지 못했으면 그대로 밝히세요.'
)


def fixed_input(seed, cycle):
    directory = ARCHIVE / str(seed)
    reviews = read(directory / f'{cycle}-reviews.json')
    original = read(directory / f'{cycle}-D.json')['request']['messages'][1]['content']
    context, raw = original.split('\n세 감시 의견 원문\n')
    rows = [dict(id=who, **reviews[who], operator_answer='') for who in IDS]
    prior = submission_text(read(directory / f'{cycle-1}-main.json')['text'])
    if rows != json.loads(raw) or json.loads(context)['현재 코드'] != prior:
        raise ValueError(f'Archive mismatch: {seed}/{cycle}')
    return context, original, reviews, [dict(cycle=cycle, **row) for row in rows]


def generate_pairs(out, port):
    for seed, cycle, order in PAIRS:
        context, original, reviews, rows = fixed_input(seed, cycle)
        for arm in order:
            directory = out / str(seed) / arm
            directory.mkdir(parents=True, exist_ok=True)
            editor = recorded(directory / 'D.json', 'D', EDITOR if arm == 'summary' else TRACE,
                              original, seed, 800, port, MERGE_FORMAT)
            groups, missing = editor_groups(editor['text'], reviews)
            packet = dict(groups=groups, questions_and_answers=rows)
            save(directory / 'handoff.json', dict(packet=packet, verbatim_fallback_ids=missing))
            user = (context + '\nD가 정리한 피드백\n' + compact(packet)
                    + '\n확정된 근거와 현재 코드를 대조해 필요한 부분만 수정하세요. ' + SUBMIT)
            recorded(directory / 'main.json', 'main', MAIN, user, seed, 1500, port)
            print(f'Completed {seed}/{cycle} {arm}', flush=True)


def grade_pairs(out):
    from backend.isolated import grade_isolated
    if not all((out / str(s) / arm / 'main.json').exists() for s, _, order in PAIRS for arm in order):
        raise ValueError('All four revisions must be submitted before grading.')
    results = []
    for seed, cycle, order in PAIRS:
        archive = ARCHIVE / str(seed)
        before = read(archive / f'{cycle-1}-score.json')['report']
        for arm in order:
            directory = out / str(seed) / arm
            editor, main = [read(directory / file) for file in ('D.json', 'main.json')]
            report = grade_isolated(submission_text(main['text']) + SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
            save(directory / 'score.json', report)
            if (before['policy_sha256'], before['benchmark_version'], [r['id'] for r in before['results']]) != (
                report['policy_sha256'], report['benchmark_version'], [r['id'] for r in report['results']]):
                raise ValueError('The original and final grading fixtures differ.')
            changes = [(a, b) for a, b in zip(before['results'], report['results']) if a['passed'] != b['passed']]
            calls = [editor, main]
            results.append(dict(seed=seed, cycle=cycle, arm=arm, initial=before['score'], final=report['score'],
                                total=report['total'], fixed=[b['id'] for a, b in changes if b['passed']],
                                lost=[b['id'] for a, b in changes if a['passed']],
                                usage={k: sum(c['usage'][k] for c in calls)
                                       for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
                                seconds=round(sum(c['elapsed_seconds'] for c in calls), 2)))
    save(out / 'results.json', results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('generate', 'grade'))
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18762)
    args = parser.parse_args()
    if args.stage == 'generate':
        generate_pairs(args.out, args.port)
    else:
        grade_pairs(args.out)
