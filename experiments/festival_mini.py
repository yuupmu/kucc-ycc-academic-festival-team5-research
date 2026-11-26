"""Small predeclared paired sample. Only this researcher-side module reads the operator cards."""
import argparse
import hashlib
from pathlib import Path

from experiments import festival_protocol as protocol
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'experiments/festival-mini-20261126'
FIXTURES = ROOT / 'experiments/project-transfer-20261126'
CONFIG = STUDY / 'design.json'


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def executed_refinement_hash(current):
    original = STUDY / 'refined-v2/executed-protocol.py.txt'
    if not original.exists() or original.read_bytes() == current.read_bytes():
        return checksum(current)
    amendment = read(STUDY / 'audit-amendment.json')
    if amendment['executed'] != checksum(original) or amendment['audit_fix'] != checksum(current):
        raise ValueError('기록된 P4의 감사 수정과 실제 파일이 다릅니다.')
    return amendment['executed']


def preregister(config):
    public = [FIXTURES / 'public' / (task + '.json') for task in config['sample']]
    benchmark = ROOT / 'reservation_benchmark/evaluator'
    files = [CONFIG, STUDY / 'operator-variants.json', FIXTURES / 'operator-cards.json', FIXTURES / 'private-cases.json',
             benchmark / 'cases.json', benchmark / 'answer_key.json', benchmark / 'policy.json',
             ROOT / 'experiments/festival_protocol.py', ROOT / 'backend/project_syntax.py', *public]
    hashes = {p.relative_to(ROOT).as_posix(): checksum(p) for p in files}
    model_hash = checksum(ROOT / config['model'])
    if model_hash != config['model_sha256']:
        raise ValueError('로컬 모델과 배포자의 SHA-256이 다릅니다.')
    freeze(STUDY / 'manifest.json', {'files_sha256': hashes, 'model_sha256': model_hash})


def lexicon(task):
    return {**read(FIXTURES / 'operator-cards.json')[task], **read(STUDY / 'operator-variants.json')[task],
            'unset': '그 경우에 대해 별도의 운영 기준은 정해져 있지 않습니다.',
            'clarify': '어느 경우에 어떤 처리를 할지 조금 더 구체적으로 물어봐 주세요.'}


def selection_path(task, arm, n):
    return STUDY / 'operator' / f'{task}-{arm}-v{n}.json'


def compose(task, selections):
    clauses = lexicon(task)
    if any(not group or any(k not in clauses for k in group) for group in selections):
        raise ValueError('지정한 운영 문장을 확인하세요.')
    return '\n'.join(dict.fromkeys(clauses[k] for group in selections for k in group))


def select(task, arm, n, groups):
    out = STUDY / ('refined-v2' if arm == 'p4' else 'runs') / task
    info = read(out / 'state.json')['arms'][arm]
    if info != {'version': n, 'status': 'awaiting_human'}:
        raise ValueError('현재 답변을 기다리는 회차를 확인하세요.')
    questions = read(out / arm / f'v{n}' / 'review.json')['questions']
    if len(questions) != len(groups):
        raise ValueError('실제 질문마다 답변을 하나씩 연결하세요.')
    path = selection_path(task, arm, n)
    path.parent.mkdir(exist_ok=True)
    freeze(path, dict(questions=questions, selections=groups, text=compose(task, groups)))


def conduct(port):
    config = read(CONFIG)
    with locked_output(STUDY / 'runs'):
        preregister(config)
        with local_server(port, config['model']):
            for task in config['sample']:
                out = STUDY / 'runs' / task
                with locked_output(out):
                    design, state = protocol.setup(out, read(FIXTURES / 'public' / (task + '.json')),
                                                   config['seed'], config['model'], config['arms'], config['versions'])
                    for arm in design['arms']:
                        info = state['arms'][arm]
                        if info['status'] == 'awaiting_human':
                            n = info['version']
                            path = selection_path(task, arm, n)
                            if path.exists():
                                receipt = read(path)
                                questions = read(out / arm / f'v{n}' / 'review.json')['questions']
                                if receipt['questions'] != questions or receipt['text'] != compose(task, receipt['selections']):
                                    raise ValueError('질문과 고정 정책의 연결이 일치하지 않습니다.')
                                protocol.answer(out, state, arm, n, receipt['text'], 'delegated_policy_card')
                        while info['status'] == 'running':
                            protocol.advance(out, design, state, arm, port)
                        print(task, arm, info, flush=True)


def pending():
    for task in read(CONFIG)['sample']:
        for folder in ('runs', 'refined-v2'):
            out = STUDY / folder / task
            if not (out / 'state.json').exists():
                continue
            for arm, info in read(out / 'state.json')['arms'].items():
                n = info['version']
                if info['status'] == 'awaiting_human' and not selection_path(task, arm, n).exists():
                    print(task, arm, n)
                    for item in read(out / arm / f'v{n}' / 'review.json')['questions']:
                        print('  ', '/'.join(item['proposed_by']), item['question'])


def refine(port):
    from experiments import festival_refinement
    config = read(CONFIG)
    with locked_output(STUDY / 'refined-v2'):
        preregister(config)
        freeze(STUDY / 'refinement-v2-manifest.json', {
            'same_sample_sha256': checksum(CONFIG), 'implementation_sha256': executed_refinement_hash(Path(festival_refinement.__file__)),
            'basis': '초안 코드와 최초 질문을 읽고 연구용 채점 전에 고정. 동일 20문항·시드·모델·초안·인간 답변 한 회차.',
            'changes': ['C가 세 감시자의 메모를 담당자 질문 최대 세 개로 정리. 간접 질문과 마침표도 원문 그대로 전달',
                        '공개 초기 파일은 보존하고, 직전 구현을 보여줄 때 모델이 새로 붙인 Python 설명 문자열을 생략',
                        '메인이 답변마다 실행 줄 또는 미결 상태를 기록. 인용과 구문 검사가 실패하면 한 번 다시 작성'],
            'previous': 'refined/에는 끝의 물음표를 필수로 검사한 기술 예비 실행이 남아 있다.'})
        with local_server(port, config['model']):
            for task in config['sample']:
                out = STUDY / 'refined-v2' / task
                with locked_output(out):
                    path = selection_path(task, 'p4', 1)
                    reply = read(path) if path.exists() else None
                    if reply and (compose(task, reply['selections']) != reply['text']
                                  or reply['questions'] != read(out / 'p4/v1/review.json')['questions']):
                        raise ValueError('P4 대리 답변의 근거가 다릅니다.')
                    state = festival_refinement.stage(STUDY / 'runs' / task, out, reply['text'] if reply else None,
                                                      'delegated_policy_card', port, previous_calls=STUDY/'refined'/task/'calls')
                    print(task, state['arms'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'refine', 'pending', 'select', 'report', 'guard-replay'))
    parser.add_argument('selection', nargs='*')
    parser.add_argument('--port', type=int, default=18768)
    args = parser.parse_args()
    if args.action == 'run':
        conduct(args.port)
    elif args.action == 'refine':
        refine(args.port)
    elif args.action == 'pending':
        pending()
    elif args.action == 'select':
        task, arm, version, *groups = args.selection
        select(task, arm, int(version), [g.split(',') for g in groups])
    elif args.action == 'report':
        from experiments.festival_report import guard_replay, report
        report()
        guard_replay()
    else:
        from experiments.festival_report import guard_replay
        print(guard_replay())
