"""Normalize actual submissions, token receipts and owner transcripts without rerunning a model."""
from pathlib import Path
from functools import lru_cache
from experiments import festival_mini as mini, answer_fidelity_study as fix, three_cycle_study as old, rule_cycle_study as rule
from experiments.festival_protocol import core
from experiments.pipeline100.collect import OUT,bank_dirs
from experiments.local_transport import read

ARCH=mini.ROOT/'experiments'
LABEL={
 'solo':'① 단독 초안','self':'② 자체 질문 · 기본 작성','p1':'③ P1 공통 관점','p2':'③ P2 관점 분담','p3':'③ P3 두 결과 대조',
 'p4':'③ P4 질문 정리','current':'③ P4 편집 보류 추가','infer':'③ 능동 질문 · 기존 작성',
 'self-apply':'② 자체 질문 · 일반 코드','apply':'③ P4 질문 · 일반 코드','both':'③ 능동 질문 · 일반 코드',
 'self-program':'② 자체 질문 · 자유 조건식','apply-program':'③ P4 질문 · 자유 조건식','both-program':'③ 능동 질문 · 자유 조건식',
 'self-regions':'② 자체 질문 · 입력 구간','apply-regions':'③ P4 질문 · 입력 구간','both-regions':'③ 능동 질문 · 입력 구간',
 'old-self':'② 기존 3회차','old-multi':'③ 기존 3회차','fixed-self':'② 회신 반영 · 질문 고정','fixed-multi':'③ 회신 반영 · 질문 고정',
 'live-self':'② 회신 반영 · 실제 후속 질문','live-multi':'③ 회신 반영 · 실제 후속 질문',
 'short':'무질문 · 단일 대안','serial':'무질문 · 순차 후보 선택','independent':'무질문 · 독립 A·B·C와 D 선택'}
def rel(p):
    return str(p.relative_to(mini.ROOT))
@lru_cache(maxsize=None)
def token_record(path):
    row=read(path)
    if core.digest([row['role'],row['request']])!=path.stem:
        raise ValueError('호출 원문과 식별값이 다릅니다.')
    return row['usage'],row['elapsed_seconds'],row['role']
def rawcost(keys,dirs):
    counts=dict(prompt_tokens=0,completion_tokens=0,total_tokens=0)
    seconds=0
    for k in keys:
        source=next(d/(k+'.json') for d in dirs if (d/(k+'.json')).exists())
        u,time,_=token_record(source)
        assert u['prompt_tokens']+u['completion_tokens']==u['total_tokens']
        for name in counts:
            counts[name]+=u[name]
        seconds+=time
    return dict(**counts,calls=len(keys),seconds=round(seconds,2))
def window(task,n,qs,groups,text,path,origin=None):
    if not qs:
        return None
    assert len(groups)==len(qs) and rule.compose(task,groups)==text
    return dict(cycle=n,source=rel(path),origin=origin or '보존된 실제 회신',text=text,questions=[
        dict(by='·'.join(q.get('proposed_by',[])),question=q['question'],facts=g,
             answer=rule.compose(task,[g])) for q,g in zip(qs,groups)])
def normalized(task,arm,cycle,snap,path,keys,dirs,windows,final=True,unsent=()):
    assert snap['sha256']==core.digest(snap['files'])
    return dict(task=task,arm=arm,cycle=cycle,final=final,files=snap['files'],sha=snap['sha256'],
                status=snap['status'],source=rel(path),windows=[w for w in windows if w],unsent=list(unsent),
                **rawcost(keys,dirs))
def collect(task):
    dirs=bank_dirs(task)
    for arm in ('solo','self','p2','p3','p4'):
        root=mini.STUDY/('refined-v2' if arm=='p4' else 'runs')/task
        state=read(root/'state.json')
        control=state['arms'][arm];n=control['version']
        source=root/arm/f'v{n}'/'snapshot.json'
        snap=read(source);snap['status']=control['status']
        calls=[k for i in range(1,n+1) for k in read(root/arm/f'v{i}'/'review.json')['calls']]
        wins=[]
        for a in state['answers']:
            if a['arm']==arm:
                p=mini.selection_path(task,arm,a['version']);g=read(p)
                assert g['questions']==a['questions'] and g['text']==a['text']
                wins.append(window(task,a['version'],a['questions'],g['selections'],a['text'],p))
        yield normalized(task,arm,0 if arm=='solo' else 1,snap,source,calls,[root/'calls',*dirs],wins)
    root=OUT/task/'p1'
    p=root/'final.json';s=read(p)
    qs=read(root/'cycle-1/window.json')['questions']
    op=root/'cycle-1/operator.json'
    w=window(task,1,qs,read(op)['selections'],read(op)['text'],op,read(op)['origin']) if qs else None
    yield normalized(task,'p1',1,s,p,s['calls'],[root/'calls',*dirs],[w])
    root=rule.STUDY/'runs'/task
    for arm in ('current','infer','self-apply','apply','both','self-program','apply-program','both-program','self-regions','apply-regions','both-regions'):
        p=root/'candidates'/arm/'final.json';s=read(p)
        intake=mini.selection_path(task,'self' if arm.startswith('self') else 'p4',1)
        if arm=='infer' or arm.startswith('both'):
            intake=root/'operator.json'
        g=read(intake)
        assert g['questions']==s['questions'] and g['selections']==s['selections'] and g['text']==s['reply']
        w=window(task,1,s['questions'],s['selections'],s['reply'],intake)
        yield normalized(task,arm,1,s,p,s['calls'],[root/'calls',*dirs],[w])
    for source_name,base in [('old',old.STUDY/'runs'),('fixed',fix.STUDY/'runs'),('live',OUT)]:
        for role in ('self','multi'):
            arm=f'{source_name}-{role}'
            act=base/task/(arm if source_name=='live' else role)
            original=act if source_name=='live' else old.root(task,role)
            assert (act/'final.json').exists()
            windows,keys,unsent,locations=[],[],[],[]
            for n in (1,2,3):
                src=original/f'cycle-{n}'
                folder=act/f'cycle-{n}'
                source=folder/'snapshot.json'
                snap=read(source);intake=read(src/'intake.json')
                if intake['questions']:
                    op=src/'operator.json';g=read(op)
                    ans=read(src/'answer.json')
                    assert ans['questions']==intake['questions']
                    windows.append(window(task,n,ans['questions'],g['selections'],ans['text'],op,g.get('origin')))
                for r in intake['reviews']:
                    doc=r.get('analysis') or {}
                    if doc and not doc.get('needed') and doc.get('owner_question','').strip():
                        unsent.append(dict(cycle=n,by=r['role'],question=doc['owner_question'],why='감시자가 질문 불필요로 표시',source=rel(src/'intake.json')))
                keys+=snap['calls']
                locations.extend([folder/'calls',src/'calls'])
                if n==3:
                    assert snap['files']==read(act/'final.json')['files']
                yield normalized(task,arm,n,snap,source,keys,[*locations,act/'initial/calls',*dirs],windows.copy(),n==3,unsent.copy())
    p=OUT/task/'choices/final.json'
    for arm,snap in read(p).items():
        yield normalized(task,arm,1,snap,p,snap['calls'],[p.parent/'calls',*dirs],[])

