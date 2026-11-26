"""macOS sandbox: model code cannot read the project/keys/answers or use networking."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def run_cases(code, cases, task_id='cancellation', *, hash_seed=None):
    if task_id not in ('cancellation', 'allocation'):
        raise ValueError('알 수 없는 과제입니다.')
    if hash_seed is not None and (type(hash_seed) is not int or not 0 <= hash_seed < 2**32):
        raise ValueError('해시 시드는 부호 없는 32비트 정수여야 합니다.')
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RuntimeError('실제 모델 코드 실행에는 macOS 격리 실행기가 필요합니다.')
    if len(code) > 100000 or len(cases) > (150 if task_id == 'allocation' else 100):
        raise ValueError('검증 크기를 초과했습니다.')
    with tempfile.TemporaryDirectory(prefix='agent-check-') as temporary:
        root = Path(temporary).resolve()
        candidate = root / 'solution.py'
        candidate.write_text(code)
        runner = root / 'runner.py'
        runner.write_bytes(Path(__file__).with_name('isolated_runner.py').read_bytes())
        python = str(Path(sys.executable).resolve())
        framework_binary = Path(sys.base_prefix) / 'Resources/Python.app/Contents/MacOS/Python'
        if framework_binary.is_file():
            python = str(framework_binary.resolve())
        # Only interpreter libraries and this disposable job are readable.
        readable = ['/System', '/usr', '/Library/Developer/CommandLineTools', '/Library/Apple',
                    str(Path(sys.base_prefix).resolve()), str(root), '/dev/null', '/dev/urandom']
        profile = '(version 1) (deny default) (allow sysctl-read)\n'
        profile += '(allow process-exec (literal %s))\n' % json.dumps(python)
        profile += '(allow file-read* (literal "/") (literal "/private") (literal "/Library") (literal "/private/var"))\n'
        profile += '(allow file-read* %s)\n' % ' '.join('(subpath %s)' % json.dumps(p) for p in readable)
        environment={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'}
        flags=['-I','-B']
        if hash_seed is not None:
            # -I ignores PYTHONHASHSEED. The fresh directory holds only our runner and solution.py.
            # This mode disables all site imports and starts with the same explicit, clean environment.
            flags=['-s','-S','-B']
            environment['PYTHONHASHSEED']=str(hash_seed)
        try:
            result = subprocess.run(['/usr/bin/sandbox-exec', '-p', profile, python, *flags, str(runner), str(candidate)],
                                    input=json.dumps({'task_id':task_id, 'cases':cases}), capture_output=True, text=True, timeout=12,
                                    cwd=root, env=environment)
        except subprocess.TimeoutExpired:
            raise RuntimeError('코드 검증 제한 시간을 초과했습니다.') from None
        if result.returncode != 0:
            raise RuntimeError('격리된 코드 실행이 실패했습니다. 문법·허용 라이브러리·실행 시간을 확인하세요.')
        try:
            rows = json.loads(result.stdout)
            if not isinstance(rows, list) or len(rows) != len(cases):
                raise ValueError()
            for row in rows:
                expected_type = dict if task_id == 'allocation' else bool
                if not isinstance(row, dict) or set(row) != {'actual', 'error'} or (row['actual'] is not None and type(row['actual']) is not expected_type):
                    raise ValueError()
            return rows
        except (ValueError, TypeError):
            raise RuntimeError('격리된 코드의 반환 형식이 올바르지 않습니다.') from None


def check_code(code, checks, task_id='cancellation', *, proposals=False):
    if not isinstance(checks, list) or len(checks) > 10:
        raise ValueError('자체 검증은 최대 10개입니다.')
    if not checks:
        return {'passed': False, 'correct': 0, 'total': 0, 'results': []}
    if task_id == 'allocation':
        return check_allocation(code, checks, proposals=proposals)
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'now', 'booked_at', 'starts_at', 'expected'} or type(check['expected']) is not bool:
            raise ValueError('자체 검증 형식이 잘못됐습니다.')
        if any(not isinstance(check[k], str) or len(check[k]) > 80 for k in ('now', 'booked_at', 'starts_at')):
            raise ValueError('자체 검증 시각 형식이 잘못됐습니다.')
    rows = run_cases(code, [{k: c[k] for k in ('now', 'booked_at', 'starts_at')} for c in checks])
    results = [{**c, **r, 'passed': r['error'] is None and r['actual'] == c['expected']} for c, r in zip(checks, rows)]
    return {'passed': all(r['passed'] for r in results), 'correct': sum(r['passed'] for r in results),
            'total': len(results), 'results': results}


def grade_isolated(code, benchmark, task_id='cancellation'):
    if task_id == 'allocation':
        spec = importlib.util.spec_from_file_location('allocation_grader', str(benchmark / 'score.py'))
        grader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grader)
        dataset, _ = grader.load_dataset()
        rows = run_cases(code, [c['input'] for c in dataset['cases']], task_id)
        return grader.grade_rows(rows)
    # The trusted parent owns the grading labels. The candidate sees inputs only.
    spec = importlib.util.spec_from_file_location('trusted_grader', str(benchmark / 'score.py'))
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    grading_data = grader.load_cases(basic=task_id == 'cancellation_basic')
    inputs = [{k: c[k] for k in ('now', 'booked_at', 'starts_at')} for c in grading_data[0]]
    rows = iter(run_cases(code, inputs))
    def submission(now, booked_at, starts_at):
        row = next(rows)
        if row['error']:
            raise RuntimeError('격리된 함수 실행 오류')
        return row['actual']
    return grader.grade_cases(submission, *grading_data)


def _allocation_pair(check, schema, proposals):
    from resource_allocation_benchmark.evaluator.validate_dataset import check_schema
    if not isinstance(check, dict) or set(check) != {'input_json', 'expected_json'}:
        raise ValueError('자체 검증에 input_json, expected_json이 필요합니다.')
    if any(not isinstance(v, str) or len(v)>100000 for v in check.values()):
        raise ValueError('자체 검증 JSON 크기·형식 오류')
    item, answer = json.loads(check['input_json']), json.loads(check['expected_json'])
    if (not isinstance(item,dict) or set(item)!={'initial_state','events'} or not isinstance(item['initial_state'],dict)
            or not isinstance(item['events'],list) or len(item['events'])>100 or not isinstance(answer,dict)):
        raise ValueError('자체 검증 입력·기대 결과 형식 오류')
    try:
        check_schema(answer,schema)
    except AssertionError as exc:
        raise ValueError('과제 출력 규격과 다른 기대 결과: '+str(exc)[:160]) from None
    if proposals:
        results=answer['event_results']
        if len(results)!=len(item['events']):
            raise ValueError('입력 사건당 결과가 한 개여야 합니다.')
        positions={}
        totals=dict(item['initial_state'].get('capacities',{}))
        tracked=set(totals)==set(answer['final_state']['capacities'])
        for i,(event,row) in enumerate(zip(item['events'],results),1):
            if not isinstance(event,dict):
                continue
            if 'event_id' in event and event['event_id']!=row['event_id']:
                raise ValueError('결과의 사건 ID 순서가 입력과 다릅니다.')
            if (event.get('op')=='reserve' and isinstance(event.get('reservation_id'),str)
                    and row['code'] in ('confirmed','queued') and not row['replayed']):
                positions.setdefault(event['reservation_id'],set()).add(i)
            if event.get('op')=='set_capacity' and not row['replayed']:
                if row['code']=='capacity_updated' and isinstance(event.get('resource'),str) and event['resource'] in totals:
                    totals[event['resource']]=event.get('capacity')
                elif row['code'] not in ('invalid_event','event_id_conflict','capacity_below_usage'):
                    tracked=False
        final=answer['final_state']
        if tracked and final['capacities']!=totals:
            raise ValueError('기대 총량이 검사 자체에서 성공했다고 쓴 용량 변경과 다릅니다.')
        available=dict(final['capacities'])
        for reservation in final['reservations']:
            if reservation['order'] not in positions.get(reservation['reservation_id'],set()):
                raise ValueError('order가 해당 예약을 정상 접수한 입력 사건의 위치와 다릅니다.')
            if reservation['status']=='confirmed':
                for resource,units in reservation['needs'].items():
                    available[resource]-=units
        if final['available']!=available or any(n<0 for n in available.values()):
            raise ValueError('검사가 제시한 총량·확정 예약 점유량·가용량이 서로 맞지 않습니다.')
    return item,answer


def check_allocation(code, checks, *, proposals=False):
    schema = json.loads((Path(__file__).resolve().parents[1] / 'resource_allocation_benchmark/agent/output_schema.json').read_text())
    inputs, expected, rejected = [], [], []
    for i,check in enumerate(checks):
        try:
            item,answer=_allocation_pair(check,schema,proposals)
        except ValueError as exc:
            if not proposals:
                raise
            rejected.append(dict(index=i,reason=str(exc)))
            continue
        inputs.append(item); expected.append(answer)
    rows = run_cases(code, inputs, 'allocation') if inputs else []
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)
    results = [{'input':item, 'expected':answer, **row,
                'passed':row['error'] is None and canonical(row['actual']) == canonical(answer)}
               for item, answer, row in zip(inputs, expected, rows)]
    report = {'passed':bool(results) and all(r['passed'] for r in results), 'correct':sum(r['passed'] for r in results),
              'total':len(results), 'results':results}
    if rejected:
        report['rejected_checks']=rejected
    return report
