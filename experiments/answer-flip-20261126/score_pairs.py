"""After every submission has a hash, run the original and the two answers in the isolated runner."""
from collections import Counter
from pathlib import Path
import json
import sys

OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from backend.isolated import run_cases
from experiments.local_transport import read
from experiments.project_review import freeze
from experiments.rule_cycle_report import TRACE
from run_pairs import content_hash, sh

def evaluate(source,func,args):
    batch=[dict(initial_state={'call':func,'args':a},events=[]) for a in args]
    evaluated=run_cases(source+TRACE,batch,'allocation',hash_seed=0)
    values=[]
    for r in evaluated:
        actual=r['actual'] or {}
        error=r['error'] or actual.get('exception')
        values.append({'value':actual.get('value'),'error':error,'lines':actual.get('lines',[])})
    return values
def correct(output,expected):
    value=output['value']
    return output['error'] is None and type(value) is type(expected) and value==expected
def result_kind(output,expected):
    err=output['error']
    if err=='NotImplementedError':return 'deferred'
    if err:return 'error'
    if type(output['value']) is not type(expected):return 'invalid-return'
    return 'correct' if correct(output,expected) else 'wrong'
def canon(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False)
def first(out):
    rec=read(out/'submission.json')
    call=rec['attempts'][0]['call']
    return read(out/'calls'/(call+'.json'))['request']

def main():
    seal=read(OUT/'sealed-all.json')
    design=read(OUT/'design.json')
    assert seal['design']==content_hash(OUT/'design.json')
    assert set(seal['submissions'])=={f'{t}/{s}/{a}' for t in design['tasks'] for s in design['seeds'] for a in ('A','B')}
    for f,h in design['signatures'].items():assert content_hash(LAB/f)==h,f
    for key,h in seal['submissions'].items():assert content_hash(OUT/'runs'/key/'solution.py')==h
    bank=read(OUT/'evaluator/cases.json')
    rows=[]; summary=[]
    for task in design['tasks']:
        state=read(OUT/'frozen'/f'{task}.json')
        cases=[r for r in bank if r['task']==task]
        args=list({canon(r['args']):r['args'] for r in cases}.values())
        positions={canon(arg):i for i,arg in enumerate(args)};cache={}
        def results(source):
            sig=sh(source.encode())
            if sig not in cache:cache[sig]=evaluate(source,state['function'],args)
            return cache[sig]
        baseline=results(state['code'])
        for seed in design['seeds']:
            paths={a:OUT/'runs'/task/str(seed)/a for a in ('A','B')}
            ss={a:read(p/'submission.json') for a,p in paths.items()}
            assert ss['A']['common_sha256']==ss['B']['common_sha256']
            requests=[canon(first(p)).replace(state['changed_sentence'][a],'<the decision>') for a,p in paths.items()]
            assert requests[0]==requests[1],(task,seed)
            outs={a:results((p/'solution.py').read_text()) for a,p in paths.items()}
            for panel in dict.fromkeys(r['panel'] for r in cases):
                count=Counter()
                for r in (v for v in cases if v['panel']==panel):
                    pos=positions[canon(r['args'])]
                    base=baseline[pos]
                    observed={a:outs[a][pos] for a in outs}
                    expected=r['expected']
                    kinds={a:result_kind(observed[a],expected[a]) for a in outs}
                    both=all(k=='correct' for k in kinds.values())
                    eq=canon([observed['A']['value'],observed['A']['error']])==canon([observed['B']['value'],observed['B']['error']])
                    sensitive=expected['A']!=expected['B']
                    old_good=correct(base,expected['A'])
                    g='target' if sensitive else 'control'
                    count[g]+=1;count[g+'_both']+=int(both);count[g+'_same_behavior']+=int(eq)
                    for a in outs:count[g+'_'+a+'_'+kinds[a]]+=1
                    if not sensitive and old_good:
                        count['initial_correct']+=1;count['initial_correct_preserved_both']+=int(both)
                    if not sensitive:count['control_valid_equal']+=int(eq and all(k in ('correct','wrong') for k in kinds.values()))
                    rows.append(dict(task=task,seed=seed,panel=panel,id=r['id'],args=r['args'],sensitive=sensitive,
                                     expected=expected,draft=base,observed=observed,status=kinds))
                summary.append(dict(task=task,seed=seed,panel=panel,metrics=dict(count),
                    same_code=ss['A']['source_sha256']==ss['B']['source_sha256'],
                    all_target_correct=count['target_both']==count['target'],
                    exact_locality=count['target_both']==count['target'] and count['control_same_behavior']==count['control'],
                    all_semantically_correct=count['target_both']==count['target'] and count['control_both']==count['control'],
                    tokens={a:ss[a]['usage']['total_tokens'] for a in outs},end_state={a:ss[a]['attempts'][-1]['outcome'] for a in outs}))
    freeze(OUT/'evaluator/results.json',dict(summary=summary,rows=rows))
    print('verified paired conditions',len(seal['submissions'])//2,'post-seal input comparisons',len(rows))
if __name__=='__main__':main()

