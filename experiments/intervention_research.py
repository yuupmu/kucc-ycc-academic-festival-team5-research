"""Researcher-only scoring of immutable code versions. The inference process consumes none of these outputs."""
import argparse
import difflib
import fcntl
import os
from pathlib import Path

from backend.isolated import grade_isolated
from experiments.blind_candidates import digest
from experiments.local_baseline import BENCHMARK, SECONDS_ADAPTER
from experiments.monitor_cycles import read, save


def research_directory(run):
    return run.with_name(run.name+'-research')


def compare(previous, current):
    before = {r['id']:r for r in previous['results']}
    after = {r['id']:r for r in current['results']}
    if before.keys() != after.keys():
        raise ValueError('평가 문항이 다른 버전입니다.')
    return {
        'corrected':[i for i in before if not before[i]['passed'] and after[i]['passed']],
        'regressed':[i for i in before if before[i]['passed'] and not after[i]['passed']],
        'newly_answered':[i for i in before if before[i]['error'] and not after[i]['error']],
        'newly_unanswered':[i for i in before if not before[i]['error'] and after[i]['error']],
    }


def inspect_snapshot(snap, directory, previous):
    code, version = snap['code'], snap['version']
    file = directory/'grade.json'
    stored = read(file) if file.exists() else {}
    if stored and stored.get('sha256') != snap['sha256']:
        raise ValueError('이미 채점한 버전의 내용이 바뀌었습니다.')
    report = stored.get('report')
    result = dict(arm=snap['arm'],version=version,sha256=snap['sha256'])
    if report is None:
        try:
            report = grade_isolated(code+SECONDS_ADAPTER,BENCHMARK,'cancellation_basic')
        except (OSError,RuntimeError,ValueError) as error:
            result['evaluation_error'] = str(error)
    result['report'] = report
    result['delta'] = compare(previous[1],report) if previous and previous[1] and report else None
    if result != stored:
        save(file,result)
    diff_file = directory/'change.diff'
    if not diff_file.exists():
        patch = difflib.unified_diff(previous[0].splitlines(True) if previous else [], code.splitlines(True),
                                     fromfile=f'v{version-1}',tofile=f'v{version}')
        diff_file.write_text(''.join(patch))
    return result


def observe(run):
    run = run.resolve()
    if read(run/'design.json').get('protocol') not in ('human-intervention-v1','human-intervention-v2','human-intervention-guided-v1',
                                                      'human-intervention-ordered-v1','human-intervention-source-thresholds-v1',
                                                      'human-intervention-bound-ordered-v1'):
        raise ValueError('사람의 판단을 받는 실험 폴더를 지정하세요.')
    destination = research_directory(run)
    destination.mkdir(exist_ok=True)
    fd = os.open(destination, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        history, rows = {}, []
        for path in sorted(run.glob('round-*/*/snapshot.json')):
            snap = read(path)
            code, arm, version = snap['code'], snap['arm'], snap['version']
            if digest(code) != snap['sha256']:
                raise ValueError('저장된 코드와 확인값이 다릅니다.')
            directory = destination/path.parent.parent.name/arm
            directory.mkdir(parents=True, exist_ok=True)
            result=inspect_snapshot(snap,directory,history.get(arm))
            report = result['report']
            history[arm] = code, report
            rows.append(dict(version=version,arm=arm,score=report['score'] if report else None,total=report['total'] if report else None,
                             returned=sum(r['error'] is None for r in report['results']) if report else None,
                             corrected=len(result['delta']['corrected']) if result['delta'] else None,
                             regressed=len(result['delta']['regressed']) if result['delta'] else None,
                             code_sha256=snap['sha256']))
        state = read(run/'state.json') if (run/'state.json').is_file() else {}
        requests = [read(f) for f in sorted([*run.glob('round-*/questions.json'), *run.glob('round-*/*/questions.json')])]
        calls = [read(f) for f in run.glob('round-*/calls/*.json')]
        usage = {}
        for arm in ('self','multi'):
            charged = [c for c in calls if c['role'] == 'shared-main' or c['role'].startswith(arm+'-')]
            arm_answers = [a for a in state.get('answers',[]) if a.get('arm',arm)==arm]
            usage[arm] = dict(calls=len(charged), tokens=sum(c['usage']['total_tokens'] for c in charged),
                              model_seconds=round(sum(c['elapsed_seconds'] for c in charged),2),
                              question_batches=sum(p.get('arm',arm)==arm for p in requests),
                              questions=sum(len(p['groups']) for p in requests if p.get('arm',arm)==arm),
                              replies=len(arm_answers),
                              clarification_only=sum(a.get('source')=='delegated_policy_card' and not a.get('scoped_replies') for a in arm_answers),
                              facts_received=sorted({k for a in arm_answers for k in a.get('scoped_replies',{})}))
        manual = [a for a in state.get('answers',[]) if a.get('source','human')=='human']
        proxy = [a for a in state.get('answers',[]) if a.get('source')=='delegated_policy_card']
        arm_status = state.get('arms') or {arm:{'status':state.get('status'),'version':state.get('version')} for arm in usage}
        submitted = {r['arm']:{'version':r['version'],'score':r['score'],'total':r['total']} for r in rows
                     if arm_status[r['arm']]['status']=='completed' and arm_status[r['arm']]['version']==r['version']}
        summary = dict(status=state.get('status'),arm_status=arm_status,submissions=submitted,versions=rows,usage=usage,
                       human_replies=len(manual),delegated_replies=len(proxy), question_batches=len(requests),
                       question_groups=sum(len(p['groups']) for p in requests),
                       human_wait_seconds=round(sum(r['wait_seconds'] for r in manual),2),
                       delegated_wait_seconds=round(sum(r['wait_seconds'] for r in proxy),2))
        save(destination/'summary.json',summary)
        table = ['# 연구자용 버전별 관찰', '',
                 '이 기록은 모델에 전달되지 않는다. 미완성 초안에서는 판정한 문항 수도 함께 확인한다.', '',
                 '| 버전 | 방식 | 정답 / 전체 | 판정을 반환한 문항 | 오답·미판정→정답 | 정답→오답·미판정 |',
                 '|---:|---|---:|---:|---:|---:|']
        for row in rows:
            label = '메인+검토자 3명' if row['arm']=='multi' else '단일 자체 검토'
            corrected = '–' if row['corrected'] is None else row['corrected']
            regressed = '–' if row['regressed'] is None else row['regressed']
            score = '평가 보류' if row['score'] is None else f"{row['score']}/{row['total']}"
            returned = '–' if row['returned'] is None else row['returned']
            table.append(f"| {row['version']} | {label} | {score} | {returned} | {corrected} | {regressed} |")
        for arm,label in [('self','단일'),('multi','메인+검토자')]:
            info = usage[arm]
            status = summary['arm_status'].get(arm,{}).get('status') or summary['status']
            status_text={'completed':'제출 완료','incomplete_limit':'버전 한도 도달, 미제출','incomplete_output':'모델 출력 불완전, 미제출',
                         'running':'진행 중','awaiting_human':'담당자 답변 대기'}.get(status,status)
            table.extend(['',f"{label} 상태 · {status_text}. 누적 {info['calls']}회 호출, {info['tokens']:,}토큰, 모델 응답 {info['model_seconds']}초. "
                          f"질문 {info['questions']}개, 답변 {info['replies']}묶음, 대리 응답 중 재질문 요청만 {info['clarification_only']}묶음."])
        table.extend(['', f"질문 묶음 {len(requests)}회, 사람의 직접 답변 {len(manual)}회, 승인된 정책 카드 대리 응답 {len(proxy)}회. "
                      f"사람의 직접 답변 대기 시간 합계 {summary['human_wait_seconds']}초.", '',
                      '각 버전의 change.diff에 이전 코드와의 차이가, grade.json에 문항별 변화가 있다.'])
        tmp = destination/'overview.tmp'
        tmp.write_text('\n'.join(table)+'\n')
        tmp.replace(destination/'overview.md')
        return summary
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    observe(parser.parse_args().run)
