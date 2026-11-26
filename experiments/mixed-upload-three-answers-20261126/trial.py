"""Blinded replay of the mixed-review upload handoff, with one possible owner exchange."""
import argparse
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from backend.allocation_repair import pending_sites
from backend.project_review import digest
from experiments import partial_reply as editor
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze

PRIOR = OUT.parent/'mixed-upload-issue-20261126'
HIST = LAB/'var/family-100-v1/runs/mixed/upload'
PORT = 18981
NAMES = ('include', 'exclude', 'unmentioned')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    archive = read(PRIOR/'input.json')
    old = read(PRIOR/'design.json')
    assert sha(PRIOR/'input.json') == old['files'][str((PRIOR/'input.json').relative_to(LAB))]
    assert archive['code'] == (HIST/'submissions/solo/solution.py').read_text()
    assert archive['dialogue'][0]['questions'] == read(HIST/'abc-1-questions.json')
    assert len(archive['review']) == 2 and archive['pending'] == pending_sites(archive['code'])
    first = archive['dialogue'][0]['answer']['text']
    assert first == read(HIST/'abc-1-reply.json') and first.count('정확히 상한이면 허용합니다.') == 1
    replies = [first, first.replace('정확히 상한이면 허용합니다.', '정확히 상한이면 거부합니다.'),
               first.replace('정확히 상한이면 허용합니다. ', '')]
    for name, answer in zip(NAMES, replies):
        packet = deepcopy(archive)
        packet['dialogue'][0]['answer']['text'] = answer
        packet['evidence']['abc-1/H1']['quote'] = answer
        (OUT/name).mkdir(exist_ok=True)
        freeze(OUT/name/'input.json', packet)
    paths = [PRIOR/'input.json', Path(__file__), Path(editor.__file__), OUT/'assess.py',
             LAB/'experiments/guarded_reply.py', LAB/'backend/allocation_repair.py',
             LAB/'experiments/festival_protocol.py', LAB/'experiments/local_transport.py',
             *[OUT/name/'input.json' for name in NAMES]]
    freeze(OUT/'design.json', dict(model=old['model'], weights=old['weights']['A']['sha256'], seed=old['seed'],
        shared='Unchanged original brief, source, three mixed-review questions and both code issues. Scope uses no reply.',
        editor='Automatic scope, public/owner numbers and code cutpoints, model action and independent stateless entailment check per reachable pending region. One candidate; no semantic retries.',
        follow='Freeze all initial programs before asking. Per outstanding condition allow one real question. A proxy owner may answer only policies actually requested. When the initial answer omitted equality, the precommitted equality policy is exclusion. Freeze all resulting programs before any execution.',
        endpoint='Exactly one transfer upload task; three first receipts; official 20 inputs with each condition’s own boundary policy, including actual NotImplementedError when unspecified. Existing inclusive key reported separately.',
        controls='Predeclared integer grid -2 through 33 plus both million-sized tails. Also check all integer comparison cutpoints from submitted code and one representative of each intervening interval against a separate reference.',
        success='Both stated arms implement immediately and ask zero extra questions. Omission implements the rest, defers exactly equality, asks exactly one question about equality alone, then follows the received reply and changes only equality. Count other exceptions and None as errors.',
        files={str(p.relative_to(LAB)): sha(p) for p in paths}))


def design():
    d = read(OUT/'design.json')
    for path, checksum in d['files'].items():
        if sha(LAB/path) != checksum:
            raise ValueError('Frozen input changed: '+path)
    return d


def make_author(d, replay=False):
    def ask(role, prompt, packet, schema, limit):
        return call_model(OUT, d, role, prompt, packet, schema, d['seed'], limit, PORT, audit=replay)
    return ask


def publish(folder, code, info):
    folder.mkdir(exist_ok=True)
    path = folder/'solution.py'
    if path.exists() and path.read_bytes() != code.encode():
        raise ValueError('Submitted program changed')
    if not path.exists():
        path.write_bytes(code.encode())
    freeze(folder/'trace.json', info)
    return {'code': sha(path), 'trace': sha(folder/'trace.json')}


def initial(ask):
    archive = read(PRIOR/'input.json')
    questions = archive['dialogue'][0]['questions']
    scope = editor.scope(archive['brief'], archive['code'], questions, archive['review'], ask)
    freeze(OUT/'scope.json', scope)
    snapshots = {}
    for name in NAMES:
        packet = read(OUT/name/'input.json')
        answers = [packet['dialogue'][0]['answer']['text']]
        code, info = editor.revise(packet['brief'], packet['code'], answers, [questions],
                                   scope['sites'] if scope['accepted'] else [], ask)
        info['calls'] = scope['calls'] + info['calls']
        snapshots[name] = publish(OUT/name/'initial', code, info)
    freeze(OUT/'initial-seal.json', dict(design=sha(OUT/'design.json'), scope=sha(OUT/'scope.json'), snapshots=snapshots))
    requests = {}
    for name in NAMES:
        folder = OUT/name
        packet, info = read(folder/'input.json'), read(folder/'initial/trace.json')
        question, calls = editor.clarification(packet['brief'], [packet['dialogue'][0]['answer']['text']],
                                               info['unresolved'], ask)
        freeze(folder/'question.json', dict(question=question, calls=calls))
        requests[name] = sha(folder/'question.json')
    freeze(OUT/'question-seal.json', dict(initial=sha(OUT/'initial-seal.json'), requests=requests))


def follow(ask):
    seal, requests = read(OUT/'initial-seal.json'), read(OUT/'question-seal.json')
    owner = read(OUT/'owner-delivery.json')
    assert seal['design'] == sha(OUT/'design.json') and seal['scope'] == sha(OUT/'scope.json')
    assert requests['initial'] == sha(OUT/'initial-seal.json') and owner['requests'] == sha(OUT/'question-seal.json')
    snapshots = {}
    for name in NAMES:
        folder = OUT/name
        assert requests['requests'][name] == sha(folder/'question.json')
        assert seal['snapshots'][name] == dict(code=sha(folder/'initial/solution.py'), trace=sha(folder/'initial/trace.json'))
        code, info = (folder/'initial/solution.py').read_text(), read(folder/'initial/trace.json')
        question = read(folder/'question.json')['question']
        reply = owner['replies'].get(name)
        if not question:
            assert reply is None
            snapshots[name] = dict(stage='initial', **seal['snapshots'][name])
            continue
        if not reply or not reply.strip():
            raise ValueError('The owner must respond to the actual question')
        packet = read(folder/'input.json')
        turn = packet['dialogue'][0]
        answers, qs = [turn['answer']['text']], [turn['questions'], [question]]
        remaining = editor.remaining_locations(code, packet['brief'], answers, info['unresolved'])
        updated, trace = editor.revise(packet['brief'], code, [*answers, reply], qs, remaining, ask)
        snapshots[name] = dict(stage='after-reply', **publish(folder/'after-reply', updated, trace))
    paths = sorted((OUT/'calls').glob('*.json'))
    freeze(OUT/'final-seal.json', dict(questions=sha(OUT/'question-seal.json'), owner=sha(OUT/'owner-delivery.json'),
                                     snapshots=snapshots, calls={p.stem: sha(p) for p in paths}))


if __name__ == '__main__':
    from contextlib import nullcontext
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['prepare', 'initial', 'follow'])
    p.add_argument('--replay', action='store_true')
    args = p.parse_args()
    with locked_output(OUT):
        if args.phase == 'prepare':
            prepare()
        else:
            d = design()
            if not args.replay and sha(LAB/d['model']) != d['weights']:
                raise ValueError('Model weights changed')
            with nullcontext() if args.replay else local_server(PORT, d['model']):
                (initial if args.phase == 'initial' else follow)(make_author(d, args.replay))
