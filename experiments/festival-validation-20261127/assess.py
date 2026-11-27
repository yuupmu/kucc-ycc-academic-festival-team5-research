"""Offline grading of sealed submissions and behavior/cost comparison against their shared drafts."""
from functools import lru_cache
from itertools import combinations
from collections import Counter
from hashlib import sha256
from run import DESIGN, OUT, PILOT, cases, digest, read, save
from owner import key
from backend.isolated import run_cases
from experiments.rule_cycle_report import TRACE


@lru_cache(None)
def evaluate(code, function, inputs):
    if code is None:
        return ['미제출']*len(inputs)
    jobs=[dict(initial_state=dict(call=function,args=list(x)),events=[]) for x in inputs]
    rows=run_cases(code+TRACE,jobs,'allocation',hash_seed=0)
    assert len(rows)==len(inputs)
    result=[]
    for row in rows:
        actual=row['actual'] or {}
        error=row['error'] or actual.get('exception')
        result.append('보류' if error=='NotImplementedError' else '실행 오류' if error or
                      type(actual.get('value'))!=bool else actual['value'])
    return result


def costs(ids):
    total=Counter()
    for call in ids:
        f=OUT/'calls'/(call+'.json')
        if not f.exists():
            f=PILOT/'shared/calls'/(call+'.json')
        u=read(f)['usage']
        assert u['prompt_tokens']+u['completion_tokens']==u['total_tokens']
        total.update(calls=1,prompt=u['prompt_tokens'],completion=u['completion_tokens'],tokens=u['total_tokens'])
    return dict(total)


def grade(supplement=False):
    seals=read(OUT/'final-seal.json')
    labels=read(OUT/'labels.json')
    rows=[]
    for task,seed,arm,original in cases():
        path=str(original.relative_to(OUT))
        folder=original
        prefix=[]
        if supplement and (OUT/'supplement'/path/'prepared.json').exists():
            folder=OUT/'supplement'/path
            prefix=read(original/'handoff.json')['calls']
            assert read(folder/'handoff.json')==read(original/'handoff.json')
        meta=DESIGN[task]
        inputs=tuple(map(tuple,meta['inputs']))
        targets=[inputs.index(tuple(x)) for x in meta['targets']]
        truth=[list(x) in meta['public_true'] for x in inputs]
        for i,v in zip(targets,meta['by_seed'][DESIGN['seeds'].index(seed)]):
            truth[i]=v
        prep=read(folder/'prepared.json')
        final=read(folder/'final.json')
        assert digest(final)==(read(OUT/'supplement-final-seal.json')[path] if supplement else seals[path])
        packet=read(folder/'handoff.json') if (folder/'handoff.json').exists() else dict(code=None,questions=[])
        draft=evaluate(packet['code'],meta['function'],inputs)
        outcome=evaluate(final['code'],meta['function'],inputs)
        if arm=='self':
            rows.append(dict(task=task,seed=seed,arm='solo',status='draft' if packet['code'] else 'draft_failed',
                behavior=draft,correct=sum(v==w for v,w in zip(draft,truth)),n=len(truth),found=[],delivered=[],answered=[],implemented=[],rounds=0,
                tokens=costs(prep['calls'][:1])['tokens'],gain=0,lost=0,shared_draft=digest(packet['code'])))
        called=prefix+prep['calls'][:]
        policies=set(meta['policies'])
        def tags(qs):
            return set(tag for q in qs for tag in labels[key(task,q)]) & policies
        found=tags(packet['questions'])
        sent=set()
        answers=set()
        turns=0
        for turn in (1,2):
            owner=folder/f'owner-{turn}.json'
            if owner.exists():
                turns+=1
                info=read(owner)
                sent|=tags(info['questions'])
                answers|=policies.intersection(info['labels'])
                called+=read(folder/f'turn-{turn}/result.json')['calls']
        implemented=[tag for i,tag in zip(targets,meta['policies']) if tag in answers and outcome[i]==truth[i]]
        preserved=[i for i,w in enumerate(truth) if draft[i]==w and outcome[i]==w]
        lost=[i for i,w in enumerate(truth) if draft[i]==w and outcome[i]!=w]
        gain=[i for i,w in enumerate(truth) if draft[i]!=w and outcome[i]==w]
        rows.append(dict(task=task,seed=seed,arm=arm,status=final['status'],behavior=outcome,expected=truth,correct=sum(v==w for v,w in zip(outcome,truth)),n=len(truth),found=sorted(found),delivered=sorted(sent),answered=sorted(answers),implemented=implemented,rounds=turns,tokens=costs(called)['tokens'],gain=len(gain),lost=len(lost),preserved=len(preserved),gain_inputs=[list(inputs[i]) for i in gain],lost_inputs=[list(inputs[i]) for i in lost],shared_draft=digest(packet['code'])))
    summary={}
    for arm in ('solo',*DESIGN['arms']):
        subset=[r for r in rows if r['arm']==arm]
        assert len(subset)==6
        summary[arm]={k:sum(r[k] for r in subset) for k in ('correct','n','tokens','rounds','gain','lost')}
        summary[arm].update({k:sum(len(r[k]) for r in subset) for k in ('found','delivered','answered','implemented')})
        summary[arm]['submitted']=sum(r['status'] in ('draft','no_question','no_open_decisions','submitted') for r in subset)
        summary[arm]['tasks']={t:sum(r['correct'] for r in subset if r['task']==t) for t in ('papers','cover')}
        summary[arm]['lost_on_submission']=sum(r['lost'] for r in subset if r['status'] in ('no_question','no_open_decisions','submitted'))
    pairs={}
    for a,b in combinations(summary,2):
        counts=Counter()
        for task in ('papers','cover'):
            for seed in DESIGN['seeds']:
                both=[r for r in rows if r['task']==task and r['seed']==seed]
                assert len({r['shared_draft'] for r in both})==1
                n={r['arm']:r['correct'] for r in both}
                counts['win' if n[b]>n[a] else 'loss' if n[b]<n[a] else 'tie']+=1
        pairs[a+' -> '+b]=dict(counts)
    save(OUT,'supplement-results.json' if supplement else 'results.json',dict(summary=summary,pairs=pairs,rows=rows))


def pilot(folder):
    ref=read(PILOT/'design.json')
    inputs=tuple(tuple(row['input']) for row in ref['conditions'])
    target=next(i for i,r in enumerate(ref['conditions']) if r['display']!=r['hide'])
    prepared=read(folder/'prepared.json')
    old=read(PILOT/'shared/handoff.json')
    baseline=evaluate(old['code'],ref['function'],inputs)
    result=dict(status=prepared['status'],setup=costs(old['calls']+prepared['calls']),draft=baseline,
                questions=prepared['questions'],sides={})
    for side in ('display','hide'):
        branch=folder/side
        if not (branch/'result.json').exists(): continue
        record=read(branch/'result.json')
        if record['status']!='submitted':
            result['sides'][side]=record
            continue
        code=(branch/'solution.py').read_text()
        assert sha256(code.encode()).hexdigest()==read(branch/'seal.json')['code']
        actual=evaluate(code,ref['function'],inputs)
        bits=[v==r[side] for v,r in zip(actual,ref['conditions'])]
        result['sides'][side]=dict(actual=actual,correct=sum(bits),target_correct=bits[target],controls_correct=sum(bits)-bits[target],unchanged_controls=sum(v==w for i,(v,w) in enumerate(zip(actual,baseline)) if i!=target),cost=costs(old['calls']+prepared['calls']+record['calls']))
    if len(result['sides'])==2 and all('actual' in v for v in result['sides'].values()):
        result['changed_inputs']=[list(x) for x,a,b in zip(inputs,result['sides']['display']['actual'],result['sides']['hide']['actual']) if a!=b]
    return result


if __name__=='__main__':
    grade()
    grade(True)
    save(OUT,'pilot-results.json',{v:pilot(folder) for v,folder in [('primary',OUT/'pilot'),('independent_scope',OUT/'supplement/pilot')]})
