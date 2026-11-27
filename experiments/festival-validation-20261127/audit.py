"""Cross-check frozen files, answers and published counts using a second execution adapter."""
from functools import lru_cache
from hashlib import sha256
from run import OUT, LAB, PILOT, DESIGN, cases, digest, read, save
from backend.isolated import run_cases

ADAPTER="""
def simulate(initial_state, events):
    try:
        value = globals()[initial_state['fn']](*initial_state['arguments'])
    except NotImplementedError:
        return {'kind':'보류'}
    except Exception:
        return {'kind':'실행 오류'}
    return {'kind':'bool','value':value} if type(value) is bool else {'kind':'실행 오류'}
"""

@lru_cache(None)
def actual(code, fn, inputs):
    if code is None:
        return ['미제출']*len(inputs)
    jobs=[dict(initial_state=dict(fn=fn,arguments=list(x)),events=[]) for x in inputs]
    rows=run_cases(code+ADAPTER,jobs,'allocation',hash_seed=0)
    return [r['actual'].get('value',r['actual']['kind']) if not r['error'] else '실행 오류' for r in rows]

def audit():
    for name,expected in read(OUT/'preregistered.json').items():
        originals = {'../decision_ledger.py':'decision_ledger_v1.py', 'run.py':'preregistration/run.py'}
        f = OUT / originals.get(name, name)
        assert sha256(f.read_bytes()).hexdigest()==expected
    original = (OUT/'preregistration/run.py').read_text()
    assert original.replace("LAB.parent / 'output/reports/", "LAB / 'docs/reports/") == (OUT/'run.py').read_text()
    for name,expected in read(OUT/'supplement-design.json')['files'].items():
        assert sha256((OUT/name).read_bytes()).hexdigest()==expected
    checks=0
    for result in ('results','supplement-results'):
        for row in read(OUT/(result+'.json'))['rows']:
            task,seed,arm=row['task'],row['seed'],row['arm']
            path=OUT/'runs'/task/str(seed)/('self' if arm=='solo' else arm)
            alt=OUT/'supplement'/path.relative_to(OUT)
            if result=='supplement-results' and (alt/'final.json').exists():path=alt
            code=read(path/('handoff.json' if arm=='solo' else 'final.json'))['code']
            m=DESIGN[task]
            inputs=tuple(map(tuple,m['inputs']))
            targets=dict(zip(map(tuple,m['targets']),m['by_seed'][DESIGN['seeds'].index(seed)]))
            expected=[targets[x] if x in targets else (4<x[0]<12 if task=='papers' else x[0]) for x in inputs]
            values=actual(code,m['function'],inputs)
            assert values==row['behavior'] and sum(v==w for v,w in zip(values,expected))==row['correct']
            checks+=1
    old=read(PILOT/'design.json')
    inputs=tuple(tuple(x['input']) for x in old['conditions'])
    for side in ('display','hide'):
        code=(OUT/'supplement/pilot'/side/'solution.py').read_text()
        assert actual(code,old['function'],inputs)==read(OUT/'pilot-results.json')['independent_scope']['sides'][side]['actual']
    stage=OUT/'runs/cover/967/three'
    intermediate=[actual(read(f)['code'],'large_cover',tuple(map(tuple,DESIGN['cover']['inputs']))) for f in
                  (stage/'handoff.json',stage/'turn-1/state.json',stage/'turn-2/state.json')]
    for f in [OUT/'control/agenda.json',OUT/'supplement/control/agenda.json']:
        agenda=read(f)['agenda']
        assert {r['when'] for r in agenda['rules'] if r['then'] in agenda['slots']}=={'focus and save_data','not focus and not save_data'}
        assert len(agenda['slots'])==2 and all('merged_from' not in v for v in agenda['slots'].values())
    save(OUT,'audit.json',dict(condition_results_checked=checks,unique_executions=actual.cache_info().misses,
          pilot_branches_checked=2,control_distinct_decisions=2,
          cover_967_abc=dict(input_order=DESIGN['cover']['inputs'],draft_then_rounds=intermediate)))
if __name__=='__main__':audit()
