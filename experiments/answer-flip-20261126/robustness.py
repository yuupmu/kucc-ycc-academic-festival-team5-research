"""Post-hoc finite-domain robustness check on already-sealed solutions, with no model calls."""
import itertools, json
from collections import Counter
from pathlib import Path
from prepare import OUT,LAB,expected,save
from run_pairs import content_hash,sh
from experiments.local_transport import read
from score_pairs import canon,correct,evaluate,result_kind

def items(task):
    if task=='reservation':
        return list(itertools.product((0,1,598,599,600,601,602,3600),(-1,0,1,3600,86399,86400,86401)))
    if task=='upload':return [[n] for n in range(-2,34)]
    alph=('account','billing','privacy','misc') if task=='triage' else (('x',0),('x',1),('y',0),('y',1))
    top=3 if task=='triage' else 4
    return [[list(xs)] for n in range(top+1) for xs in itertools.product(alph,repeat=n)]
def main():
    orig=read(OUT/'sealed-all.json')
    primary=read(OUT/'evaluator/results.json')
    config={t:items(t) for t in ('reservation','upload','triage','sensors')}
    basis=dict(source=content_hash(Path(__file__)),frozen_submissions=content_hash(OUT/'sealed-all.json'),primary=content_hash(OUT/'evaluator/results.json'),
               rationale='prespecified sensor winner returned its result before later distinct sensors. New exhaustive small finite domains for every task chosen after inspecting sealed code.',
               domains=json.loads(json.dumps(config)))
    save(OUT/'evaluator/robustness-design.json',basis)
    summary=[];examples=[]
    for task,inps in config.items():
        state=read(OUT/'frozen'/f'{task}.json')
        cache={}
        def execute(code):
            sig=sh(code.encode())
            if sig not in cache:
                values=[]
                for i in range(0,len(inps),100):values+=evaluate(code,state['function'],inps[i:i+100])
                cache[sig]=values
            return cache[sig]
        baseline=execute(state['code'])
        for seed in (273,419,887):
            outs={}
            for a in 'AB':
                p=OUT/'runs'/task/str(seed)/a/'solution.py'
                assert content_hash(p)==orig['submissions'][f'{task}/{seed}/{a}']
                outs[a]=execute(p.read_text())
            count=Counter();first={}
            for idx,args in enumerate(inps):
                wanted={a:expected(task,args,a) for a in 'AB'}
                got={k:v[idx] for k,v in outs.items()}
                target=wanted['A']!=wanted['B'];g='target' if target else 'control'
                both=all(correct(got[a],wanted[a]) for a in 'AB')
                same=canon([got['A']['value'],got['A']['error']])==canon([got['B']['value'],got['B']['error']])
                count[g]+=1;count[g+'_both']+=int(both);count[g+'_same']+=int(same)
                if not target and correct(baseline[idx],wanted['A']):
                    count['initial_correct']+=1;count['initial_preserved']+=int(both)
                if not both and g not in first:first[g]=dict(args=args,wanted=wanted,got=got)
                if task=='sensors' and seed==419 and [list(x) for x in args[0]] in ([['x',0],['x',1],['y',1]],[['x',0],['x',1],['x',0],['y',1]]):
                    examples.append(dict(args=args,wanted=wanted,got=got))
            summary.append(dict(task=task,seed=seed,metrics=dict(count),examples=first,success=count['target_both']==count['target'] and count['control_same']==count['control']))
    save(OUT/'evaluator/robustness.json',json.loads(json.dumps(dict(summary=summary,examples=examples))))
    print('Post-hoc finite inputs',{k:len(v) for k,v in config.items()},'strict pairs',sum(x['success'] for x in summary))
if __name__=='__main__':main()

