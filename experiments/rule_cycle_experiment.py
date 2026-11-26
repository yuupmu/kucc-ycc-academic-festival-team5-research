"""Cross question design with implementation method, keeping each treatment's owner reply fixed."""
from pathlib import Path

from backend import scoped_implementation
from experiments import festival_mini as old, festival_protocol as base, rule_cycle, rule_cycle_calls, rule_intake, rule_writer
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls
from experiments.rule_cycle_study import CONFIG, STUDY, compose, load_public, paths, record_intake


ARMS = ('current','apply','infer','both','self-apply')


def preflight():
    design = read(CONFIG)
    prev = read(STUDY/'intake-manifest.json')
    old.preregister(read(old.CONFIG))
    if (prev['design_sha256'] != old.checksum(CONFIG) or prev['reference_sha256'] != old.checksum(old.CONFIG)
            or prev['intake_sha256'] != old.checksum(Path(rule_intake.__file__)) or
            prev['policy_sha256'] != old.checksum(old.FIXTURES/'operator-cards.json') or
            prev['operator_variants_sha256'] != old.checksum(old.STUDY/'operator-variants.json')):
        raise ValueError('고정한 입력이나 정책이 바뀌었습니다.')
    manifest = {'design_sha256':prev['design_sha256'],'implementation':{Path(m.__file__).name:old.checksum(Path(m.__file__))
                for m in (rule_cycle,rule_writer,scoped_implementation,rule_cycle_calls)},'questions_and_replies':{},
                'revision':'Before grading, replaced the line-by-line code form and mutually exclusive fact label with native code and separate established/open fields.'}
    for task in design['projects']:
        out = paths(task)[0]
        files = ['intake.json'] + (['operator.json'] if read(out/'intake.json')['questions'] else [])
        manifest['questions_and_replies'][task] = {name:old.checksum(out/name) for name in files}
    freeze(STUDY/'implementation-v2-manifest.json',manifest)
    return design


def arm_record(task, arm, port, audit=False):
    out, parent, previous, design, draft = load_public(task)
    incoming = arm in ('infer','both')
    own = arm == 'self-apply'
    strategy = 'scoped' if arm in ('apply','both','self-apply') else 'legacy'
    if incoming:
        intake = read(out/'intake.json')
        questions = intake['questions']
        receipt = read(out/'operator.json') if questions else None
        initial = [draft['author_call'],*intake['calls']]
        if receipt and receipt['text'] != compose(task,receipt['selections']):
            raise ValueError('대리 응답이 고정 정책과 다릅니다.')
    else:
        folder = (parent/'self' if own else previous/'p4')/'v1'
        review = read(folder/'review.json')
        initial, questions = review['calls'], review['questions']
        receipt = read(old.selection_path(task,'self' if own else 'p4',1)) if questions else None
        if receipt and receipt['text'] != old.compose(task,receipt['selections']):
            raise ValueError('기존에 전달된 답변이 다릅니다.')
    if receipt and receipt['questions']!=questions:
        raise ValueError('해당 조건에서 묻지 않은 정책 답변입니다.')
    ask = Calls(out,design,port,(parent/'calls',previous/'calls'),audit)
    for k in initial:
        path = out/'calls'/(k+'.json')
        if not path.exists() and not audit:
            origin = next((p for d in ask.prior for p in [d/(k+'.json')] if p.exists()),None)
            if not origin:
                raise ValueError('최초 호출 원문이 없습니다.')
            freeze(path,read(origin))
        if not path.exists():
            raise ValueError('최초 호출 원문이 누락됐습니다.')
    final = rule_cycle.revise(design['project'],draft['files'],receipt['text'] if receipt else None,
                              design['seed'],'self' if own else 'multi',strategy,ask)
    final.update(arm=arm, initial_sha256=draft['sha256'], questions=questions, reply=receipt['text'] if receipt else None,
                 owner_source='delegated_policy_card' if receipt else None, selections=receipt['selections'] if receipt else [],
                 calls=[*initial,*final['calls']])
    folder = out/'candidates'/arm
    if audit:
        if read(folder/'final.json') != final:
            raise ValueError('저장된 최종 후보·질문·토큰 출처와 재구성 결과가 다릅니다.')
        target = folder/'submissions/candidate'
        exported = {f.relative_to(target).as_posix():f.read_bytes() for f in target.rglob('*') if f.is_file()}
        if exported!={p:s.encode() for p,s in final['files'].items()}:
            raise ValueError('내보낸 후보가 다릅니다.')
    else:
        folder.mkdir(exist_ok=True,parents=True)
        publish(folder,'candidate',final['files'])
        freeze(folder/'final.json',final)
    if arm=='current':
        guard = read(previous/'guarded/receipt.json')
        prior_calls = read(previous/'p4/v1/review.json')['calls']+read(previous/'p4/v2/review.json')['calls']
        if final['sha256']!=guard['retained_sha256'] or final['calls']!=prior_calls:
            raise ValueError('직전 기준선이 동일한 호출과 코드로 재현되지 않았습니다.')
    return final


def run(port):
    with locked_output(STUDY/'runs'):
        config=preflight()
        with local_server(port,config['model']):
            for task in config['projects']:
                out = paths(task)[0]
                with locked_output(out):
                    record_intake(task,0,audit=True)
                    for arm in ARMS:
                        record = arm_record(task,arm,port)
                        print(task,arm,record['status'],record['writer']['error'],flush=True)
