"""Replay the submitted reservation writer with the same policy text and vary only the requested rows."""
from copy import deepcopy
from pathlib import Path
import json

from backend import answer_contracts, decision_regions
from experiments.local_transport import compact, generate, local_server, read
from experiments.project_review import freeze


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/reservation/live-multi/cycle-2'
OUT = ROOT / 'diagnostics/choice-order'
CELL = 'age_seconds == 600 and 0 < until_start_seconds < 86400'


def select_rows(request, rows):
    result = deepcopy(request)
    message = result['messages'][1]
    packet = json.loads(message['content'])
    packet['입력영역'] = rows
    message['content'] = compact(packet)
    spec = result['response_format']['json_schema']['schema']['properties']['regions']
    spec['properties'] = {key: spec['properties'][key] for key in rows}
    spec['required'] = rows
    return result


def check_validation(original):
    request = original['request']
    packet = json.loads(request['messages'][1]['content'])
    previous = read(RUN.parent / 'cycle-1/snapshot.json')['writer']['answer_application'][0]
    writer = read(RUN / 'snapshot.json')['writer']
    replies = [read(RUN.parent / f'cycle-{n}/answer.json') for n in (1, 2)]
    layout = decision_regions.layout(['age_seconds', 'until_start_seconds'], packet['원문'], writer['decisions'])
    for value in ('True', 'False'):
        choice = json.loads(original['text'])
        choice['regions'][CELL]['result'] = value
        bound, report = answer_contracts.bind(choice, packet, replies, True, previous)
        _, rows = decision_regions.apply_choices('T1', layout, bound['regions'], packet['원문'])
        row = next(row for row in rows if row['region'] == CELL)
        print('validation', value, row['selected'], row['issue'], report['issues'], flush=True)
        assert (row['selected'], row['issue'], report['issues']) == (value, None, [])


def run():
    records = [read(p) for p in (RUN / 'calls').glob('*.json')]
    original, = [rec for rec in records if rec['role'] == 'main-region-decisions']
    check_validation(original)
    request = original['request']
    rows = json.loads(request['messages'][1]['content'])['입력영역']
    assert len(rows) == 25 and rows.count(CELL) == 1
    assert select_rows(request, rows) == request
    conditions = {
        'original-order': rows,
        'only-this-row': [CELL],
        'this-row-first': [CELL, *(r for r in rows if r != CELL)],
    }
    OUT.mkdir(exist_ok=True)
    with local_server(18781, request['model']):
        for label, order in conditions.items():
            variant = select_rows(request, order)
            path = OUT / (label + '.json')
            if path.is_file():
                response = read(path)
            else:
                response = generate(18781, variant['model'], variant['messages'], variant['seed'],
                                    variant['max_tokens'], 'off', variant['response_format'])
                assert response['request'] == variant and response['model'] == variant['model']
                freeze(path, response)
            assert response['request'] == variant and response['finish_reason'] == 'stop'
            selected = json.loads(response['text'])['regions']
            assert set(selected) == set(order)
            print(label, len(selected), selected[CELL], 'first response key', next(iter(selected)), flush=True)


if __name__ == '__main__':
    run()

