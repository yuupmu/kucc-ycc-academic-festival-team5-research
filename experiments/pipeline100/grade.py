"""Only run after every new submission has been sealed. Never used by the generation/owner entry point."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from backend.isolated import run_cases
from experiments.rule_cycle_report import TRACE
from experiments import festival_mini as mini, three_cycle_study as old, answer_fidelity_study as fix
from experiments.project_review import freeze
from experiments.local_transport import read
from experiments.pipeline100.design import ROOT, KINDS, TASKS, register
from experiments.pipeline100.records import collect, LABEL, rel
from experiments.pipeline100 import history

RESEARCH=ROOT/'research'
TRANSITIONS=[
 ('solo','self'),('solo','p1'),('p1','p2'),('p2','p3'),('p3','p4'),('p4','current'),
 ('current','infer'),('current','apply-regions'),('infer','both-regions'),('apply-regions','both-regions'),
 ('both','both-program'),('both-program','both-regions'),('self','self-regions'),
 ('self-regions','old-self'),('both-regions','old-multi'),('old-self','fixed-self'),('old-multi','fixed-multi'),
 ('fixed-self','live-self'),('fixed-multi','live-multi'),('solo','live-self'),('solo','live-multi'),('live-self','live-multi'),
 ('solo','short'),('short','serial'),('serial','independent')]

def verdict(task,code,items):
    calls=[dict(initial_state=dict(call='allow_cancel' if task=='reservation' else 'triage',
               args=i['inputs'] if task=='reservation' else [i['inputs']]),events=[]) for i in items]
    outputs=run_cases(code+TRACE,calls,'allocation',hash_seed=0)
    if len(outputs)!=len(items):
        raise ValueError('격리 실행 결과 수가 다릅니다.')
    rows={}
    for item,row in zip(items,outputs):
        output=row['actual'] or {}
        error=row['error'] or output.get('exception')
        y=output.get('value')
        if error:
            status='보류' if error=='NotImplementedError' else '실행 오류'
        elif type(y) is not type(item['expected']):
            status='반환 형식 오류'
        else:
            status='정답' if y==item['expected'] else '오답'
        rows[item['id']]=dict(actual=y,status=status,line=(output.get('lines') or [None])[-1],error=error)
    return rows

def evidence(item,wins):
    paths=item['owner_paths']
    if not paths:
        return '공개 명세',[],[]
    active={}
    for w in wins:
        for i,q in enumerate(w['questions'],1):
            for fact in q['facts']:
                active.setdefault(fact,[]).append(f"{w['cycle']}.{i}")
    matched=next((p for p in paths if set(p)<=active.keys()),None)
    if matched:
        return '회신 확보',matched,sorted({qid for f in matched for qid in active[f]})
    return '회신 부족',sorted({f for p in paths for f in p if f not in active}),[]

def stage(source,status):
    if status in ('반환 형식 오류','실행 오류'):
        return '코드 실행·형식 오류'
    if source=='회신 부족':
        return {'정답':'카드 미확보·정답','오답':'카드 미확보·오답 반환','보류':'카드 미확보·판단 보류'}[status]
    if status=='정답':
        return '근거 확보·정답'
    return ('공개 명세' if source=='공개 명세' else '받은 회신')+('·구현 오답' if status=='오답' else '·구현 보류')

def main():
    register()
    assert (ROOT/'submission-manifest.json').is_file(), '모든 제출을 고정한 뒤 채점합니다.'
    for name,digest in read(ROOT/'submission-manifest.json').items():
        assert mini.checksum(ROOT/name)==digest
    RESEARCH.mkdir(exist_ok=True)
    sample=read(ROOT/'sample.json')
    by_task={t:[i for i in sample if i['task']==t] for t in TASKS}
    records=[r for t in TASKS for r in collect(t)]
    before=read(old.STUDY/'research/observations.json')['tasks']
    after=read(fix.STUDY/'research/observations.json')['tasks']
    measured={}
    def run(t,code):
        digest=sha256(code.encode()).hexdigest()
        if (t,digest) not in measured:
            measured[t,digest]=verdict(t,code,by_task[t])
        return measured[t,digest]
    details=[];snaps=[];lookup={};timelines={}
    for rec in records:
        t,a,n=rec['task'],rec['arm'],rec['cycle']
        assert len(rec['files'])==1
        code=next(iter(rec['files'].values()))
        judged=run(t,code)
        reference=(before if a.startswith('old-') else after if a.startswith('fixed-') else {}).get(t,{}).get(a.split('-')[-1],{}).get(str(n))
        if reference:
            ref_cases=reference['cases']
            for i in by_task[t]:
                if i['old_id']:
                    v=ref_cases[i['old_id']];got=judged[i['id']]
                    assert (v['actual'],v['status'])==(got['actual'],{'정답':'correct','오답':'wrong','보류':'unanswered'}[got['status']])
        counts=Counter()
        for i in by_task[t]:
            j=judged[i['id']];state,facts,qs=evidence(i,rec['windows']);s=stage(state,j['status'])
            details.append(dict(arm=a,cycle=n,final=rec['final'],id=i['id'],kind=i['kind'],task=t,
                                **j,evidence=state,facts=facts,question_refs=qs,stage=s,code_source=rec['source']))
            counts[j['status']]+=1
        snaps.append({**{k:v for k,v in rec.items() if k!='files'},'counts':dict(counts)})
        timelines[a,n,t]=judged
        if rec['final']:
            lookup[a,t]=judged
    assert set((a,t) for a in LABEL for t in TASKS)==set(lookup)
    summary=[]
    for a in LABEL:
        entries=[r for r in snaps if r['arm']==a and r['final']]
        rows=[r for r in details if r['arm']==a and r['final']]
        dc=Counter(r['status'] for r in rows)
        assert sum(dc.values())==100
        scores={t:sum(lookup[a,t][i['id']]['status']=='정답' for i in by_task[t]) for t in TASKS}
        summary.append(dict(arm=a,label=LABEL[a],**scores,correct=dc['정답'],wrong=dc['오답'],defer=dc['보류'],
            errors=dc['반환 형식 오류']+dc['실행 오류'],old20=sum(lookup[a,i['task']][i['id']]['status']=='정답' for i in sample if i['old_id']),
            gained=sum(lookup[a,i['task']][i['id']]['status']=='정답' and lookup['solo',i['task']][i['id']]['status']!='정답' for i in sample),
            lost=sum(lookup[a,i['task']][i['id']]['status']!='정답' and lookup['solo',i['task']][i['id']]['status']=='정답' for i in sample),
            new80=sum(lookup[a,i['task']][i['id']]['status']=='정답' for i in sample if not i['old_id']),
            types={k:sum(r['status']=='정답' and r['kind']==k for r in rows) for k in KINDS},
            diagnosis=dict(Counter(r['stage'] for r in rows)),questions=sum(len(w['questions']) for e in entries for w in e['windows']),
            windows=sum(len(e['windows']) for e in entries),**{k:sum(e[k] for e in entries) for k in ('calls','prompt_tokens','completion_tokens','total_tokens','seconds')}))
    transitions=[]
    def compare(a,b,first,second):
        g=[i for i in sample if first[i['task']][i['id']]['status']!='정답' and second[i['task']][i['id']]['status']=='정답']
        l=[i for i in sample if first[i['task']][i['id']]['status']=='정답' and second[i['task']][i['id']]['status']!='정답']
        changed=[i['id'] for i in sample if (first[i['task']][i['id']]['actual'],first[i['task']][i['id']]['status'])!=(second[i['task']][i['id']]['actual'],second[i['task']][i['id']]['status'])]
        transitions.append(dict(before=a,after=b,gained=[i['id'] for i in g],lost=[i['id'] for i in l],changed=changed,
                                gain_types=dict(Counter(i['kind'] for i in g)),loss_types=dict(Counter(i['kind'] for i in l))))
    for a,b in TRANSITIONS:
        compare(a,b,{t:lookup[a,t] for t in TASKS},{t:lookup[b,t] for t in TASKS})
    for a in ('old-self','old-multi','fixed-self','fixed-multi','live-self','live-multi'):
        for n in (1,2):
            compare(f'{a}/{n}',f'{a}/{n+1}',{t:timelines[a,n,t] for t in TASKS},{t:timelines[a,n+1,t] for t in TASKS})
    related={'R1':{'ordinary_before','overlap_allowed'},'R2':{'overlap_allowed'},'R3':{'ordinary_late'},
             'R4':{'inputs'},'R5':set(),'R6':set(),'R7':{'ordinary_before','both_allowed'},'R8':set(),'R9':set(),
             'T1':{'one_known'},'T2':{'invariant','one_known'},'T3':{'invariant'},'T4':{'invariant'},
             'T5':{'invariant','one_known'},'T6':{'invariant'},'T7':set(),'T8':set(),'T9':{'invariant'}}
    question_rows=[]
    for rec in (r for r in snaps if r['final']):
        t,a=rec['task'],rec['arm']
        past=[]
        for w in rec['windows']:
            n=w['cycle']
            this=timelines[a,n,t];prev=lookup['solo',t] if n==1 else timelines[a,n-1,t]
            old_facts={f for earlier in past for q in earlier['questions'] for f in q['facts']}
            for i,q in enumerate(w['questions'],1):
                items=[v for v in by_task[t] if set(q['facts']).intersection(related[v['kind']].union(*map(set,v['owner_paths'])))]
                enough=[v for v in items if evidence(v,past)[0]=='회신 부족' and evidence(v,[*past,w])[0]=='회신 확보']
                gained=[v for v in items if this[v['id']]['status']=='정답' and prev[v['id']]['status']!='정답']
                lost=[v for v in items if this[v['id']]['status']!='정답' and prev[v['id']]['status']=='정답']
                question_rows.append(dict(arm=a,task=t,cycle=n,order=i,**q,source=w['source'],origin=w['origin'],
                    fresh=[f for f in q['facts'] if f not in old_facts],kinds=sorted({v['kind'] for v in items}),
                    sufficient=[v['id'] for v in enough],gained=[v['id'] for v in gained],lost=[v['id'] for v in lost],
                    gain_types=dict(Counter(v['kind'] for v in gained)),loss_types=dict(Counter(v['kind'] for v in lost))))
            past.append(w)
    archive_rows,archive_qa,scope=history.analyze(sample,run)
    new_cost=Counter()
    for p in (ROOT/'runs').glob('**/billing/*.json'):
        if read(p)['origin']=='new':
            raw=read(p.parent.parent/'calls'/p.name)
            new_cost.update({k:raw['usage'][k] for k in ('prompt_tokens','completion_tokens','total_tokens')})
            new_cost['calls']+=1
    for name,data in [('scores',summary),('items',details),('snapshots',snaps),('transitions',transitions),
                      ('questions',question_rows),('historical',archive_rows),('historical-qa',archive_qa),('historical-scope',scope),('new-cost',dict(new_cost))]:
        freeze(RESEARCH/(name+'.json'),data)
    print('조건',len(summary),'최종 판정',len(lookup)*50,'전체 회차 판정',len(details),'역사 결과 행',len(archive_rows))
    for r in summary:
        print(r['arm'],r['correct'],r['wrong'],r['defer'],r['errors'],r['total_tokens'])
if __name__=='__main__':
    main()
