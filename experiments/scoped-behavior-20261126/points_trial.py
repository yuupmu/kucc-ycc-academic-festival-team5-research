"""Freeze, run and independently replay the final local editor on all three small comparisons."""
import argparse
from collections import Counter
import os
from pathlib import Path

from trial import LAB, OLD, ROOT, call_model, content_hash, freeze, local_server, locked_output, public_history, read, sealed_text, writer
from experiments import confirmed_points, guarded_reply

OUT = ROOT / 'confirmed-points'
SIGNAL = ROOT / 'signal-check'


def setup():
    parent = read(ROOT / 'scalar-guards/design.json')
    files = [Path(__file__), Path(confirmed_points.__file__), Path(guarded_reply.__file__),
             *[ROOT / group / name for group in ('scalar-guards','signal-check') for name in ('design.json','sealed.json','results.json')]]
    freeze(OUT/'design.json', dict(model=parent['model'], weights=parent['model_sha256'],
           tasks=dict(parent['task_seeds'], signal=[read(SIGNAL/'design.json')['seed']]),
           files={**parent['files'], **{str(p.relative_to(LAB)):content_hash(p) for p in files}},
           grading='Same pre-registered panels. All ten final submissions frozen before grading. Signal was already seen in the third trial.',
           change='Predict the values of integer literals explicitly in the public brief or owner reply. Reconcile only exact boundary literals shared with the total guard. Accept declarative equality notation.'))


def items(design):
    for task,seeds in design['tasks'].items():
        state = read(SIGNAL/'design.json')['state'] if task=='signal' else read(OLD/'frozen'/(task+'.json'))
        for i,seed in enumerate(seeds):
            for side in ('AB' if i%2 else 'BA'):
                yield task,seed,side,f'{task}/{seed}/{side}',state


def generate(dest,design,state,seed,side,port,audit=False):
    def transport(out, config, role, prompt, packet, schema, call_seed, limit, endpoint):
        return call_model(out,config,role,prompt,packet,schema,call_seed,limit,endpoint,audit=audit)
    send = confirmed_points.with_points(transport)
    def ask(role,prompt,packet,schema,call_seed,limit):
        return send(dest,design,role,prompt,packet,schema,call_seed,limit,port)
    code, trace = writer.revise(state['brief'],state['code'],public_history(state,side),state['review'],seed,ask)
    trace['logs'] = {k:content_hash(dest/'calls'/(k+'.json')) for k in trace['calls']}
    return code,trace


def run(design):
    os.chdir(LAB)
    if content_hash(LAB/design['model']) != design['weights']:
        raise ValueError('Model changed')
    outputs = {}
    with local_server(18954,design['model']):
        for _,seed,side,label,state in items(design):
            dest=OUT/'runs'/label
            dest.mkdir(parents=True,exist_ok=True)
            code,trace=generate(dest,design,state,seed,side,18954)
            signature=sealed_text(dest/'solution.py',code)
            freeze(dest/'writer.json',trace)
            outputs[label]=dict(code=signature,trace=content_hash(dest/'writer.json'))
            print('sealed',label,flush=True)
    freeze(OUT/'sealed.json',dict(design=content_hash(OUT/'design.json'),outputs=outputs))


def grade(design):
    from evaluate import token_usage
    from score import cases,correct,evaluate,old_calls
    seal=read(OUT/'sealed.json')
    if seal['design']!=content_hash(OUT/'design.json') or set(seal['outputs'])!={row[3] for row in items(design)}:
        raise ValueError('All submissions must be sealed')
    historical=read(OLD/'sealed-all.json')['submissions']
    signal_seal=read(SIGNAL/'sealed.json')['runs']
    for task,seed,side,label,state in items(design):
        dest=OUT/'runs'/label
        code,record=generate(dest,design,state,seed,side,0,audit=True)
        if (read(dest/'writer.json')!=record or code!=(dest/'solution.py').read_text() or
            seal['outputs'][label]!=dict(code=content_hash(dest/'solution.py'),trace=content_hash(dest/'writer.json'))):
            raise ValueError('Replay failed: '+label)
        old=SIGNAL/'old'/side if task=='signal' else OLD/'runs'/label
        expected=signal_seal['old/'+side]['code'] if task=='signal' else historical[label]
        if content_hash(old/'solution.py')!=expected:
            raise ValueError('Historical submission changed')
    cache, reports = {}, {}
    for task,seed,side,label,state in items(design):
        bank=([([n],dict(A=n>=-3,B=n>-3)) for n in read(SIGNAL/'design.json')['inputs']] if task=='signal' else cases(task))
        args=[inputs for inputs,_ in bank]
        function=state.get('function','needs_check')
        report=reports.setdefault(task,dict(panels={},submissions={},usage={'old':Counter(),'new':Counter()},code_equal=[]))
        dest=OUT/'runs'/label
        old=SIGNAL/'old'/side if task=='signal' else OLD/'runs'/label
        calls = list(signal_seal['old/'+side]['calls']) if task=='signal' else old_calls(old)
        observed={}
        for method,folder,keys in [('old',old,calls),('new',dest,read(dest/'writer.json')['calls'])]:
            report['usage'][method].update(token_usage(folder,keys))
            source=(folder/'solution.py').read_text()
            cache_key=(task,source)
            if cache_key not in cache:
                values=[]
                for first in range(0,len(args),100):
                    values.extend(evaluate(source,function,args[first:first+100]))
                if len(values)!=len(args):
                    raise ValueError('Incomplete execution')
                cache[cache_key]=values
            observed[method]=[correct(v,w[side]) for v,(_,w) in zip(cache[cache_key],bank)]
        if (dest/'solution.py').read_bytes()==(old/'solution.py').read_bytes():
            report['code_equal'].append(label)
        panels={'domain':range(len(bank))}
        if task=='upload':
            panels['boundary']=[args.index([n]) for n in (15,16,17)]
        for panel,indices in panels.items():
            counts=Counter()
            for i in indices:
                before,after=(observed[v][i] for v in ('old','new'))
                counts['kept' if before and after else 'fixed' if after else 'lost' if before else 'still_wrong']+=1
            report['submissions'].setdefault(label,{})[panel]=dict(counts)
            report['panels'].setdefault(panel,Counter()).update(counts)
    freeze(OUT/'results.json',dict(seal=content_hash(OUT/'sealed.json'),tasks=reports))
    for t,r in reports.items():
        print(t,r['panels'],r['usage'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','run','grade'))
    action=p.parse_args().action
    with locked_output(OUT):
        if action=='prepare':
            setup()
        else:
            design=read(OUT/'design.json')
            for name,checksum in design['files'].items():
                if action=='run' and Path(name).name in ('results.json','score.py','evaluate.py'):
                    continue
                if content_hash(LAB/name)!=checksum:
                    raise ValueError('Frozen input changed: '+name)
            (run if action=='run' else grade)(design)
