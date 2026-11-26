"""Compare all sealed condition pairs, executing only changed sources on the original rows."""
from collections import Counter
from functools import lru_cache
import importlib.util
import sys

from run import (BANKS, FAMILY, LAB, LABELS, OUT, RES, TRANSFER_TASKS, digest, family,
                 freeze, identities, read, rel, sha)
from experiments.transfer100_report import execute
from reservation_benchmark.score import load_cases


@lru_cache(None)
def usage(path, key):
    raw=read(path)
    if key != digest([raw['role'],raw['request']]) or raw['model']!=raw['request']['model']:
        raise ValueError('Model request changed: '+key)
    u=raw['usage']
    assert u['prompt_tokens']+u['completion_tokens']==u['total_tokens']
    return {n:u[n] for n in ('prompt_tokens','completion_tokens','total_tokens')}


def main():
    seal=read(OUT/'sealed.json')
    assert set(seal['submissions'])=={'/'.join(row[:3]) for row in identities()}
    assert seal['design']==sha(OUT/'design.json') and seal['requests']==sha(OUT/'requests.json') and seal['scan']==sha(OUT/'scan.json')
    assert seal['new_labels']==digest(read(OUT/'new-labels.json') if (OUT/'new-labels.json').exists() else {})
    for name,checksum in read(OUT/'design.json')['files'].items():
        if sha(LAB/name)!=checksum: raise ValueError('Frozen input changed: '+name)
    records=read(OUT/'requests.json')
    for k,r in records.items():
        assert sha(LAB/r['path'])==r['sha256'] and usage(LAB/r['path'],k)['total_tokens']==r['tokens']
    for r in seal['submissions'].values():
        assert sha(LAB/r['path'])==r['sha256']
        if 'rounds' in r: assert sha(LAB/r['rounds'])==r['rounds_sha256']

    # Only the offline grader imports the historical evaluator and reads the answer keys.
    sys.modules['study']=family
    spec=importlib.util.spec_from_file_location('archived_family_audit',FAMILY/'audit.py')
    audit=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    transfer=read(FAMILY/'results.json')
    booking=read(RES/'details.json')
    booking_scores=read(RES/'scores.json')['results']
    all_transfer=read(LAB/'experiments/transfer100-20261126/evaluator/cases.json')
    cases={task:[r for r in all_transfer if r['task']==task] for task in TRANSFER_TASKS}
    basic=[r for r in read(LAB/'experiments/pipeline100/sample.json') if r['task']=='reservation']
    cases['reservation']=[dict(r,function='allow_cancel',args=r['inputs']) for r in basic]
    full,answers,_,_=load_cases()
    cases['calendar']=[dict(r,function='can_cancel',args=[r[x] for x in ('now','booked_at','starts_at')],
                            expected=answers[r['id']]['allowed']) for r in full]
    cache,table,details={}, {}, {}
    counts=Counter()
    for suite,task,label,arm,folder in identities():
        key='/'.join((suite,task,label))
        r=seal['submissions'][key]
        oldpath=folder/'submissions'/arm/'solution.py'
        oldhash=sha(oldpath)
        prior=transfer['trace'][label][task] if suite=='transfer' else booking[task][label]
        assert prior['code_sha256']==oldhash==read(BANKS[suite]/'sealed-all.json')[folder.parent.name+'/'+task][arm]
        bank=cases[task]
        assert set(prior['cases'])=={v['id'] for v in bank} and len(bank)==len(prior['cases'])
        changed=r['sha256']!=oldhash
        if changed:
            source=(LAB/r['path']).read_text()
            outputs=execute(task,{'files':{'solution.py':source},'sha256':r['sha256']},bank,cache)
            counts['executed_project_conditions']+=1
            counts['executed_rows']+=len(bank)
        outcomes={}
        rounds=read(LAB/r['rounds']) if 'rounds' in r else None
        topics={c for row in rounds for c in row['topics']} if rounds is not None else None
        for i,v in enumerate(bank):
            old=prior['cases'][v['id']]
            if suite=='transfer':
                before=old['correct']
                actual,error=old['value'],old['error']
                previous_e=old['sufficient']
            else:
                before=old['status']=='정답'
                actual,error=old['actual'],old['error']
                previous_e=old.get('sufficient_evidence')
            after=before
            if changed:
                value=outputs[i]['actual'] or {}
                actual=value.get('value')
                error=outputs[i]['error'] or value.get('exception')
                after=not error and type(actual) is type(v['expected']) and actual==v['expected']
            sufficient=previous_e
            if topics is not None:
                if suite=='transfer': sufficient=audit.grounded(task,v,topics)
                elif task=='reservation': sufficient=not v['owner_paths'] or any(set(p)<=topics for p in v['owner_paths'])
            outcomes[v['id']]=dict(before=before,after=after,actual=actual,error=error,
                                    evidence_before=previous_e,evidence_after=sufficient)
        group='transfer' if suite=='transfer' else task
        row=table.setdefault(label,{}).setdefault(group,Counter())
        oldcalls=read(folder/(arm+'.json'))['calls']
        oldtokens=sum(usage(BANKS[suite]/'calls'/(k+'.json'),k)['total_tokens'] for k in oldcalls)
        newtokens=0
        for k in r['calls']:
            path=LAB/records[k]['path'] if 'rounds' in r and k in records else BANKS[suite]/'calls'/(k+'.json')
            newtokens+=usage(path,k)['total_tokens']
        base_questions=prior['questions'] if suite=='transfer' else booking_scores[task][label]['questions']
        new_questions=sum(len(x['questions']) for x in rounds) if rounds is not None else base_questions
        before=sum(v['before'] for v in outcomes.values()); after=sum(v['after'] for v in outcomes.values())
        original_metrics=prior if suite=='transfer' else booking_scores[task][label]
        assert (oldtokens,before)==((prior['usage']['tokens'],prior['correct']) if suite=='transfer' else
                                   (original_metrics['total_tokens'],original_metrics['score']))
        row.update(total=len(bank),before=before,after=after,old_tokens=oldtokens,new_tokens=newtokens,
                   old_calls=len(oldcalls),new_calls=len(r['calls']),questions_before=base_questions,questions_after=new_questions)
        if task!='calendar':
            row.update(grounded_before=sum(x['before'] and x['evidence_before'] for x in outcomes.values()),
                       grounded_after=sum(x['after'] and x['evidence_after'] for x in outcomes.values()))
        plus=[i for i,v in outcomes.items() if v['after'] and not v['before']]
        minus=[i for i,v in outcomes.items() if v['before'] and not v['after']]
        details[key]=dict(before=before,after=after,gained=plus,lost=minus,changed_code=changed,
                          old_tokens=oldtokens,new_tokens=newtokens,old_questions=base_questions,new_questions=new_questions,
                          cases=outcomes)
        counts.update(comparisons=len(bank),gained=len(plus),lost=len(minus))
    for label in LABELS:
        for category,denominator in [('transfer',100),('reservation',50),('calendar',100)]:
            assert table[label][category]['total']==denominator
        assert table[label]['transfer']['before']==transfer['summary'][label]['correct']
    efforts={}
    for v in records.values():
        efforts.setdefault(v['origin'],Counter()).update(calls=1,tokens=v['tokens'])
    new_files={p.stem for p in (OUT/'calls').glob('*.json')}
    assert new_files=={k for k,v in records.items() if v['origin']=='new'}
    assert counts['comparisons']==2500
    freeze(OUT/'results.json',dict(seal=sha(OUT/'sealed.json'),table=table,counts=counts,
                               active_unique_requests=efforts,details=details))
    print('Counts',counts,'active unique inference',efforts)
    for label,row in table.items():
        print(label,[(v['before'],v['after'],v['old_tokens'],v['new_tokens']) for v in row.values()])


if __name__=='__main__':
    main()
