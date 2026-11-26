"""Operator/researcher harness. The general project workflow never imports this module."""
import argparse
import ast
import difflib
import time
from collections import Counter
from pathlib import Path

from backend import project_review as core
from backend.isolated import grade_isolated, run_cases
from experiments import project_review as runner
from experiments.local_baseline import BENCHMARK, SECONDS_ADAPTER
from experiments.local_transport import MODEL, local_server, locked_output, read, recorded, request_body, save


STUDY=Path(__file__).resolve().parent/'project-transfer-20261126'
TASKS=('reservation','triage','labels')


def operator_reply(study,task,arm,version,questions,brief,card):
    selection=study/'operator'/f'{task}-{arm}-{version}.json'
    if not selection.is_file():
        return None
    record=read(selection)
    if record['questions_sha256']!=core.digest(questions) or len(record['selections'])!=len(questions):
        raise ValueError(f'질문 묶음과 대리 응답 선택이 다릅니다: {selection}')
    clauses={**core.sources(brief,[]),**card,'clarify':'어떤 경우의 처리를 물으시는지 조금 더 구체적으로 말씀해 주세요.',
             'unset':'그 경우에 대한 별도의 운영 방침은 정해져 있지 않습니다.'}
    sentences=[]
    for codes in record['selections']:
        if not codes or any(k not in clauses for k in codes):
            raise ValueError(f'고정 카드 또는 공개 명세에 없는 응답: {selection}')
        sentences.extend(clauses[k] for k in codes)
    return '\n'.join(dict.fromkeys(sentences))


def select(study,task,arm,version,selections,reference=None):
    if task not in TASKS or arm not in runner.ARMS or version<1:
        raise ValueError('응답 대상 과제·조건·회차를 확인하세요.')
    run=study/'runs'/task
    if read(run/'state.json')['arms'][arm]!={'version':version,'status':'awaiting_human'}:
        raise ValueError('현재 대기 중인 질문에 응답하세요.')
    questions=read(run/f'round-{version:03}'/arm/'review.json')['questions']
    fixtures=reference or study
    card={**read(fixtures/'operator-cards.json')[task],**core.sources(read(fixtures/'public'/f'{task}.json')['brief'],[])}
    if len(selections)!=len(questions) or any(not group or set(group)-set(card)-{'unset','clarify'} for group in selections):
        raise ValueError('질문별로 실제 카드 문장, unset, clarify 중 해당 항목을 지정하세요.')
    directory=study/'operator'
    directory.mkdir(exist_ok=True)
    runner.freeze(directory/f'{task}-{arm}-{version}.json',
                  dict(questions_sha256=core.digest(questions),questions=questions,selections=selections))


def paired_caller(out,prior):
    def call(path,role,system,user,seed,limit,port,fmt,model):
        source=prior/path.relative_to(out)
        if not path.exists() and source.exists():
            old=read(source)
            messages=[dict(role='system',content=system),dict(role='user',content=user)]
            if old['role']==role and old['model']==model and old['request']==request_body(model,messages,seed,limit,'off',fmt):
                save(path,dict(**old,replayed_from=source.relative_to(prior).as_posix(),original_sha256=core.digest(old)))
        return recorded(path,role,system,user,seed,limit,port,fmt,model)
    return call


def conduct(study,port,reference=None):
    fixtures=reference or study
    cards=read(fixtures/'operator-cards.json')
    with locked_output(study/'runs'),local_server(port):
        while True:
            waiting=False
            progressed=False
            for task in TASKS:
                out=study/'runs'/task
                with locked_output(out):
                    project=read(fixtures/'public'/f'{task}.json')
                    design,state=runner.setup(out,project,263,protocol=core.PROTOCOL if reference else core.TEXT_PROTOCOL)
                    if reference:
                        old=read(reference/'runs'/task/'design.json')
                        if any(design[k]!=old[k] for k in ('project','seed','limits','author_model','review_models','max_versions','prompts_sha256')):
                            raise ValueError('공개 입력, 역할, 시드 또는 예산이 원본과 다릅니다.')
                    for arm,info in state['arms'].items():
                        if info['status']=='awaiting_human':
                            version=info['version']
                            questions=read(out/f'round-{version:03}'/arm/'review.json')['questions']
                            if reference:
                                name=f'{task}-{arm}-{version}.json'
                                prior=reference/'operator'/name
                                target=study/'operator'/name
                                if not target.exists() and prior.exists() and read(prior)['questions']==questions:
                                    target.parent.mkdir(exist_ok=True)
                                    runner.freeze(target,read(prior))
                            response=operator_reply(study,task,arm,version,questions,project['brief'],cards[task])
                            if response is not None:
                                runner.answer(out,state,arm,version,response,'delegated_policy_card')
                    if any(a['status']=='running' for a in state['arms'].values()):
                        invoke=paired_caller(out,reference/'runs'/task) if reference else None
                        runner.advance(out,design,state,{MODEL:port},invoke=invoke)
                        progressed=True
                        print(task,state['arms'],flush=True)
                    waiting|=any(a['status']=='awaiting_human' for a in state['arms'].values())
            if not waiting:
                return
            if not progressed:
                time.sleep(2)


def fixture_verdicts(task,code,cases):
    entry={'reservation':'allow_cancel','triage':'triage','labels':'merge_labels'}[task]
    adapter='\n\ndef simulate(initial_state, events):\n    return {"value": '+entry+'(*initial_state["args"])}\n'
    inputs=[dict(initial_state={'args':row['args']},events=[]) for row in cases]
    outputs=run_cases(code+adapter,inputs,'allocation')
    return {str(i):('보류' if row['error'] else '정답' if row['actual']=={'value':case['expected']} else '오답')
            for i,(row,case) in enumerate(zip(outputs,cases),1)}


def measure(task,files,cases):
    code=next(iter(files.values()))
    if task=='reservation':
        grade=grade_isolated(code+SECONDS_ADAPTER,BENCHMARK,'cancellation_basic')
        return {r['id']:('보류' if r['error'] else '정답' if r['passed'] else '오답') for r in grade['results']}
    return fixture_verdicts(task,code,cases)


def observe(study,reference=None):
    fixtures=reference or study
    cases=read(fixtures/'private-cases.json')
    cards=read(fixtures/'operator-cards.json')
    probes=read(fixtures/'evidence-probes.json')
    results={}
    for task in TASKS:
        out=study/'runs'/task
        if not (out/'state.json').is_file():
            continue
        design,state=read(out/'design.json'),read(out/'state.json')
        graded=study/'research'/task
        graded.mkdir(parents=True,exist_ok=True)
        terminal=all(v['status'] in ('completed','incomplete_limit','incomplete_output') for v in state['arms'].values())
        result=dict(prompt_sha256=design['prompts_sha256'],audited_calls=runner.audit(out) if terminal else None,arms={})
        cache={}
        probe_cache={}
        for arm,info in state['arms'].items():
            versions=[]
            prev=None
            for n in range(1,info['version']+1):
                folder=out/f'round-{n:03}'/arm
                snap=read(folder/'snapshot.json')
                key=snap['sha256']
                if key!=core.digest(snap['files']):
                    raise ValueError('코드 사본의 확인값이 다릅니다.')
                if key not in cache:
                    cache[key]=measure(task,snap['files'],cases.get(task,[]))
                    probe_cache[key]=fixture_verdicts(task,next(iter(snap['files'].values())),probes[task])
                verdicts=cache[key]
                counts=dict(Counter(verdicts.values()))
                review=read(folder/'review.json')
                changes=Counter((prev[k]+' → '+v) for k,v in verdicts.items()) if prev else {}
                try:
                    ast.parse(next(iter(snap['files'].values())))
                    syntax_error=None
                except SyntaxError as error:
                    syntax_error=dict(line=error.lineno,message=error.msg)
                versions.append(dict(version=n,sha256=key,correct=counts.get('정답',0),wrong=counts.get('오답',0),
                                     unanswered=counts.get('보류',0),changes=dict(changes),questions=len(review['questions']),
                                     overlap_findings=sum(len({(a['file'],a['line']) for a in f['locations']})==2
                                                          for r in review['reviews'] for f in r['findings']),
                                     edits=len(snap['applied_edits']),edit_error=snap['edit_error'],syntax_error=syntax_error))
                dest=graded/f'round-{n:03}'/arm
                dest.mkdir(parents=True,exist_ok=True)
                save(dest/'verdicts.json',dict(sha256=key,verdicts=verdicts))
                delivered=set()
                for receipt in state['answers']:
                    if receipt['arm']==arm and receipt['version']<n:
                        selection=read(study/'operator'/f"{task}-{arm}-{receipt['version']}.json")
                        delivered.update(k for group in selection['selections'] for k in group if k in cards[task])
                checks=[dict(choice=probe['choice'],missing=sorted(set(probe['requires'])-delivered),
                             verdict=probe_cache[key][str(i)]) for i,probe in enumerate(probes[task],1)]
                versions[-1]['evidence_probes']=checks
                before=read(out/f'round-{n-1:03}'/arm/'snapshot.json')['files'] if n>1 else design['project']['files']
                patch=''.join(line for name,source in snap['files'].items()
                              for line in difflib.unified_diff(before[name].splitlines(True),source.splitlines(True),f'v{n-1}/{name}',f'v{n}/{name}'))
                (dest/'change.diff').write_text(patch)
                prev=verdicts
            receipts=[a for a in state['answers'] if a['arm']==arm]
            delivered=set()
            exchanges=[]
            for a in receipts:
                if a['source']!='delegated_policy_card' or a['text']!=operator_reply(study,task,arm,a['version'],a['questions'],design['project']['brief'],cards[task]):
                    raise ValueError('연구 실행의 답변 출처가 일치하지 않습니다.')
                choices=read(study/'operator'/f"{task}-{arm}-{a['version']}.json")['selections']
                main,reviewers=set(),set()
                for question,selected in zip(a['questions'],choices):
                    facts=set(selected)&cards[task].keys()
                    if 'main' in question['proposed_by']:
                        main.update(facts)
                    if any(k.startswith('review-') for k in question['proposed_by']):
                        reviewers.update(facts)
                exchanges.append(dict(version=a['version'],questions=len(choices),new_facts=sorted((main|reviewers)-delivered),
                                      new_from_reviewers_only=sorted(reviewers-main-delivered)))
                delivered.update(main|reviewers)
            calls=[read(p) for p in out.glob('round-*/calls/*.json') if p.stem=='shared-main' or p.stem.startswith(arm+'-')]
            if reference:
                for c in calls:
                    if 'replayed_from' in c:
                        original=read(reference/'runs'/task/c['replayed_from'])
                        if c['original_sha256']!=core.digest(original) or original!={k:v for k,v in c.items() if k not in ('original_sha256','replayed_from')}:
                            raise ValueError('원본 모델 호출과 재사용한 기록이 다릅니다.')
            result['arms'][arm]=dict(status=info['status'],versions=versions,reply_batches=len(receipts),exchanges=exchanges,
                                     facts_received=sorted(delivered),calls=len(calls),replayed_calls=sum('replayed_from' in c for c in calls),
                                     tokens=sum(c['usage']['total_tokens'] for c in calls))
        if all(result['arms'][a]['versions'] for a in runner.ARMS):
            old,new=[cache[result['arms'][a]['versions'][-1]['sha256']] for a in runner.ARMS]
            result['self_to_multi']=dict(Counter(old[k]+' → '+new[k] for k in old))
        results[task]=result
    (study/'research').mkdir(exist_ok=True)
    save(study/'research'/'comparison.json',results)
    table=['# 버전별 연구자 관찰', '',
           '숫자는 정답 · 오답 · 미판정이다. 문항마다 판정을 반환했는지와 이전 버전에서 어떻게 바뀌었는지는 각 코드 차이 옆의 verdicts.json에 기록했다.',
           '', '| 과제와 조건 | 1차 | 2차 | 3차 | 4차 | 5차 | 6차 | 상태 |','|---|---|---|---|---|---|---|---|']
    labels={'reservation':'예약 취소','triage':'문의 배정','labels':'표시 태그 병합','self':'단일','multi':'멀티'}
    statuses={'completed':'제출','incomplete_limit':'한도 도달·미제출','incomplete_output':'응답 미완성·미제출',
              'running':'진행 중','awaiting_human':'답변 대기'}
    for task,result in results.items():
        for arm,record in result['arms'].items():
            cells=[f"[{v['correct']} · {v['wrong']} · {v['unanswered']}]({task}/round-{v['version']:03}/{arm}/verdicts.json)"
                   for v in record['versions']]
            cells+=['—']*(6-len(cells))
            table.append('| '+' | '.join([labels[task]+' '+labels[arm],*cells,statuses[record['status']]])+' |')
    (study/'research'/'versions.md').write_text('\n'.join(table)+'\n')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','observe','select'])
    parser.add_argument('selection',nargs='*',help='For select: task arm version then a comma-separated clause list per question')
    parser.add_argument('--study',type=Path,default=STUDY)
    parser.add_argument('--reference',type=Path,help='Earlier run with identical public files, policies and role requests')
    parser.add_argument('--port',type=int,default=18767)
    args=parser.parse_args()
    if args.action=='select':
        task,arm,version,*groups=args.selection
        select(args.study,task,arm,int(version),[g.split(',') for g in groups],args.reference)
    elif args.action=='run':
        conduct(args.study,args.port,args.reference)
    else:
        observe(args.study,args.reference)
