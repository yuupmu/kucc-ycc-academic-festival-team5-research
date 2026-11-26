"""Score completed, sealed checkpoints offline. Only a continuation flag crosses the phase boundary."""
import argparse
from collections import Counter

from trial import CASES, HIST, LAB, OUT, design, digest, freeze, read, sha
from experiments.transfer100_report import execute


def verify(folder, seal):
    assert sha(folder/'solution.py')==seal['code'] and sha(folder/'trace.json')==seal['trace']
    trace=read(folder/'trace.json')
    assert set(trace['calls'])==set(trace['raw'])
    tokens=Counter()
    for key in trace['calls']:
        ref=trace['raw'][key]
        path=LAB/ref['path']
        assert sha(path)==ref['sha256']
        raw=read(path)
        assert digest([raw['role'],raw['request']])==key and (raw['role'],raw['model'])==(ref['role'],ref['model'])
        u=raw['usage']
        assert ref['tokens']==u['total_tokens']==u['prompt_tokens']+u['completion_tokens']
        tokens.update({k:u[k] for k in ('prompt_tokens','completion_tokens','total_tokens')})
    return dict(calls=len(trace['calls']),**tokens)


def evaluate(code,items,cache):
    import hashlib
    record={'files':{'solution.py':code},'sha256':hashlib.sha256(code.encode()).hexdigest()}
    rows=execute('upload',record,items,cache)
    checked={}
    for item,row in zip(items,rows):
        result=row['actual'] or {}
        error=row['error'] or result.get('exception')
        value=result.get('value')
        checked[item['id']]=dict(input=item['args'][0],expected=item['expected'],actual=value,error=error,
                                  correct=not error and type(value) is bool and value is item['expected'])
    assert len(checked)==20
    return checked


def compare(old,new):
    assert old.keys()==new.keys()
    return dict(old=sum(v['correct'] for v in old.values()),new=sum(v['correct'] for v in new.values()),
                kept=[k for k in old if old[k]['correct'] and new[k]['correct']],
                gained=[k for k in old if not old[k]['correct'] and new[k]['correct']],
                lost=[k for k in old if old[k]['correct'] and not new[k]['correct']],
                still_wrong=[k for k in old if not old[k]['correct'] and not new[k]['correct']])


def run(phase):
    design()
    first=read(OUT/'round-1-seal.json')
    assert first['design']==sha(OUT/'design.json') and set(first['submissions'])=={'old','new'}
    cost={k:verify(OUT/'round-1'/k,s) for k,s in first['submissions'].items()}
    if phase=='final':
        final=read(OUT/'final-seal.json')
        assert final['round1']==sha(OUT/'round-1-seal.json') and set(final['rounds'])=={'2','3'}
        cost.update({k:verify(OUT/'follow'/k,s) for k,s in final['rounds'].items()})
    items=[r for r in read(CASES) if r['task']=='upload']
    cache={}
    old,new=(evaluate((OUT/'round-1'/k/'solution.py').read_text(),items,cache) for k in ('old','new'))
    comparison=compare(old,new)
    if phase=='pair':
        old_reproduced=(OUT/'round-1/old/solution.py').read_text()==read(HIST/'abc-1-snapshot.json')['code']
        result=dict(seal=sha(OUT/'round-1-seal.json'),comparison=comparison,usage=cost,
                    reproduced_archived_round1=old_reproduced,cases={'old':old,'new':new})
        freeze(OUT/'round-1-results.json',result)
        freeze(OUT/'continuation.json',{'round1_seal':result['seal'],'continue':bool(comparison['gained']) and not comparison['lost']})
        print('First round',comparison,'tokens',cost,'old reproduced',old_reproduced)
        return
    rounds={k:evaluate((OUT/'follow'/k/'solution.py').read_text(),items,cache) for k in ('2','3')}
    oldfile=HIST/'submissions/abc/solution.py'
    assert sha(oldfile)==read(HIST/'sealed.json')['abc']
    reference=evaluate(oldfile.read_text(),items,cache)
    kept_gains=[k for k in comparison['gained'] if rounds['3'][k]['correct']]
    final_result=dict(seal=sha(OUT/'final-seal.json'),usage=cost,cases=rounds,
                      scores=[comparison['new'],*(sum(v['correct'] for v in r.values()) for r in rounds.values())],
                      compared_with_archived_final=compare(reference,rounds['3']),
                      compared_with_new_round1=compare(new,rounds['3']),retained_round1_gains=kept_gains)
    freeze(OUT/'final-results.json',final_result)
    print('Scores',final_result['scores'],'retained first-round gains',kept_gains,'tokens',cost)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('phase',choices=('pair','final'))
    run(p.parse_args().phase)
