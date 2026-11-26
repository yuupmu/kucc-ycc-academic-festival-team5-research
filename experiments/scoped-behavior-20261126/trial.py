"""Prepare the matched study, then produce all new submissions before any evaluation."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parents[1]
OLD = ROOT.parent / 'answer-flip-20261126'
sys.path[:0] = [str(LAB), str(OLD)]

from experiments import scoped_reply_writer as writer
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from run_pairs import content_hash, sealed_text


def public_history(state, side):
    return [dict(request_id='abc-1', questions=state['questions'], answer={'text': state['answers'][side]})]


def setup():
    past = read(OLD / 'design.json')
    paths = [OLD / 'frozen' / (name + '.json') for name in ('upload', 'sensors')]
    paths += [LAB / name for name in ('experiments/scoped_transfer.py', 'backend/allocation_repair.py',
                                       'experiments/local_transport.py', 'experiments/festival_protocol.py')]
    for path in paths:
        if content_hash(path) != past['signatures'][str(path.relative_to(LAB))]:
            raise ValueError(f'Archived input changed: {path}')
    paths += [Path(__file__).resolve(), ROOT / 'score.py', Path(writer.__file__),
              LAB / 'experiments/scoped_transfer_v2.py', OLD / 'sealed-all.json']
    design = dict(model=past['model'], model_sha256=past['weights']['sha256'],
                  task_seeds={'upload': [273, 419, 887], 'sensors': [419]}, sides=['A', 'B'],
                  sampling={k: past[k] for k in ('temperature','top_p','top_k','thinking')},
                  controls='Same public brief, draft, three or one archived question(s), owner reply, seed, weights, local patcher and edit output limits.',
                  grading='After all eight submissions are frozen. Upload primary 15,16,17 and fixed prior integer grid -2..33. Sensors: prior finite grid of the four readings through length four. Compare fixes, losses, strict typed returns, paired changes and writer tokens.',
                  files={str(p.relative_to(LAB)): content_hash(p) for p in paths})
    freeze(ROOT / 'design.json', design)


def execute():
    os.chdir(LAB)
    design = read(ROOT / 'design.json')
    for name, checksum in design['files'].items():
        if Path(name).name != 'score.py' and content_hash(LAB / name) != checksum:
            raise ValueError(f'Changed after registration: {name}')
    if content_hash(LAB / design['model']) != design['model_sha256']:
        raise ValueError('Model weights changed')
    seals = {}
    port = 18954
    with local_server(port, design['model']):
        for task, seeds in design['task_seeds'].items():
            state = read(OLD / 'frozen' / (task + '.json'))
            for i, seed in enumerate(seeds):
                for side in (design['sides'] if i % 2 else design['sides'][::-1]):
                    label = f'{task}/{seed}/{side}'
                    dest = ROOT / 'runs' / label
                    dest.mkdir(exist_ok=True, parents=True)

                    def ask(role, prompt, packet, schema, call_seed, limit):
                        return call_model(dest, design, role, prompt, packet, schema, call_seed, limit, port)

                    code, record = writer.revise(state['brief'], state['code'], public_history(state, side),
                                                 state['review'], seed, ask)
                    source_hash = sealed_text(dest / 'solution.py', code)
                    record['logs'] = {key: content_hash(dest / 'calls' / (key + '.json')) for key in record['calls']}
                    freeze(dest / 'writer.json', record)
                    seals[label] = dict(source=source_hash, record=content_hash(dest / 'writer.json'))
                    print('sealed', label, flush=True)
    freeze(ROOT / 'sealed.json', dict(design=content_hash(ROOT / 'design.json'), submissions=seals))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    with locked_output(ROOT):
        if parser.parse_args().action == 'prepare':
            setup()
        else:
            execute()
