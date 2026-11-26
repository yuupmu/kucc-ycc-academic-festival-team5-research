"""Research-only, post-seal scoring and executed-line tracing on the exact twenty original inputs."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys

from backend import isolated
from backend.isolated import run_cases
from experiments import festival_protocol as base
from experiments.festival_report import select_cases, token_sum, write_csv
from experiments import festival_mini as old
from experiments import region_study
from experiments.local_transport import read, save
from experiments.project_review import freeze
from experiments.rule_cycle_experiment import ARMS, arm_record
from experiments.rule_cycle_study import STUDY, CONFIG, load_public, paths, record_intake
from experiments.rule_program_study import VARIANTS, program_record


LABEL = {'solo':'① 메인 단독','self':'② 기존 자체 검토','self-apply':'② 같은 답·일반 코드','self-program':'② 같은 답·자유 조건식',
         'current':'③ 기존 P4 보류 포함','apply':'③ 기존 질문·일반 코드','infer':'③ 새 질문·기존 작성',
         'both':'③ 새 질문·일반 코드','apply-program':'③ 기존 질문·자유 조건식','both-program':'③ 새 질문·자유 조건식',
         'self-regions':'② 같은 답·입력 영역','apply-regions':'③ 기존 질문·입력 영역','both-regions':'③ 새 질문·입력 영역'}
TRACE = '''

def simulate(initial_state, events):
    import sys
    f = globals()[initial_state['call']]
    visited = []
    def tracer(frame, event, arg):
        if frame.f_code is f.__code__ and event == 'line' and len(visited) < 1000:
            visited.append(frame.f_lineno)
        return tracer
    previous = sys.gettrace()
    try:
        sys.settrace(tracer)
        value = f(*initial_state['args'])
        return {'value': value, 'lines': visited, 'exception': None}
    except Exception as exc:
        return {'value': None, 'lines': visited, 'exception': type(exc).__name__}
    finally:
        sys.settrace(previous)
'''


def trace_cases(task, files, fixtures):
    calls = []
    for _,case,_ in fixtures:
        if task=='reservation':
            now, booked, start = (datetime.fromisoformat(case[k]) for k in ('now','booked_at','starts_at'))
            args=[int((now-booked).total_seconds()),int((start-now).total_seconds())]
        else:
            args=case['initial_state']['args']
        calls.append({'initial_state':{'call':'allow_cancel' if task=='reservation' else 'triage','args':args},'events':[]})
    outputs=run_cases(next(iter(files.values()))+TRACE,calls,'allocation',hash_seed=0)
    verdicts={}
    for (key,_,expected),call,row in zip(fixtures,calls,outputs):
        value = row['actual'] or {}
        exc = row['error'] or value.get('exception')
        actual=value.get('value')
        status='unanswered' if exc or type(actual) is not type(expected) else 'correct' if actual==expected else 'wrong'
        verdicts[key]=dict(args=call['initial_state']['args'],actual=actual,expected=expected,status=status,
                           executed=value.get('lines',[]),exception=exc)
    return verdicts


def stored_control(task,arm,parent,design):
    state=read(parent/'state.json')
    n=state['arms'][arm]['version']
    snap=read(parent/arm/f'v{n}'/'snapshot.json')
    calls=[k for i in range(1,n+1) for k in read(parent/arm/f'v{i}'/'review.json')['calls']]
    receipts=[a for a in state['answers'] if a['arm']==arm]
    return dict(files=snap['files'],sha256=snap['sha256'],calls=calls,status=state['arms'][arm]['status'],
                selections=read(old.selection_path(task,arm,1))['selections'] if receipts else [],
                questions=receipts[0]['questions'] if receipts else [],reply=receipts[0]['text'] if receipts else None)


def observed_rules(task, rows, selected):
    if task=='reservation':
        requirements={'정정 600초와 601초의 구분':(('clock','duration','end','late','expired'),['C071','C072']),
                      '이용 시작 순간 거부':(('start',),['C082']), '정확한 일반 마감':(('deadline',),['C011']),
                      '이용 시작 후 정정 거부':(('after',),['C084'])}
    else:
        requirements={'복수 팀 우선순위':(('rank',),['6','7','9','11']), '미등록·등록 태그 혼합':(('unknown',),['14']),
                      '빈 목록':(('empty',) if 'empty' in selected else ('empty_list',),['5'])}
    result={}
    for label,(needs,ids) in requirements.items():
        seen=set(needs)<=selected
        result[label]=dict(authorized=seen,cases=ids,passed=all(rows[k]['status']=='correct' for k in ids),
                           actual=[rows[k]['actual'] for k in ids],missing=sorted(set(needs)-selected))
    if task=='triage':
        pair=[rows[k] for k in ('6','7')]
        result['공개된 입력 순서 불변성']={'authorized':True,'cases':['6','7'],'missing':[],
            'passed':all(x['status']!='unanswered' for x in pair) and pair[0]['actual']==pair[1]['actual'],
            'actual':[x['actual'] for x in pair]}
    return result


def report():
    config=region_study.preflight()
    prior_config=read(old.CONFIG)
    tasks=config['projects']
    if any(not (paths(t)[0]/'candidates'/a/'final.json').exists() for t in tasks for a in (*ARMS,*VARIANTS,*region_study.VARIANTS)):
        raise ValueError('모든 조건의 마지막 코드가 고정되기 전입니다.')
    research=STUDY/'research'
    research.mkdir(exist_ok=True)
    observations, costs, summary, details, items = {}, {}, [], [], []
    distinct, borrowed, pilot_only = [], [], []
    pilot_keys=read(STUDY/'format-pilot/raw-calls.json')
    order=('solo','self','self-regions','current','infer','apply-regions','both-regions',
           'self-apply','apply','both','self-program','apply-program','both-program')
    audited={}
    for task in tasks:
        out,parent,previous,design,_=load_public(task)
        base.audit(parent)
        record_intake(task,0,audit=True)
        records={a:arm_record(task,a,0,audit=True) for a in ARMS}
        records.update({a:program_record(task,a,0,audit=True) for a in VARIANTS})
        records.update({a:region_study.record(task,a,0,audit=True) for a in region_study.VARIANTS})
        for x,y in [('current','apply'),('infer','both'),*VARIANTS.items(),*region_study.VARIANTS.items()]:
            if (records[x]['reply'],records[x]['questions'])!=(records[y]['reply'],records[y]['questions']):
                raise ValueError('작성 방식 사이에 질문·대답이 다릅니다.')
        for arm in ('solo','self'):
            records[arm]=stored_control(task,arm,parent,design)
        if (records['self']['questions'],records['self']['reply'])!=(records['self-apply']['questions'],records['self-apply']['reply']):
            raise ValueError('자체 검토 비교의 답변이 다릅니다.')
        audited[task]=records
    for task in tasks:
        out,parent,previous,design,_=load_public(task)
        records=audited[task]
        fixtures=select_cases(prior_config,task)
        measured,task_bank={},{}
        observations[task]={}
        for arm in order:
            rec=records[arm]
            key=rec['sha256']
            if key!=base.core.digest(rec['files']):
                raise ValueError('고정한 코드 식별값이 다릅니다.')
            if key not in measured:
                measured[key]=trace_cases(task,rec['files'],fixtures)
            verdicts=measured[key]
            if arm in ('solo','self','current'):
                folder='p4-guarded' if arm=='current' else arm
                n=1 if arm=='solo' else 2
                expected=read(old.STUDY/'research'/task/folder/f'v{n}'/'cases.json')['verdicts']
                if any((r['actual'],r['status'])!=(expected[k]['actual'],expected[k]['status']) for k,r in verdicts.items()):
                    raise ValueError('추적 실행과 이전 기준선의 실제 반환값이 다릅니다.')
            raw=[]
            for k in rec['calls']:
                file=next((p for d in (out,parent,previous) for p in [d/'calls'/(k+'.json')] if p.exists()),None)
                if not file:
                    raise ValueError('호출 원문 누락')
                record=read(file)
                if k!=base.core.digest([record['role'],record['request']]):
                    raise ValueError('호출 식별값이 다릅니다.')
                task_bank[k]=record
                raw.append(record)
            amount=token_sum(raw)
            counts=Counter(row['status'] for row in verdicts.values())
            selected={k for group in rec['selections'] for k in group}
            probes=prior_config['policy_probes_within_sample'][task]
            unsupported=sum(verdicts[cid]['status']!='unanswered' and any(not selected.intersection(choices) for choices in requirements)
                            for cid,requirements in probes.items())
            rules=observed_rules(task,verdicts,selected)
            metrics=dict(task=task,arm=arm,correct=counts['correct'],wrong=counts['wrong'],unanswered=counts['unanswered'],
                         unsupported_returns=unsupported,probes=len(probes),questions=len(rec['questions']),calls=len(raw),
                         author_tokens=token_sum([r for r in raw if r['role'] in ('main-author','main-rule-plan','main-rule-program','main-region-decisions')])['total_tokens'],
                         **amount, status=rec['status'], owner_facts=','.join(sorted(selected)))
            observations[task][arm]={'metrics':metrics,'cases':verdicts,'rules':rules,'sha256':key,'questions':rec['questions'],
                                     'reply':rec['reply'], 'writer_error':rec.get('writer',{}).get('error')}
            details.append(metrics)
        for cid,_,expected in fixtures:
            item={'project':task,'item':cid,'expected':expected}
            for arm in order:
                case=observations[task][arm]['cases'][cid]
                item[arm]=case['actual'] if case['status']!='unanswered' else '미판정'
                item[arm+'_status']=case['status']
            items.append(item)
        for k,raw in task_bank.items():
            archived=any((d/'calls'/(k+'.json')).exists() for d in (parent,previous,old.STUDY/'refined'/task))
            (borrowed if archived else distinct).append(raw)
        for k in set(pilot_keys[task])-task_bank.keys():
            if not any((d/'calls'/(k+'.json')).exists() for d in (parent,previous,old.STUDY/'refined'/task)):
                pilot_only.append(read(out/'calls'/(k+'.json')))
        logged={p.stem for p in (out/'calls').glob('*.json')}
        if logged-task_bank.keys()-set(pilot_keys[task]):
            raise ValueError('회차에 연결되지 않은 로컬 모델 호출입니다.')
    for arm in order:
        rows=[observations[t][arm]['metrics'] for t in tasks]
        total={k:sum(r[k] for r in rows) for k in ('correct','wrong','unanswered','unsupported_returns','probes',
                                                   'questions','calls','author_tokens','prompt_tokens','completion_tokens','total_tokens')}
        summary.append(dict(condition=LABEL[arm],arm=arm,model=Path(config['model']).name,seed=config['seed'],
                            reservation=rows[0]['correct'],triage=rows[1]['correct'],**total))
    for title,group in [('new_completed_calls',distinct),('borrowed_calls',borrowed),('format_pilot_only',pilot_only)]:
        costs[title]=dict(calls=len(group),**token_sum(group))
    changes=[]
    for before,after in [('solo','both-regions'),('self','self-regions'),('self-regions','both-regions'),
                         ('current','infer'),('current','apply-regions'),('infer','both-regions'),
                         ('apply-regions','both-regions'),('current','both-regions')]:
        gained,lost=[],[]
        for t in tasks:
            left,right=(observations[t][name]['cases'] for name in (before,after))
            gained.extend(f'{t}/{k}' for k in left if left[k]['status']!='correct' and right[k]['status']=='correct')
            lost.extend(f'{t}/{k}' for k in left if left[k]['status']=='correct' and right[k]['status']!='correct')
        changes.append(dict(before=before,after=after,gained=len(gained),lost=len(lost),net=len(gained)-len(lost),
                            gained_items=', '.join(gained),lost_items=', '.join(lost)))
    write_csv(research/'summary.csv',summary)
    write_csv(research/'by-project.csv',details)
    write_csv(research/'items.csv',items)
    write_csv(research/'changes.csv',changes)
    save(research/'observations.json',dict(tasks=observations,summary=summary,costs=costs,
                                          changes=changes,python_hash_seed=0))
    freeze(research/'scoring-manifest.json',dict(seed=config['seed'],python_hash_seed=0,python=sys.version.split()[0],
           scorer=old.checksum(Path(__file__)),isolation=old.checksum(Path(isolated.__file__)),
           benchmark=old.checksum(old.STUDY/'manifest.json'),candidates={t:{a:r['sha256'] for a,r in rows.items()} for t,rows in audited.items()},
           results={p:old.checksum(research/p) for p in ('summary.csv','by-project.csv','changes.csv','items.csv','observations.json')}))
    for row in summary:
        print(row['arm'],row['reservation'],row['triage'],row['correct'],row['wrong'],row['unanswered'],row['unsupported_returns'],row['total_tokens'])
    return observations,summary
