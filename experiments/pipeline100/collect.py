"""Build submissions using only public inputs and the owner's replies. Scoring is a separate entry point."""
import argparse
import ast
from pathlib import Path
from experiments import answer_fidelity as writer, festival_protocol as model, festival_mini as base, repeated_intervention as loop
from experiments import rule_cycle_study as rule, three_cycle_study as old, answer_fidelity_study as fix
from experiments.local_transport import read, recorded, local_server, locked_output
from experiments.project_review import freeze
from experiments.rule_cycle_calls import Calls
from backend.structured_output import obj

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs'
TASKS=('reservation','triage')

def bank_dirs(task):
    first,parent,prior,_,_=rule.load_public(task)
    dates=[p/'calls' for p in (first,parent,prior,base.STUDY/'refined-v2'/task)]
    for root in (old.STUDY/'runs',fix.STUDY/'runs',OUT):
        dates.extend(sorted((root/task).glob('*/cycle-*/calls')))
    dates.extend(sorted((OUT/task).glob('*/calls')))
    dates.extend(sorted((OUT/task).glob('*/initial/calls')))
    return dates

class Bank(Calls):
    def reuse(self,path,role,system,user,seed,limit,port,fmt,model_id):
        note=self.out/'billing'/path.name
        if not path.exists():
            origin=next((d/path.name for d in self.prior if (d/path.name).is_file()),None)
            if origin:
                freeze(path,read(origin))
            result=recorded(path,role,system,user,seed,limit,port,fmt,model_id)
            note.parent.mkdir(exist_ok=True)
            freeze(note,dict(origin=str(origin.relative_to(base.ROOT)) if origin else 'new'))
            return result
        if not note.is_file():
            raise ValueError('호출 재사용 경로가 없습니다.')
        return recorded(path,role,system,user,seed,limit,port,fmt,model_id)

def ctx(task,folder,port):
    folder.mkdir(parents=True,exist_ok=True)
    _,_,_,design,draft=rule.load_public(task)
    return design,draft,Bank(folder,design,port,bank_dirs(task))

def archive_answers(task,questions):
    files=sorted((base.STUDY/'operator').glob(f'{task}-*.json'))
    files += [rule.STUDY/'runs'/task/'operator.json']
    for f in files:
        item=read(f)
        if item['questions']==questions:
            return item['selections'],f
    for path in sorted((old.STUDY/'runs'/task).glob('*/cycle-*/answer.json')):
        if read(path)['questions']==questions:
            return read(path.parent/'operator.json')['selections'],path
    return None

def operator(folder,task,qs,groups=None):
    path=folder/'operator.json'
    if not qs:
        return None
    if path.is_file():
        row=read(path)
        assert row['questions']==qs and rule.compose(task,row['selections'])==row['text']
        if groups is not None and groups!=row['selections']:
            raise ValueError('이미 확정한 담당자 회신입니다.')
        return row
    past=archive_answers(task,qs) if groups is None else None
    if not past and groups is None:
        return None
    chosen=past[0] if past else groups
    assert len(chosen)==len(qs)
    row=dict(questions=qs,selections=chosen,text=rule.compose(task,chosen),
             source='delegated_policy_card',origin=str(past[1].relative_to(base.ROOT)) if past else '대리 담당자가 이번 질문 원문을 읽고 선택')
    freeze(path,row)
    return row

def need(task,arm,n,folder,qs):
    freeze(folder/'window.json',dict(questions=qs,task=task,arm=arm,cycle=n))
    answer=operator(folder,task,qs)
    if qs and answer is None:
        print('담당자 회신 대기',task,arm,n,flush=True)
        for i,q in enumerate(qs,1):
            print(i,q['question'],flush=True)
    return answer

def adaptive(task,arm,port):
    out=OUT/task/arm
    if (out/'final.json').is_file():
        return
    role=arm.split('-')[-1]
    design,draft,initial=ctx(task,out/'initial',port)
    snap,review=model.record_version(out/'initial',design,'self' if role=='self' else 'solo',1,None,[],port,invoke=initial.reuse)
    assert snap['files']==draft['files']
    prev,receipts,prior=snap['files'],[],None
    for n in (1,2,3):
        folder=out/f'cycle-{n}'
        _,_,ask=ctx(task,folder,port)
        if n==1 and role=='self':
            inquiry=dict(questions=review['questions'],calls=review['calls'][1:],reviews=review['reviewers'],
                         withheld=review['withheld'],invalid=review['status']=='invalid_output')
        else:
            inquiry=loop.questions_for(design['project'],prev,role,design['seed'],ask,receipts)
        intake=loop.intake_for(n,role,prev,receipts,inquiry)
        freeze(folder/'intake.json',intake)
        response=need(task,arm,n,folder,intake['questions'])
        if intake['questions'] and not response:
            return
        if response:
            receipts.append(loop.accept(folder,intake,response['text'],'delegated_policy_card'))
        outcome=writer.revise(design['project'],prev,receipts,design['seed'],role,ask,prior)
        current=loop.snapshot(n,prev,intake,receipts,outcome,[snap['author_call']] if n==1 else [])
        freeze(folder/'snapshot.json',current)
        prev,prior=current['files'],current['writer']
    loop.finish(out,current)
    print('제출 고정',task,arm,flush=True)

def p1(task,port):
    out=OUT/task/'p1'
    if (out/'final.json').is_file():
        return
    design,draft,ask=ctx(task,out,port)
    design=model.spec(design['project'],design['seed'],design['model'],('p1',),2)
    snap,review=model.record_version(out,design,'p1',1,None,[],port,invoke=ask.reuse)
    assert draft['files']==snap['files']
    folder=out/'cycle-1'
    folder.mkdir(exist_ok=True)
    answer=need(task,'p1',1,folder,review['questions'])
    if review['questions'] and not answer:
        return
    receipts=[dict(version=1,arm='p1',text=answer['text'],source='delegated_policy_card')] if answer else []
    if review['status'] in model.TERMINAL:
        final,last=snap,review
        calls=review['calls']
    else:
        final,last=model.record_version(out,design,'p1',2,snap,receipts,port,invoke=ask.reuse)
        calls=review['calls']+last['calls']
    freeze(out/'final.json',dict(files=final['files'],sha256=final['sha256'],calls=calls,status=last['status']))
    print('제출 고정',task,'p1',flush=True)

def choices(task,port):
    out=OUT/task/'choices'
    if (out/'final.json').is_file():
        return
    design,draft,ask=ctx(task,out,port)
    brief=design['project']['brief']
    files=draft['files']
    methods=('공개 규칙의 적용 순서를 살펴보세요.','입력의 의미를 구분하고 조건들을 조합하세요.','겹치는 규칙과 예외의 우선순위를 살펴보세요.')
    arms={}
    for arm in ('independent','serial'):
        pool={'draft':files}
        calls=[draft['author_call']]
        invalid=[]
        for member,method in zip('ABC',methods):
            payload={'공개 요청':brief,'초안':files}
            if arm=='serial' and member!='A':
                payload['같은 작성자의 이전 수정안']={k:v for k,v in pool.items() if k!='draft'}
            call,answer=ask('alternative-'+member,'대체 구현을 작성하세요. '+method+' 정보가 부족하면 해당 분기를 보류하세요. 전체 파일을 제출하세요.',
                            payload,model.author_schema(files),design['seed'],model.AUTHOR_LIMIT)
            calls.append(call)
            good=bool(answer)
            if good:
                try:
                    for v in answer['files'].values():
                        ast.parse(v)
                except (SyntaxError,ValueError):
                    good=False
            if good:
                pool[member]=answer['files']
            else:
                invalid.append(member)
            if member=='A':
                pick='A' if good else 'draft'
                arms['short']=dict(files=pool[pick],sha256=model.core.digest(pool[pick]),calls=calls.copy(),status='submitted',chosen=pick)
        key,picked=ask('selector-D' if arm=='independent' else 'self-selector',
                       '공개 명세와 코드만 읽고 제출할 후보 하나를 선택하세요.',
                       {'공개 요청':brief,'후보':pool},obj({'chosen':{'type':'string','enum':list(pool)}}),design['seed'],80)
        take=picked['chosen'] if picked else 'draft'
        arms[arm]=dict(files=pool[take],sha256=model.core.digest(pool[take]),calls=calls+[key],chosen=take,
                       status='submitted' if picked else 'invalid_selector',invalid_candidates=invalid)
    freeze(out/'final.json',arms)
    print('제출 고정',task,'코드만 선택하는 세 방식',flush=True)

def main():
    cmd=argparse.ArgumentParser()
    cmd.add_argument('action',choices=('collect','answer'))
    cmd.add_argument('args',nargs='*')
    a=cmd.parse_args()
    if not (ROOT/'protocol.json').is_file():
        raise ValueError('100문항 설계가 먼저 고정되어야 합니다.')
    with locked_output(OUT):
        if a.action=='answer':
            task,arm,n,*groups=a.args
            assert task in TASKS and arm in ('live-self','live-multi','p1') and n in ('1','2','3')
            folder=OUT/task/arm/f'cycle-{n}'
            operator(folder,task,read(folder/'window.json')['questions'],[g.split(',') for g in groups])
            return
        with local_server(18773,model.MODEL):
            for task in TASKS:
                adaptive(task,'live-multi',18773)
                adaptive(task,'live-self',18773)
                p1(task,18773)
            for task in TASKS:
                choices(task,18773)
        if all((OUT/t/a/'final.json').is_file() for t in TASKS for a in ('live-multi','live-self','p1','choices')):
            paths=sorted(OUT.glob('*/*/final.json'))
            freeze(ROOT/'submission-manifest.json',{str(p.relative_to(ROOT)):base.checksum(p) for p in paths})

if __name__=='__main__':
    main()
