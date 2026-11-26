"""Use the archived writer with the automatic scope and an explicit outstanding-policy check."""
import argparse
import hashlib
import shutil
import sys
from contextlib import nullcontext
from pathlib import Path

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
FIRST = OUT.parent/'mixed-upload-three-answers-20261126'
PRIOR = OUT.parent/'mixed-upload-issue-20261126'
sys.path.insert(0, str(LAB))
from backend.project_review import digest
from experiments import partial_predicate_reply as writer, partial_reply
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.project_review import freeze

NAMES = ('include', 'exclude', 'unmentioned')
PORT = 18981
ARCHIVES = (PRIOR/'round-1/new/calls', FIRST/'calls')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    prior = read(FIRST/'design.json')
    assert (FIRST/'final-seal.json').exists()
    for name in NAMES:
        (OUT/name).mkdir(exist_ok=True)
        freeze(OUT/name/'input.json', read(FIRST/name/'input.json'))
    files = [FIRST/'design.json', FIRST/'final-seal.json', PRIOR/'input.json', Path(__file__), OUT/'assess.py',
             FIRST/'assess.py', Path(writer.__file__), Path(partial_reply.__file__), LAB/'experiments/scoped_reply_writer.py',
             LAB/'experiments/guarded_reply.py', LAB/'experiments/reply_pipeline.py',
             *[OUT/name/'input.json' for name in NAMES]]
    freeze(OUT/'design.json', dict(model=prior['model'], seed=prior['seed'], weights=prior['weights'],
        shared=prior['shared'], follow=prior['follow'], endpoint=prior['endpoint'], controls=prior['controls'],
        success=prior['success'], change='Keep previous main-behavior and main-predicates messages. The same automatic scope locates the edits. A separate stateless reader expresses still unanswered policy as a predicate. Only singly decided, uncontradicted regions outside that predicate are compiled on current pending statements. One run per receipt, no retries or grading before final seal.',
        cache='Reuse byte-identical model requests by role/request digest only, including common scope and archived original writer calls.',
        files={str(p.relative_to(LAB)): sha(p) for p in files}))


def design():
    d = read(OUT/'design.json')
    for path, checksum in d['files'].items():
        if sha(LAB/path) != checksum:
            raise ValueError('Changed input: '+path)
    return d


def author(d, replay):
    def infer(path, *params):
        if not path.is_file():
            for folder in ARCHIVES:
                origin = folder/path.name
                if origin.exists():
                    shutil.copyfile(origin, path)
                    break
        return recorded(path, *params)
    def ask(role, prompt, packet, schema, limit):
        return call_model(OUT, d, role, prompt, packet, schema, d['seed'], limit, PORT, audit=replay, invoke=infer)
    return ask


def submit(folder, source, trace):
    folder.mkdir(exist_ok=True)
    path = folder/'solution.py'
    if path.exists():
        assert path.read_bytes() == source.encode()
    else:
        path.write_bytes(source.encode())
    freeze(folder/'trace.json', trace)
    return dict(code=sha(path), trace=sha(folder/'trace.json'))


def initial(ask):
    common = read(PRIOR/'input.json')
    scope = partial_reply.scope(common['brief'], common['code'], common['dialogue'][0]['questions'], common['review'], ask)
    freeze(OUT/'scope.json', scope)
    snapshots, requests = {}, {}
    for name in NAMES:
        folder = OUT/name
        p = read(folder/'input.json')
        source, trace = writer.revise(p['brief'], p['code'], p['dialogue'], p['review'],
                                      scope['sites'] if scope['accepted'] else [], ask)
        trace['calls'] = scope['calls'] + trace['calls']
        snapshots[name] = submit(folder/'initial', source, trace)
    freeze(OUT/'initial-seal.json', dict(design=sha(OUT/'design.json'), scope=sha(OUT/'scope.json'), snapshots=snapshots))
    for name in NAMES:
        folder = OUT/name
        p, trace = read(folder/'input.json'), read(folder/'initial/trace.json')
        q, keys = partial_reply.clarification(p['brief'], [p['dialogue'][0]['answer']['text']], trace['unresolved'], ask)
        freeze(folder/'question.json', dict(question=q, calls=keys))
        requests[name] = sha(folder/'question.json')
    freeze(OUT/'question-seal.json', dict(initial=sha(OUT/'initial-seal.json'), requests=requests))


def follow(ask):
    first, requests, owner = (read(OUT/k) for k in ('initial-seal.json', 'question-seal.json', 'owner-delivery.json'))
    assert first['design'] == sha(OUT/'design.json') and requests['initial'] == sha(OUT/'initial-seal.json')
    assert owner['requests'] == sha(OUT/'question-seal.json')
    snapshots = {}
    for name in NAMES:
        folder = OUT/name
        q = read(folder/'question.json')['question']
        assert sha(folder/'question.json') == requests['requests'][name]
        assert first['snapshots'][name] == dict(code=sha(folder/'initial/solution.py'), trace=sha(folder/'initial/trace.json'))
        if not q:
            assert name not in owner['replies']
            snapshots[name] = dict(stage='initial', **first['snapshots'][name])
            continue
        response = owner['replies'][name]
        assert response.strip()
        p, trace = read(folder/'input.json'), read(folder/'initial/trace.json')
        source = (folder/'initial/solution.py').read_text()
        remaining = partial_reply.remaining_locations(source, p['brief'], [p['dialogue'][0]['answer']['text']], trace['unresolved'])
        history = [*p['dialogue'], dict(request_id='follow', questions=[q], answer={'text': response})]
        new, log = writer.revise(p['brief'], source, history, p['review'], remaining, ask)
        snapshots[name] = dict(stage='after-reply', **submit(folder/'after-reply', new, log))
    raw = {p.stem: sha(p) for p in sorted((OUT/'calls').glob('*.json'))}
    freeze(OUT/'final-seal.json', dict(questions=sha(OUT/'question-seal.json'), owner=sha(OUT/'owner-delivery.json'),
                                      snapshots=snapshots, calls=raw))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'initial', 'follow'])
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    with locked_output(OUT):
        if args.phase == 'prepare':
            prepare()
        else:
            d = design()
            if not args.replay and sha(LAB/d['model']) != d['weights']:
                raise ValueError('Weights changed')
            with nullcontext() if args.replay else local_server(PORT,d['model']):
                (initial if args.phase=='initial' else follow)(author(d,args.replay))
