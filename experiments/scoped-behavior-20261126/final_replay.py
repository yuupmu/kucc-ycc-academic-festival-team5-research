"""Replay recorded real model responses with the retained equality parser and seal before scoring."""
import argparse
from pathlib import Path

import points_trial as comparison
from experiments import reply_pipeline
from trial import LAB, ROOT, call_model, content_hash, freeze, locked_output, public_history, read, sealed_text, writer

OUT = ROOT / 'retained'
SIGNAL = ROOT / 'signal-check'
SCALAR = ROOT / 'scalar-guards'


def setup():
    prior = read(ROOT/'confirmed-points/design.json')
    files = [Path(__file__), Path(reply_pipeline.__file__), ROOT/'confirmed-points/results.json']
    freeze(OUT/'design.json', dict(prior, files={**prior['files'],**{str(p.relative_to(LAB)):content_hash(p) for p in files}},
           change='Select the full-region reader from scalar-guards. Only normalize standalone mathematical equality in restricted predicate strings. Replay identical raw calls; no new inference or per-seed selection.'))


def generate(dest, design, state, seed, side, port, audit=False):
    task = state.get('task','signal')
    if task == 'signal':
        directory = SIGNAL/'new'/side
        original = read(SIGNAL/'sealed.json')['runs']['new/'+side]['calls']
    else:
        label = f'{task}/{seed}/{side}'
        directory = SCALAR/'runs'/label
        if content_hash(directory/'writer.json') != read(SCALAR/'sealed.json')['submissions'][label]['trace']:
            raise ValueError('Source call receipt changed')
        original = read(directory/'writer.json')['logs']

    def raw(out, config, role, prompt, packet, schema, call_seed, limit, endpoint):
        key, value = call_model(dest if audit else directory, config, role, prompt, packet, schema, call_seed, limit, 0, audit=True)
        log = (dest if audit else directory)/'calls'/(key+'.json')
        if content_hash(log)!=original[key]:
            raise ValueError('Raw inference differs from the recorded third trial')
        if not audit:
            target=dest/'calls'/log.name
            target.parent.mkdir(exist_ok=True)
            freeze(target,read(log))
        return key,value

    send = reply_pipeline.with_guards(raw)
    def ask(role,prompt,packet,schema,call_seed,limit):
        return send(dest,design,role,prompt,packet,schema,call_seed,limit,0)
    code,trace=writer.revise(state['brief'],state['code'],public_history(state,side),state['review'],seed,ask)
    if set(trace['calls'])!=set(original):
        raise ValueError('The retained method must replay the identical model requests')
    trace['logs']={k:content_hash(dest/'calls'/(k+'.json')) for k in trace['calls']}
    return code,trace


def seal(design):
    outputs={}
    for _,seed,side,label,state in comparison.items(design):
        dest=OUT/'runs'/label
        dest.mkdir(parents=True,exist_ok=True)
        code,trace=generate(dest,design,state,seed,side,0)
        signature=sealed_text(dest/'solution.py',code)
        freeze(dest/'writer.json',trace)
        outputs[label]=dict(code=signature,trace=content_hash(dest/'writer.json'))
    freeze(OUT/'sealed.json',dict(design=content_hash(OUT/'design.json'),outputs=outputs))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','seal','grade'))
    action=parser.parse_args().action
    with locked_output(OUT):
        if action=='prepare':
            setup()
        else:
            design=read(OUT/'design.json')
            for name,checksum in design['files'].items():
                if content_hash(LAB/name)!=checksum:
                    raise ValueError('Registered artifact changed: '+name)
            if action=='seal':
                seal(design)
            else:
                comparison.OUT,comparison.generate=OUT,generate
                comparison.grade(design)
