"""Generate from the public brief and source text. Grade only the complete, sealed batch."""
from hashlib import sha256
import json

from experiments.local_baseline import BENCHMARK, SECONDS_ADAPTER, submission_text
from experiments.monitor_cycles import (
    IDS, MAIN, MODEL, SUBMIT, compact, locked_output, public_brief, read, recorded, save,
)


SEEDS = (131, 157, 191, 223, 257, 293)
ARMS = ('direct', 'self_short', 'self_serial', 'abcd')
OPTIONS = ('draft', *IDS)
METHODS = ('안내문의 규칙 순서를 결정한 뒤 간결한 함수를 작성하세요.',
           '각 인자가 측정하는 시간을 먼저 구분하고, 허용 조건을 조합해 함수를 작성하세요.',
           '규칙이 겹치는 상황의 우선순위부터 정한 뒤 함수를 작성하세요.')
PROPOSE = ('명세에 근거해 대체 함수 전체를 제안하세요. 미확정 사항은 가정임을 주석에 표시하세요. '
           '전체 allow_cancel 함수만 하나의 Python 코드 블록으로 제출하세요.')
PICK = {'type': 'json_schema', 'json_schema': {'name': 'selection', 'strict': True, 'schema': {
    'type': 'object', 'properties': {'chosen': {'type': 'string', 'enum': list(OPTIONS)}},
    'required': ['chosen'], 'additionalProperties': False}}}


def digest(code):
    return sha256(code.encode()).hexdigest()


def generate_seed(out, seed, index, port):
    d = out/str(seed)
    d.mkdir(exist_ok=True)
    brief = public_brief()
    draft = recorded(d/'draft.json', 'main', MAIN, brief+'\n\n'+SUBMIT, seed, 1500, port)
    context = brief + '\n현재 초안\n' + submission_text(draft['text'])
    a = recorded(d/'A.json', 'A', MAIN, context+'\n'+METHODS[0]+' '+PROPOSE, seed, 800, port)
    shared = {'draft': submission_text(draft['text']), 'A': submission_text(a['text'])}

    def freeze(arm, choice, pool, calls):
        paths = [str(p.relative_to(d)) for p in calls]
        return dict(arm=arm, seed=seed, chosen=choice, code=pool[choice],
                    sha256=digest(pool[choice]), calls=paths)

    shared_calls = [d/'draft.json', d/'A.json']
    submissions = [freeze('direct', 'draft', shared, shared_calls[:1]),
                   freeze('self_short', 'A', shared, shared_calls)]
    for arm in (('abcd', 'self_serial') if index % 2 == 0 else ('self_serial', 'abcd')):
        target = d/arm
        target.mkdir(exist_ok=True)
        pool, calls = shared.copy(), shared_calls.copy()
        for role, method in zip(IDS[1:], METHODS[1:]):
            prior = ''
            if arm == 'self_serial':
                prior = '\n같은 개발자로서 앞서 작성한 후보\n'+compact({k:v for k,v in pool.items() if k != 'draft'})
            path = target/f'{role}.json'
            reply = recorded(path, role, MAIN, context+prior+'\n'+method+' '+PROPOSE, seed, 800, port)
            pool[role] = submission_text(reply['text'])
            calls.append(path)
        selector = '당신은 검토 편집자 D입니다.' if arm == 'abcd' else MAIN
        user = brief+'\n초안과 수정안 전문\n'+compact(pool)+'\n명세와 코드를 읽고 제출할 함수 하나를 선택하세요.'
        path = target/'D.json'
        pick = recorded(path, 'D', selector, user, seed, 80, port, PICK)
        choice = json.loads(pick['text'])['chosen']
        if choice not in OPTIONS:
            raise ValueError('선택을 기록할 수 없습니다.')
        submissions.append(freeze(arm, choice, pool, calls+[path]))
    return submissions


def validate_batch(rows, seeds, arms=ARMS):
    expected = {(s,a) for s in seeds for a in arms}
    if len(rows) != len(expected) or {(r['seed'],r['arm']) for r in rows} != expected:
        raise ValueError('모든 시드와 조건의 제출이 확정되어야 합니다.')
    if any(digest(r['code']) != r['sha256'] for r in rows):
        raise ValueError('확정된 코드와 해시가 일치하지 않습니다.')


def grade_sealed(out, seeds, arms=ARMS):
    sealed = read(out/'submissions.json')
    validate_batch(sealed, seeds, arms)
    # Only this offline phase has access to benchmark inputs, execution, or answers.
    from backend.isolated import grade_isolated
    from experiments.cancellation_transfer import transfer_checks
    from experiments.verified_cycles import observe
    extra = transfer_checks(())
    results = []
    for row in sealed:
        d = out/str(row['seed'])
        report = grade_isolated(row['code']+SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
        more = observe(row['code'], extra)
        calls = [read(d/p) for p in row['calls']]
        save(d/(row['arm']+'-score.json'), dict(report=report, transfer=more, sha256=row['sha256']))
        results.append(dict(seed=row['seed'], arm=row['arm'], chosen=row['chosen'], score=report['score'],
                            total=report['total'], transfer_score=sum(x['passed'] for x in more),
                            transfer_total=len(more), calls=len(calls), tokens=sum(c['usage']['total_tokens'] for c in calls)))
    save(out/'results.json', results)


def run(out, port):
    design = dict(protocol='blind-candidates-v1', model=MODEL, seeds=list(SEEDS), info='public',
                  fixed_calls=dict(direct=1,self_short=2,self_serial=5,abcd=5), retries=0,
                  selection=list(OPTIONS), grading='only after every arm and seed is sealed')
    with locked_output(out):
        path = out/'design.json'
        if (path.exists() and read(path) != design) or (not path.exists() and any(out.iterdir())):
            raise ValueError('새 폴더 또는 동일 설계의 기록을 사용하세요.')
        save(path, design)
        if not (out/'submissions.json').exists():
            if (out/'results.json').exists() or any(out.glob('*/*-score.json')):
                raise ValueError('채점이 시작된 폴더에서 새 제출을 생성할 수 없습니다.')
            batch = []
            for index, seed in enumerate(SEEDS):
                batch.extend(generate_seed(out, seed, index, port))
                print('submitted', seed, flush=True)
            validate_batch(batch, SEEDS)
            save(out/'submissions.json', batch)
        grade_sealed(out, SEEDS)
