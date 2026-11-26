"""Freeze and run the upload policy-reading and code-editing arms on separate model servers."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parents[1]
PREVIOUS = LAB / 'experiments/answer-flip-20261126'
STATE_PATH = PREVIOUS / 'frozen/upload.json'
sys.path[:0] = [str(LAB), str(PREVIOUS)]

from backend.allocation_repair import pending_sites
from backend.structured_output import obj
from experiments.festival_protocol import call_model
from experiments.local_transport import compact, local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import evidence_choices
from run_pairs import content_hash, edit, sealed_text

SIZES = (15, 16, 17)
CHOICES = ['허용', '거부', '판단 보류']
PREDICT = ('당신은 이 프로젝트의 메인 개발자입니다. 공개 명세와 직접 받은 담당자 답변에 따라 '
           '완성된 함수가 15바이트, 16바이트, 17바이트에서 각각 반환해야 할 결과를 답하세요. '
           '각 입력마다 허용 또는 거부를, 이 정보로 결정할 수 없는 경우에는 판단 보류를 선택하세요. '
           '세 입력의 판단만 작성하세요.')
PREDICTION_SCHEMA = obj({str(size): {'type': 'string', 'enum': CHOICES} for size in SIZES})
ROLE_ORDER = ('edit', 'predict')


def folder(seed, side, role):
    return ROOT / 'runs' / str(seed) / side / role


def common_packet(state, side):
    history = [dict(request_id='abc-1', questions=state['questions'],
                    answer={'text': state['answers'][side]})]
    return dict(brief=state['brief'], code=state['code'], dialogue=history,
                review=state['review'], pending=pending_sites(state['code']),
                evidence=evidence_choices(history))


def setup():
    historic = read(PREVIOUS / 'design.json')
    paths = [STATE_PATH, PREVIOUS / 'run_pairs.py', LAB / 'backend/allocation_repair.py',
             LAB / 'experiments/local_transport.py', LAB / 'experiments/scoped_transfer.py',
             LAB / 'experiments/festival_protocol.py']
    for path in paths:
        if content_hash(path) != historic['signatures'][str(path.relative_to(LAB))]:
            raise ValueError(f'Archived experiment changed: {path.name}')
    paths.extend([Path(__file__).resolve(), ROOT / 'score.py', ROOT / 'evaluator/key.json'])
    design = dict(task='upload', sizes=list(SIZES), seeds=historic['seeds'], model=historic['model'],
                  model_sha256=historic['weights']['sha256'], role_order=list(ROLE_ORDER),
                  side_order=[['B', 'A'], ['A', 'B'], ['B', 'A']],
                  sampling={k: historic[k] for k in ('temperature','top_p','top_k','thinking')},
                  prediction_system=PREDICT, prediction_schema=PREDICTION_SCHEMA,
                  raw_input='identical user message for both first calls. Probes only in the predictor system and schema.',
                  grading='After globally sealing both arms, execute each submitted function on 15,16,17 and score both arms against the pre-frozen key. Check exact bool type. Count invalid, deferred and implicit None separately.',
                  counts='18 size-level comparisons; six three-value vectors; three paired A/B policy flips. These are three inputs repeated, not 18 independent problems.',
                  fingerprint={str(p.relative_to(LAB)): content_hash(p) for p in paths})
    freeze(ROOT / 'design.json', design)


def predict(dest, design, packet, seed, port):
    calls = []
    value = None
    for limit in (1100, 1800):
        key, value = call_model(dest, design, 'main-predict', PREDICT, packet,
                                PREDICTION_SCHEMA, seed, limit, port)
        calls.append(key)
        if value is not None:
            break
    freeze(dest / 'predictions.json', value)
    return 'predictions.json', calls, 'submitted' if value is not None else 'invalid-output'


def run():
    os.chdir(LAB)
    design = read(ROOT / 'design.json')
    for path, wanted in design['fingerprint'].items():
        if not path.endswith(('evaluator/key.json', '/score.py')) and content_hash(LAB / path) != wanted:
            raise ValueError(f'Inputs changed after setup: {path}')
    if content_hash(LAB / design['model']) != design['model_sha256']:
        raise ValueError('Model weights do not match the prior study')
    state = read(STATE_PATH)
    seals = {}
    for role, port in zip(ROLE_ORDER, (18946, 18947)):
        # The original writer is closed before any predictions are generated.
        with local_server(port, design['model']):
            for seed, sides in zip(design['seeds'], design['side_order']):
                for side in sides:
                    dest = folder(seed, side, role)
                    dest.mkdir(parents=True, exist_ok=True)
                    packet = common_packet(state, side)
                    if role == 'edit':
                        code, attempts = edit(dest, design['model'], state, state['answers'][side], seed, port)
                        name = 'solution.py'
                        sealed_text(dest / name, code)
                        calls = [attempt['call'] for attempt in attempts]
                        state_name = attempts[-1]['outcome']
                        freeze(dest / 'edit-log.json', attempts)
                    else:
                        name, calls, state_name = predict(dest, design, packet, seed, port)
                    records = [read(dest / 'calls' / (key+'.json')) for key in calls]
                    if records[0]['request']['messages'][1]['content'] != compact(packet):
                        raise ValueError('The two arms must receive the same user message')
                    receipt = dict(output=name, status=state_name,
                                   calls={k: content_hash(dest / 'calls' / (k+'.json')) for k in calls},
                                   usage={k: sum(r['usage'][k] for r in records) for k in
                                          ('prompt_tokens','completion_tokens','total_tokens')})
                    if role == 'edit':
                        receipt['edit_log_sha256'] = content_hash(dest / 'edit-log.json')
                    freeze(dest / 'receipt.json', receipt)
                    seals[str(dest.relative_to(ROOT))] = dict(output=content_hash(dest / name),
                                                               receipt=content_hash(dest / 'receipt.json'))
                    print('sealed', role, seed, side, flush=True)
    freeze(ROOT / 'sealed.json', dict(design=content_hash(ROOT / 'design.json'), runs=seals))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'run'))
    args = parser.parse_args()
    with locked_output(ROOT):
        if args.action == 'prepare':
            setup()
        else:
            run()

