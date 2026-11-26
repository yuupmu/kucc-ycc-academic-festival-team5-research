"""One new Korean policy, signed levels and opposite threshold direction, after freezing the writer."""
import argparse
import os
from pathlib import Path

from trial import (LAB, ROOT, call_model, content_hash, freeze, local_server, locked_output,
                   public_history, read, sealed_text, writer)
from experiments import guarded_reply
from run_pairs import edit as original_edit

OUT = ROOT / 'signal-check'
STATE = dict(brief='needs_check(level: int) -> bool은 계측값을 다시 확인할지 결정합니다. level은 음수도 유효한 정수입니다. '
             '기준보다 높은 값은 재검(True), 낮은 값은 통과(False)입니다. 기준 수치와 정확히 기준일 때의 처리는 담당자에게 확인하세요.',
             code='def needs_check(level: int) -> bool:\n    raise NotImplementedError\n',
             review=[], questions=['재검 기준은 얼마이고, 값이 정확히 기준일 때도 재검하나요?'],
             answers={'A':'기준값은 -3입니다. 정확히 기준이면 재검합니다.',
                      'B':'기준값은 -3입니다. 정확히 기준이면 통과시킵니다.'})


def setup():
    base = read(ROOT / 'scalar-guards/design.json')
    freeze(OUT/'design.json',dict(model=base['model'], weights=base['model_sha256'], seed=1421, state=STATE,
           pipeline=content_hash(Path(guarded_reply.__file__)), parent=content_hash(ROOT/'scalar-guards/design.json'),
           script=content_hash(Path(__file__)), evaluate_after='all four submissions sealed',
           inputs=list(range(-12,7)), order=[['old','A'],['new','B'],['new','A'],['old','B']]))


def run():
    design = read(OUT/'design.json')
    if content_hash(LAB/design['model']) != design['weights']:
        raise ValueError('Unexpected model')
    seals = {}
    os.chdir(LAB)
    with local_server(18956,design['model']):
        for method, side in design['order']:
            dest = OUT / method / side
            dest.mkdir(exist_ok=True,parents=True)
            if method == 'old':
                code, attempts = original_edit(dest,design['model'],STATE,STATE['answers'][side],design['seed'],18956)
                calls = [a['call'] for a in attempts]
            else:
                send = guarded_reply.with_guards(call_model)
                def ask(role,prompt,packet,schema,seed,limit):
                    return send(dest,design,role,prompt,packet,schema,seed,limit,18956)
                code, record = writer.revise(STATE['brief'],STATE['code'],public_history(STATE,side),[],design['seed'],ask)
                calls = record['calls']
            codehash = sealed_text(dest/'solution.py',code)
            seals[method+'/'+side] = dict(code=codehash,calls={k:content_hash(dest/'calls'/(k+'.json')) for k in calls})
    freeze(OUT/'sealed.json',dict(design=content_hash(OUT/'design.json'),runs=seals))


def grade():
    from evaluate import token_usage
    from score import correct,evaluate
    design,seal = read(OUT/'design.json'),read(OUT/'sealed.json')
    if seal['design'] != content_hash(OUT/'design.json') or set(seal['runs']) != {'old/A','old/B','new/A','new/B'}:
        raise ValueError('Require four frozen submissions')
    for label,item in seal['runs'].items():
        dest=OUT/label
        if (content_hash(dest/'solution.py') != item['code'] or
                any(content_hash(dest/'calls'/(k+'.json')) != v for k,v in item['calls'].items())):
            raise ValueError('Submission or request changed')
    results={}
    for label, item in seal['runs'].items():
        dest,side=OUT/label,label[-1]
        rows = evaluate((dest/'solution.py').read_text(),'needs_check',[[n] for n in design['inputs']])
        if len(rows)!=len(design['inputs']):
            raise ValueError('Incomplete execution')
        checks=[dict(level=n, value=r['value'],error=r['error'],correct=correct(r,n>=-3 if side=='A' else n>-3))
                for n,r in zip(design['inputs'],rows)]
        results[label]=dict(correct=sum(r['correct'] for r in checks),total=len(checks),
                            usage=token_usage(dest,list(item['calls'])),checks=checks)
    freeze(OUT/'results.json',dict(seal=content_hash(OUT/'sealed.json'),runs=results))
    print({k:v['correct'] for k,v in results.items()})


if __name__ == '__main__':
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('action',choices=('prepare','run','grade'))
    action=args.parse_args().action
    with locked_output(OUT):
        if action != 'prepare':
            design=read(OUT/'design.json')
            if (design['script']!=content_hash(Path(__file__)) or design['pipeline']!=content_hash(Path(guarded_reply.__file__))
                    or design['parent']!=content_hash(ROOT/'scalar-guards/design.json') or design['state']!=STATE):
                raise ValueError('Registered transfer study changed')
        {'prepare':setup,'run':run,'grade':grade}[action]()
