"""Post-submission evaluator. Its inputs and outputs are never supplied to model calls."""
import difflib
from collections import Counter,defaultdict
from pathlib import Path

from backend.isolated import run_cases
from experiments import transfer100_study as study
from experiments.festival_report import token_sum,write_csv
from experiments.local_transport import read
from experiments.project_review import freeze
from experiments.rule_cycle_report import TRACE

RESEARCH=study.STUDY/'research'
STAGES={'correct_grounded':'근거 확보·정답','correct_unsupported':'답 확보 전 정답 반환',
        'missing_wrong':'필요 정책 미수신·오답','missing_defer':'필요 정책 미수신·보류',
        'known_wrong':'근거 확보·구현 오답','known_defer':'근거 확보·구현 보류',
        'public_wrong':'공개 요구 구현 오답','public_defer':'공개 요구 구현 보류'}

def cost(keys):
    calls=[]
    for key in keys:
        item=read(study.BANK/'calls'/f'{key}.json')
        if key!=study.base.core.digest([item['role'],item['request']]):
            raise ValueError('요청 해시 불일치')
        calls.append(item)
    return dict(calls=len(calls),**token_sum(calls),
        seconds=round(sum(c['elapsed_seconds'] for c in calls),3),
        unfinished=sum(c['finish_reason']!='stop' for c in calls))

def policies(task,receipts):
    known=set()
    cards=read(study.STUDY/'operator'/f'{task}.json')['cards']
    for rec in receipts:
        lines=set(rec['text'].splitlines())
        known.update(k for k,v in cards.items() if set(v.splitlines())<=lines)
    return known

def needs(row,known):
    # Either exceeded bound alone proves a two-dimensional item does not fit.
    if row['task']=='print' and row['args'][0]>6 and row['args'][1]>4:
        return bool({'width','height'} & known), [] if {'width','height'} & known else ['width OR height']
    return set(row['required'])<=known,sorted(set(row['required'])-known)

def ensure_sealed():
    study.verify()
    manifest=read(study.STUDY/'submissions-manifest.json')
    if manifest['protocol']!=study.checksum(study.STUDY/'manifest.json'):
        raise ValueError('고정한 실험 조건 불일치')
    for filename,digest in manifest['files'].items():
        if study.checksum(study.STUDY/filename)!=digest:
            raise ValueError('제출 후 원기록이 변경됨 '+filename)
    for task in study.TASKS:
        for arm in study.ARMS:
            folder=study.root(task)/'candidates'/arm
            rec=read(folder/'final.json')
            exported={p.relative_to(folder/'submissions/candidate').as_posix():p.read_text()
                      for p in (folder/'submissions/candidate').rglob('*') if p.is_file()}
            if rec['files']!=exported or rec['sha256']!=study.base.core.digest(exported):
                raise ValueError('최종 파일 불일치')
    for p in (study.STUDY/'runs').glob('*/dialogues/*/cycle-*/answer.json'):
        rec=read(p);doc=read(p.with_name('intake.json'))
        selection=read(p.with_name('operator.json'))
        task=p.parents[3].name
        cards=read(study.STUDY/'operator'/f'{task}.json')
        text=[]
        if len(selection['selections'])!=len(doc['questions']):
            raise ValueError('회신 수 불일치')
        for group in selection['selections']:
            text.extend([cards['cards'][k] for k in group] if group else [cards['clarification']])
        assembled='\n'.join(dict.fromkeys(line for s in text for line in s.splitlines()))
        if rec['text']!=assembled or rec['ticket']!=study.base.core.digest(doc) or rec['questions']!=doc['questions']:
            raise ValueError('대리 응답 원문 불일치')
    return manifest

def execute(task,record,rows,cache):
    key=(task,record['sha256'])
    if key not in cache:
        source=record['files']['solution.py']
        payload=[dict(initial_state=dict(call=row['function'],args=row['args']),events=[]) for row in rows]
        results=run_cases(source+TRACE,payload,'allocation',hash_seed=0)
        if len(results)!=len(rows):
            raise ValueError('실행 결과 수 불일치')
        cache[key]=results
    return cache[key]

def measure(task,arm,cycle,rec,rows,cache):
    known=policies(task,rec['receipts'])
    cases=[]
    for row,raw in zip(rows,execute(task,rec,rows,cache)):
        actual=raw['actual'] or {}
        exception=raw['error'] or actual.get('exception')
        value=actual.get('value')
        status=('unanswered' if exception or type(value) is not type(row['expected']) else
                'correct' if value==row['expected'] else 'wrong')
        failure_kind=('abstained' if exception=='NotImplementedError' else
                      'execution_error' if exception else 'invalid_return' if type(value) is not type(row['expected']) else 'returned')
        sufficient,missing=needs(row,known)
        if status=='correct':
            stage='correct_grounded' if sufficient else 'correct_unsupported'
        elif not row['required']:
            stage='public_wrong' if status=='wrong' else 'public_defer'
        elif sufficient:
            stage='known_wrong' if status=='wrong' else 'known_defer'
        else:
            stage='missing_wrong' if status=='wrong' else 'missing_defer'
        cases.append(dict(task=task,arm=arm,cycle=cycle,id=row['id'],category=row['category'],skill=row['skill'],
            args=row['args'],expected=row['expected'],actual=value,status=status,stage=stage,failure_kind=failure_kind,
            required=row['required'],received=sorted(known),missing=missing,sufficient=sufficient,
            executed=actual.get('lines',[]),exception=exception))
    counts=Counter(c['status'] for c in cases)
    stages=Counter(c['stage'] for c in cases)
    receipts=rec['receipts']
    error=(rec.get('writer') or {}).get('error')
    evidence=dict(task=task,arm=arm,cycle=cycle,correct=counts['correct'],wrong=counts['wrong'],unanswered=counts['unanswered'],
         abstained=sum(c['failure_kind']=='abstained' for c in cases),
         execution_errors=sum(c['failure_kind']=='execution_error' for c in cases),
         invalid_returns=sum(c['failure_kind']=='invalid_return' for c in cases),
         supported=sum(c['sufficient'] for c in cases),unsupported_returns=sum(not c['sufficient'] and c['status']!='unanswered' for c in cases),
         questions=sum(len(r['questions']) for r in receipts),windows=len(receipts),received_policies=len(known-{'public'}),
         format=(rec.get('writer') or {}).get('format','native' if 'native' in arm else 'whole_file'),writer_error=error,
         writer_issues=(rec.get('writer') or {}).get('issues',[]),
         edit_held=bool((rec.get('guard') or (rec.get('writer') or {}).get('guard') or {}).get('held')),
         status=rec['status'],sha256=rec['sha256'],**{k:stages[k] for k in STAGES},**cost(rec['calls']))
    return evidence,cases

def aggregate(records):
    fields=['correct','wrong','unanswered','abstained','execution_errors','invalid_returns','supported','unsupported_returns','questions','windows','received_policies',
            'calls','prompt_tokens','completion_tokens','total_tokens','seconds','unfinished',*STAGES]
    return {k:round(sum(r[k] for r in records),3) for k in fields}

def question_log():
    lines=['# 실제로 전달한 질문과 대리 담당자 회신','',
           '같은 첫 질문 묶음을 공유한 작성 조건은 같은 회신을 받았다. 아래 group은 질문을 생성한 경로이며 세부 코드 작성 조건은 설계 파일에 있다.','']
    stats=[]
    for task in study.TASKS:
        for group in sorted((study.root(task)/'dialogues').iterdir()):
            known=set();past=set()
            if group.name in study.CYCLES:
                first_group='self' if study.CYCLES[group.name][0]=='self' else 'infer'
                initial=study.root(task)/'dialogues'/first_group/'cycle-1'
                if (initial/'answer.json').exists():
                    previous=read(initial/'operator.json')
                    known.update(k for items in previous['selections'] for k in items)
                    past.update(study.base.text_key(q['question']) for q in read(initial/'intake.json')['questions'])
            for folder in sorted(group.glob('cycle-*')):
                doc=read(folder/'intake.json')
                rec=read(folder/'answer.json') if (folder/'answer.json').exists() else None
                if not doc['questions']:
                    lines.extend([f'## {task} · {group.name} · {folder.name}','','전달한 질문 없음.',''])
                    continue
                op=read(folder/'operator.json')
                lines.extend([f'## {task} · {group.name} · {folder.name}',''])
                picked=set()
                for i,(q,ids,reason) in enumerate(zip(doc['questions'],op['selections'],op['rationales']),1):
                    lines.extend([f"{i}. {'·'.join(q.get('proposed_by',[]))} — {q['question']}",'',
                                  f"   회신 선택 근거 — {reason}",''])
                    picked.update(ids)
                lines.extend(['담당자 회신','',rec['text'],''])
                stats.append(dict(task=task,group=group.name,cycle=rec['cycle'],questions=len(doc['questions']),
                    selected=','.join(sorted(picked)),new=','.join(sorted(picked-known)),
                    repeated=','.join(sorted(picked & known)),clarifications=sum(not s for s in op['selections']),
                    exact_repeated_questions=sum(study.base.text_key(q['question']) in past for q in doc['questions'])))
                known.update(picked)
                past.update(study.base.text_key(q['question']) for q in doc['questions'])
    (RESEARCH/'questions.md').write_text('\n'.join(lines))
    write_csv(RESEARCH/'question-windows.csv',stats)

def report():
    manifest=ensure_sealed()
    RESEARCH.mkdir(exist_ok=True)
    freeze(RESEARCH/'scoring-plan.json',dict(scorer=study.checksum(Path(__file__)),inputs=study.checksum(study.STUDY/'evaluator/cases.json'),
        final_submissions=study.checksum(study.STUDY/'submissions-manifest.json'),missing_policy_rule='print에서 두 축 모두 초과하면 어느 한 축의 상한만 알아도 거부 근거가 충분하다.',
        classify='정보 충족 여부는 사전 required와 실제 회신으로 정한다. 모호한 자유 문장 의미의 완전한 증명을 뜻하지 않는다. 점수는 마지막 제출, 시드 하나.',
        stages=STAGES))
    rows=read(study.STUDY/'evaluator/cases.json')
    metadata=read(study.STUDY/'evaluator/tasks.json')
    cache={};records=[];details=[];cycles=[]
    for task in study.TASKS:
        subset=[r for r in rows if r['task']==task]
        for arm in study.ARMS:
            final=read(study.root(task)/'candidates'/arm/'final.json')
            measured,items=measure(task,arm,final['cycle'],final,subset,cache)
            records.append(measured);details.extend(items)
        for arm in study.CYCLES:
            total_keys=[]
            for n in (1,2,3):
                rec=read(study.root(task)/'cycles'/arm/f'cycle-{n}'/'snapshot.json')
                total_keys+=rec['calls']
                measured,items=measure(task,arm,n,{**rec,'calls':total_keys},subset,cache)
                cycles.append(dict(metrics=measured,cases=items))
        print('graded',task,flush=True)
    summary=[dict(arm=a,name=study.NAMES[a],**aggregate([r for r in records if r['arm']==a])) for a in study.ARMS]
    types=[]
    for arm in study.ARMS:
        for task in study.TASKS:
            for category in dict.fromkeys(r['category'] for r in rows if r['task']==task):
                cases=[c for c in details if (c['arm'],c['task'],c['category'])==(arm,task,category)]
                count=Counter(c['status'] for c in cases)
                stages=Counter(c['stage'] for c in cases)
                types.append(dict(arm=arm,task=task,category=category,n=len(cases),
                    correct=count['correct'],wrong=count['wrong'],unanswered=count['unanswered'],**{k:stages[k] for k in STAGES}))
    skill_rows=[]
    for arm in study.ARMS:
        for skill in dict.fromkeys(r['skill'] for r in rows):
            cases=[c for c in details if (c['arm'],c['skill'])==(arm,skill)]
            c=Counter(r['status'] for r in cases)
            skill_rows.append(dict(arm=arm,skill=skill,n=len(cases),correct=c['correct'],wrong=c['wrong'],unanswered=c['unanswered']))
    comparisons=[('solo','self'),('self','p2'),('p1','p2'),('p2','p3'),('p3','p4'),('p4','p4guard'),
                 ('p4guard','infer-legacy'),('p4guard','p4-native'),('p4guard','p4-program'),('p4guard','p4-regions'),
                 ('infer-legacy','infer-native'),('infer-native','infer-program'),('infer-native','infer-regions'),
                 ('p4-regions','infer-regions'),('self-regions','self-regions-3'),('infer-regions','multi-regions-3'),
                 ('self-regions-3','self-fidelity-3'),('multi-regions-3','multi-fidelity-3')]
    transition=[]
    for before,after in comparisons:
        by_before={c['id']:c for c in details if c['arm']==before}
        by_after={c['id']:c for c in details if c['arm']==after}
        for case_id,b in by_before.items():
            a=by_after[case_id]
            transition.append(dict(before=before,after=after,task=a['task'],id=case_id,category=a['category'],
                old_status=b['status'],new_status=a['status'],old_actual=b['actual'],new_actual=a['actual'],
                gained=b['status']!='correct' and a['status']=='correct',lost=b['status']=='correct' and a['status']!='correct',
                old_missing=','.join(b['missing']),new_missing=','.join(a['missing'])))
    cycle_summary=[]
    for arm in study.CYCLES:
        for n in (1,2,3):
            cycle_summary.append(dict(arm=arm,cycle=n,**aggregate([c['metrics'] for c in cycles if c['metrics']['arm']==arm and c['metrics']['cycle']==n])))
    for name,data in [('summary',summary),('by-project',records),('by-type',types),('by-skill',skill_rows),
                      ('items',details),('transitions',transition),('cycles',cycle_summary)]:
        write_csv(RESEARCH/(name+'.csv'),data)
    question_log()
    bank=[read(p) for p in sorted((study.BANK/'calls').glob('*.json'))]
    calls_used={k for task in study.TASKS for arm in study.ARMS for k in read(study.root(task)/'candidates'/arm/'final.json')['calls']}
    unused=[r for p,r in zip(sorted((study.BANK/'calls').glob('*.json')),bank) if p.stem not in calls_used]
    totals=dict(unique_calls=len(bank),**token_sum(bank),seconds=round(sum(r['elapsed_seconds'] for r in bank),2),
                orphan_calls=len(unused),orphan_usage=token_sum(unused))
    freeze(RESEARCH/'observations.json',dict(summary=summary,by_project=records,cases=details,cycles=cycles,physical=totals))
    diffs=[]
    for task in study.TASKS:
        for before,after in [('solo','p4guard'),('infer-regions','multi-regions-3'),('multi-regions-3','multi-fidelity-3')]:
            a=read(study.root(task)/'candidates'/before/'final.json')['files']['solution.py']
            b=read(study.root(task)/'candidates'/after/'final.json')['files']['solution.py']
            diffs.extend(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile=task+'/'+before,tofile=task+'/'+after,lineterm=''))
    (RESEARCH/'code-changes.diff').write_text('\n'.join(diffs)+'\n')
    files=sorted(p for p in RESEARCH.iterdir() if p.is_file() and p.name!='manifest.json')
    freeze(RESEARCH/'manifest.json',dict(artifacts={p.name:study.checksum(p) for p in files}))
    for row in summary:
        print(row['arm'],row['correct'],row['wrong'],row['unanswered'],row['total_tokens'],row['questions'],flush=True)
    print('physical',totals,flush=True)

if __name__=='__main__':
    report()
