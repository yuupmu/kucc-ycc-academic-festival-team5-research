"""Run from the repository root with PYTHONPATH=. and the requested labels as arguments."""
import json
import sys
from collections import Counter
from pathlib import Path

from backend.isolated import run_cases
from experiments.monitor_pilot import save
from resource_allocation_benchmark.score import grade_rows, load_dataset

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parents[1] / 'resource_allocation_benchmark/evaluator/reference.py'
LIMIT = 100000
BATCH = 10
MARKER = '__allocation_scenario_line_limit__'
EXAMPLE = {'initial_state': {'capacities': {'seats': 2, 'laptops': 0, 'projectors': 0}},
           'events': [{'op': 'reserve', 'event_id': 'E1', 'reservation_id': 'R1',
                       'user_id': 'U1', 'needs': {'seats': 1}, 'priority': 1}]}

# The saved model submission stays verbatim. This outer wrapper runs in the normal isolated child.
WRAPPER = '''
import sys as _trace_sys
_fullinfo_original = simulate

class _FullinfoLineLimit(BaseException):
    pass

def simulate(initial_state, events):
    source_file = _fullinfo_original.__code__.co_filename
    count = 0
    def trace(frame, event, arg):
        nonlocal count
        if frame.f_code.co_filename != source_file:
            return None
        if event == 'line':
            count += 1
            if count > LINE_CAP:
                raise _FullinfoLineLimit()
        return trace
    _trace_sys.settrace(trace)
    try:
        return _fullinfo_original(initial_state, events)
    except _FullinfoLineLimit:
        return {'LIMIT_MARKER': True}
    finally:
        _trace_sys.settrace(None)
'''.replace('LINE_CAP', str(LIMIT)).replace('LIMIT_MARKER', MARKER)


def bounded_rows(source, inputs):
    results = []
    for i in range(0, len(inputs), BATCH):
        rows = run_cases(source + '\n' + WRAPPER, inputs[i:i + BATCH], 'allocation')
        for row in rows:
            if row['actual'] == {MARKER: True}:
                row = {'actual': None, 'error': '시나리오 실행 한도 초과'}
            results.append(row)
    return results


def main(labels):
    dataset, _ = load_dataset()
    inputs = [case['input'] for case in dataset['cases']]
    for label in labels:
        if label == 'reference':
            source = REFERENCE.read_text()
            path = HERE / 'grading-control.json'
            record = {}
        else:
            path = HERE / f'allocation-{int(label)}.json'
            record = json.loads(path.read_text())
            source = record['submission']
        rows = bounded_rows(source, inputs)
        report = grade_rows(rows)
        if label == 'reference':
            assert report['score'] == report['total'] == 150
        details = dict(batch_size=BATCH, source_line_limit_per_scenario=LIMIT,
                       error_counts=dict(Counter(r['error'] for r in report['results'] if r['error'])))
        record.update(status='scored', report=report, grading=details,
                      example={'input': EXAMPLE, 'output': bounded_rows(source, [EXAMPLE])[0]})
        save(path, record)
        print(label, report['score'], report['total'], details['error_counts'], report['components'], flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
