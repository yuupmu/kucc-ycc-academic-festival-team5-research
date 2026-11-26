"""Grade sealed scoped-transfer submissions without sending results back to authors."""
import argparse
import hashlib
from pathlib import Path

from experiments.local_transport import read
from experiments.project_review import freeze
from experiments.transfer100_report import execute


def grade(out):
    arms = ('solo', 'self', 'abc', 'abc-confirmed')
    sealed = read(out/'sealed-confirmation.json')
    sources = {arm:(out/'submissions'/arm/'solution.py').read_text() for arm in arms}
    if sealed != {arm:hashlib.sha256(code.encode()).hexdigest() for arm,code in sources.items()}:
        raise ValueError('Final submissions differ from seal')
    task = read(out/'design.json')['task']
    bank = Path(__file__).resolve().parent/'transfer100-20261126'
    rows = [row for row in read(bank/'evaluator/cases.json') if row['task']==task]
    if not rows:
        raise ValueError('Empty task')
    cache, summary = {}, {}
    for arm in arms:
        record = dict(files={'solution.py':sources[arm]}, sha256=sealed[arm])
        results = execute(task,record,rows,cache)
        cases = []
        for row, raw in zip(rows, results):
            actual = raw['actual'] or {}
            value = actual.get('value')
            error = raw['error'] or actual.get('exception')
            cases.append(dict(id=row['id'],actual=value,error=error,
                              correct=not error and type(value) is type(row['expected']) and value==row['expected']))
        usage = [read(out/'calls'/(key+'.json'))['usage'] for key in read(out/(arm+'.json'))['calls']]
        summary[arm] = dict(correct=sum(c['correct'] for c in cases),count=len(cases),
                            tokens=sum(u['total_tokens'] for u in usage), calls=len(usage), cases=cases)
        print(arm,{k:v for k,v in summary[arm].items() if k!='cases'})
    freeze(out/'scores.json',summary)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    grade(parser.parse_args().out)
