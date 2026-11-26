"""Archive-only matched checks. No model calls or info sent to the writers."""
import json
from pathlib import Path
from collections import Counter
import sys
OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from experiments.local_transport import read
from experiments.project_review import freeze

def response(x):
    return (json.dumps(x['value'],sort_keys=True),x['error'])

def main():
    prev=read(LAB/'var/family-100-v1/previous-process.json')['trace']
    curr=read(LAB/'var/family-100-v1/results.json')['trace']
    inputs={r['id']:r for r in read(LAB/'experiments/transfer100-20261126/evaluator/cases.json')}
    costs=read(LAB/'var/family-100-v1/comparison.json')['summary']
    loo=[]
    for family,name in zip('ABC',('Qwen','Gemma','Phi')):
        for drop in (None,*prev['A-self']):
            row=dict(model=name,omit=drop,arms={})
            for arm in ('self','abc'):
                label=f'{family}-{arm}'
                remaining={t:v for t,v in curr[label].items() if t!=drop}
                count=sum(v['correct'] for v in remaining.values())
                denom=sum(len(v['cases']) for v in remaining.values())
                tok=sum(v['usage']['total_tokens'] if 'total_tokens' in v['usage'] else v['usage']['tokens'] for v in remaining.values())
                row['arms'][arm]=dict(score=count,n=denom,tokens=tok)
                if drop is None:
                    assert count==costs[label]['correct'] and tok==costs[label]['tokens']
            loo.append(row)
    rows=[];freq=Counter();full=Counter()
    for task in prev['A-abc']:
        slf=prev['A-self'][task]['cases']; obs=prev['A-abc'][task]['cases']; draft=prev['A-solo'][task]['cases']
        for i,o in obs.items():
            s=slf[i];b=draft[i]; case=inputs[i]
            extra=o['sufficient'] and not s['sufficient']
            if b['correct'] and o['correct']:cat='already_correct'
            elif o['correct']:cat='fixed'
            elif b['correct']:cat='regression'
            elif o['error']=='NotImplementedError':cat='unapplied_deferred'
            elif o['error']:cat='unapplied_error'
            elif type(o['value']) is not type(case['expected']):cat='unapplied_invalid_return'
            else:cat='unapplied_wrong'
            item=dict(id=i,task=task,args=case['args'],expected=case['expected'],required=case['required'],extra=extra,
                      self_only=s['sufficient'] and not o['sufficient'],draft=b,self=s,abc=o,category=cat,
                      same_agent_outcome=response(o)==response(s),same_agent_correct=o['correct']==s['correct'])
            rows.append(item)
            if extra:freq[cat]+=1
            full[cat]+=1
    rs=read(LAB/'var/reservation-family-v1/details.json')['reservation']
    d=LAB/'var/reservation-family-v1/runs'
    byte_equal=(d/'A/reservation/submissions/solo/solution.py').read_bytes()==(d/'mixed/reservation/submissions/abc/solution.py').read_bytes()
    res={}
    for arm in ('A-solo','mixed'):
        x=rs[arm]['cases']
        res[arm]=dict(score=sum(v['status']=='정답' for v in x.values()),sufficient=sum(v['sufficient_evidence'] for v in x.values()),
                      grounded=sum(v['sufficient_evidence'] and v['status']=='정답' for v in x.values()))
    ret=[] 
    for task in prev['A-abc']:
        for round_ in prev['A-abc'][task]['rounds']:
            ret.append(dict(task=task,cycle=round_['round'],answer=round_['answer'],patch=round_['patch_attempts'],changed=round_['changed']))
    assert sum(freq.values())==14 and len(rows)==100
    assert not any(x['self_only'] for x in rows)
    assert all(x['same_agent_correct'] for x in rows)
    full_results=dict(loo=loo,extra=dict(freq),all=dict(full),scoped_rows=rows,numerically_identical_outputs=sum(x['same_agent_outcome'] for x in rows),
                      reservation=dict(same_bytes=byte_equal,arms=res),editor_trace=ret)
    freeze(OUT/'retrospective.json',full_results)
    print('leave-one-out',len(loo),'extra',freq,'all',full,'reservation',res, 'same code',byte_equal)
if __name__=='__main__':main()

