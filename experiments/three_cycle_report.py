"""Research-only scoring of all saved versions after every third-cycle candidate has been sealed."""
import difflib
from collections import Counter
from pathlib import Path

from experiments import festival_mini, repeated_intervention as loop, three_cycle_study as study
from experiments.festival_report import select_cases, token_sum, write_csv
from experiments.local_transport import read, save
from experiments.project_review import freeze
from experiments.rule_cycle_report import observed_rules, stored_control, trace_cases
from experiments.rule_cycle_study import load_public


NAMES={'solo':'① 메인 단독','self':'② 메인 자체 검토','multi':'③ 메인 + 독립 감시자'}
TASKS={'reservation':'예약','triage':'문의 배정'}
COUNTS=('correct','wrong','unanswered','unsupported_returns','policy_probes','questions','owner_windows',
        'new_reply_sentences','repeated_reply_sentences','calls','prompt_tokens','completion_tokens','total_tokens',
        'cumulative_questions','cumulative_windows','cumulative_calls','cumulative_prompt_tokens',
        'cumulative_completion_tokens','cumulative_total_tokens')


def raw_calls(keys,locations):
    raw=[]
    for key in keys:
        source=next((p for d in locations for p in [d/(key+'.json')] if p.is_file()),None)
        if source is None:
            raise ValueError('기록된 모델 호출을 찾지 못했습니다.')
        call=read(source)
        if loop.base.core.digest([call['role'],call['request']])!=key:
            raise ValueError('모델 요청의 식별값이 다릅니다.')
        raw.append(call)
    return raw


def grade(task,role,n,snap,selected,fixtures,measured,probes):
    key=snap['sha256']
    if key!=loop.base.core.digest(snap['files']):
        raise ValueError('코드 해시가 다릅니다.')
    if key not in measured:
        measured[key]=trace_cases(task,snap['files'],fixtures)
    cases=measured[key]
    counts=Counter(v['status'] for v in cases.values())
    ungrounded=[cid for cid,requirements in probes.items()
                if cases[cid]['status']!='unanswered' and any(not selected.intersection(choices) for choices in requirements)]
    return dict(cases=cases,sha256=key,status=snap['status'],unsupported_items=ungrounded,rules=observed_rules(task,cases,selected)),dict(
        task=task,arm=role,cycle=n,correct=counts['correct'],wrong=counts['wrong'],unanswered=counts['unanswered'],
        unsupported_returns=len(ungrounded),policy_probes=len(probes))


def differences(before,after):
    gained=[k for k in before if before[k]['status']!='correct' and after[k]['status']=='correct']
    lost=[k for k in before if before[k]['status']=='correct' and after[k]['status']!='correct']
    changed=[k for k in before if (before[k]['status'],before[k]['actual'])!=(after[k]['status'],after[k]['actual'])]
    return gained,lost,changed


def report():
    cfg=study.preregister()
    steps=cfg['cycles']
    tasks=cfg['projects']
    roles=list(cfg['first_cycle'])
    # This check precedes importing any fixture values or opening any old or new scores.
    if any(not (study.root(t,r)/'final.json').is_file() for t in tasks for r in roles):
        raise ValueError('모든 조건이 세 번째 코드까지 고정된 후에만 채점합니다.')
    for task in tasks:
        for role in roles:
            study.conduct(task,role,0,audit=True)
    benchmark=read(festival_mini.CONFIG)
    old=read(study.PREVIOUS/'research/observations.json')['tasks']
    research=study.STUDY/'research'
    research.mkdir(exist_ok=True)
    observations,details,questions,items,transitions={},[],[],[],[]
    code_diffs=[]
    for task in tasks:
        earlier,parent,prior,design,_=load_public(task)
        previous_calls=[p/'calls' for p in (earlier,parent,prior)]
        fixtures=select_cases(benchmark,task)
        probes=benchmark['policy_probes_within_sample'][task]
        measured={}
        observations[task]={}
        for role in ['solo',*roles]:
            last_files=None
            last_writer_calls=None
            history,known_ids,known_lines=set(),set(),set()
            cumulative=Counter()
            totals={}
            observations[task][role]=totals
            for n in ([0] if role=='solo' else list(range(1,steps+1))):
                receipt=None
                qs,groups=[],[]
                if role=='solo':
                    snap=stored_control(task,role,parent,design)
                    raw=raw_calls(snap['calls'],previous_calls)
                else:
                    folder=loop.directory(study.root(task,role),n)
                    snap=read(folder/'snapshot.json')
                    intake=read(folder/'intake.json')
                    qs=intake['questions']
                    if qs:
                        receipt=read(folder/'answer.json')
                        groups=read(folder/'operator.json')['selections']
                    raw=raw_calls(snap['calls'],previous_calls if n==1 else [folder/'calls'])
                    if n>1 and {p.stem for p in (folder/'calls').glob('*.json')}!=set(snap['calls']):
                        raise ValueError('호출 누락 또는 회차에 속하지 않은 호출이 있습니다.')
                lines=list(dict.fromkeys(line for line in (receipt['text'] if receipt else '').splitlines() if line.strip()))
                new_lines=[line for line in lines if line not in known_lines]
                ids={i for group in groups for i in group}
                if role!='solo':
                    questions.append(dict(task=task,arm=role,cycle=n,questions=qs,groups=groups,
                                          text=receipt['text'] if receipt else None,new_sentences=new_lines,
                                          new_card_ids=sorted(ids-known_ids)))
                known_ids.update(ids)
                known_lines.update(lines)
                if receipt:
                    history.add(n)
                if role!='solo' and snap['received_cycles']!=sorted(history):
                    raise ValueError('수정본과 당시 접수된 응답 회차가 다릅니다.')
                entry,metrics=grade(task,role,n,snap,known_ids,fixtures,measured,probes)
                costs=token_sum(raw)
                cumulative.update(costs)
                cumulative.update(questions=len(qs),windows=int(bool(receipt)),calls=len(raw))
                metrics.update(questions=len(qs),owner_windows=int(bool(receipt)),new_reply_sentences=len(new_lines),
                               repeated_reply_sentences=len(lines)-len(new_lines),calls=len(raw),**costs)
                metrics.update({'cumulative_'+k:v for k,v in cumulative.items()})
                metrics['status']=snap['status']
                writer_calls=snap.get('writer',{}).get('calls')
                metrics['same_writer_requests_as_last']=None if last_writer_calls is None else writer_calls==last_writer_calls
                metrics['same_files_as_last']=None if last_files is None else snap['files']==last_files
                entry.update(metrics=metrics,known_card_ids=sorted(known_ids),
                             role_tokens={member:token_sum([c for c in raw if c['role']==member]) for member in dict.fromkeys(c['role'] for c in raw)},
                             model_seconds=round(sum(c['elapsed_seconds'] for c in raw),2))
                totals[n]=entry
                details.append(metrics)
                if n<=1:
                    ref=old[task]['solo' if role=='solo' else cfg['first_cycle'][role]]
                    if (entry['sha256']!=ref['sha256'] or entry['cases']!=ref['cases'] or
                            any(metrics[k]!=ref['metrics'][k] for k in ('total_tokens','correct','wrong','unanswered','unsupported_returns'))):
                        raise ValueError('첫 회차 또는 단독 조건이 종전 실험과 다릅니다.')
                if last_files is not None:
                    for path,text in snap['files'].items():
                        code_diffs.extend(difflib.unified_diff(last_files[path].splitlines(),text.splitlines(),
                            fromfile=f'{task}/{role}/cycle-{n-1}/{path}',tofile=f'{task}/{role}/cycle-{n}/{path}',lineterm=''))
                last_files=snap['files']
                last_writer_calls=writer_calls
        for cid,_,expect in fixtures:
            item={'task':task,'item':cid,'expected':expect}
            for role,rounds in observations[task].items():
                for n,entry in rounds.items():
                    case=entry['cases'][cid]
                    name=f'{role}_{n}'
                    item[name]=case['actual'] if case['status']!='unanswered' else '미판정'
                    item[name+'_status']=case['status']
            items.append(item)
        for role in roles:
            rounds=observations[task][role]
            for start,end in [(1,2),(2,3),(1,3)]:
                gained,lost,changed=differences(rounds[start]['cases'],rounds[end]['cases'])
                transitions.append(dict(task=task,arm=role,start=start,end=end,gained=len(gained),lost=len(lost),
                                        net=len(gained)-len(lost),gained_items=','.join(gained),lost_items=','.join(lost),
                                        changed_items=','.join(changed)))
    summary=[]
    for role in ['solo',*roles]:
        for n in ([0] if role=='solo' else list(range(1,steps+1))):
            rows=[observations[t][role][n]['metrics'] for t in tasks]
            summary.append(dict(condition=NAMES[role],arm=role,cycle=n,model=Path(cfg['model']).name,seed=cfg['seed'],
                                reservation=rows[0]['correct'],triage=rows[1]['correct'],**{k:sum(r[k] for r in rows) for k in COUNTS}))
    write_csv(research/'summary.csv',summary)
    write_csv(research/'by-project.csv',details)
    write_csv(research/'items.csv',items)
    write_csv(research/'transitions.csv',transitions)
    (research/'code-changes.diff').write_text('\n'.join(code_diffs)+'\n')
    save(research/'observations.json',dict(tasks=observations,questions=questions,summary=summary,transitions=transitions))
    question_lines=['# 담당자에게 실제로 전달된 질문과 자연어 답변',
                    '', '질문은 모델이 낸 문장을 그대로 기록했다. 아래 회신은 사용자가 위임한 진행자가 고정 정책에서 골랐다. 새 문장 수는 직전 회차까지의 회신과 글자 그대로 비교했다.','']
    for q in questions:
        question_lines.extend([f"## {TASKS[q['task']]} · {NAMES[q['arm']]} · {q['cycle']}회차",''])
        for i,row in enumerate(q['questions'],1):
            question_lines.append(f"{i}. {'·'.join(row['proposed_by'])} — "+' '.join(row['question'].splitlines()))
        if not q['questions']:
            question_lines.append('질문 없음')
        question_lines.extend(['','**담당자 회신**','',q['text'] or '접수된 질문이 없어 회신 없음',''])
    (research/'questions.md').write_text('\n'.join(question_lines))
    checksum=festival_mini.checksum
    freeze(research/'manifest.json',dict(protocol=checksum(study.STUDY/'manifest.json'),scorer=checksum(Path(__file__)),
           previous_grading=checksum(study.PREVIOUS/'research/scoring-manifest.json'),artifacts={p:checksum(research/p) for p in
           ('summary.csv','by-project.csv','items.csv','transitions.csv','code-changes.diff','observations.json','questions.md')}))
    for row in summary:
        print(row['arm'],row['cycle'],row['reservation'],row['triage'],row['correct'],row['wrong'],row['unanswered'],
              row['unsupported_returns'],row['questions'],row['new_reply_sentences'],row['cumulative_total_tokens'])
