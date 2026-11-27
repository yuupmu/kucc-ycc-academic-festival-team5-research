"""Discovery study runner: one shared draft per task x seed, four review arms, then the question-agenda stage.

Mirrors experiments/festival-validation-20261127/run.py (project, caller, prepare) and
experiments/mixed_review_ledger.py handoff. Only the new arm `same3` differs from that handoff.

  python3 -B experiments/discovery-study-20261127/run.py main    # 15 tasks x 5 seeds x 4 arms -> runs/, calls/
  python3 -B experiments/discovery-study-20261127/run.py smoke   # old festival `cover` task, seed 941 -> smoke/
Resume-safe: stored calls are reused, finished arms (prepared.json) are skipped.
"""
import argparse
import os
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from backend.structured_output import array, obj
from experiments.festival_protocol import MODEL, call_model
from experiments.ledger_pipeline import open_ticket
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING, VIEWS
from experiments.scoped_transfer_v2 import DRAFT, REVIEW

DESIGN = read(OUT / 'design.json')
FESTIVAL = read(LAB / 'experiments/festival-validation-20261127/design.json')
PORT = DESIGN['port']
ARMS = ('self1', 'ind1', 'same3', 'split3')
MODE = dict(self1='self', ind1='one', same3='same', split3='three')
assert MODEL == DESIGN['model'] and tuple(DESIGN['arms']) == ('self1', 'ind1', 'same3', 'split3')


def review_schema(mode):
    return obj({'questions': array(STRING, 0, 3 if mode in ('self', 'one') else 1), 'issue': STRING})


def draft_schema():
    return obj({'code': STRING})


def handoff(project, ask, base_seed, mode):
    """Copy of mixed_review_ledger.handoff for modes self/one/three, plus the new mode `same`."""
    calls, questions, issues = [], [], []
    key, draft = ask(MODEL, 'main', DRAFT, project, draft_schema(), base_seed, 1100)
    if not draft:
        raise ValueError('Invalid draft')
    calls.append(key)
    source = draft['code']
    compile(source, 'solution.py', 'exec')
    if mode in ('self', 'one'):
        assignments = [(MODEL, ' 및 '.join(VIEWS))]
    elif mode == 'same':
        assignments = [(MODEL, ' 및 '.join(VIEWS))] * 3
    elif mode == 'three':
        assignments = list(zip((MODEL,) * 3, VIEWS))
    else:
        raise ValueError('unknown mode ' + mode)
    for i, (model, view) in enumerate(assignments):
        packet = dict(brief=project['brief'], code=source, dialogue=[])
        role, intro = 'observer-' + 'ABC'[i], '당신은 독립 감시자입니다. '
        if mode == 'self':
            role, intro = 'main-review', '당신이 방금 작성한 초안을 스스로 검토하세요. '
            packet['draft_context'] = dict(instruction=DRAFT, original_request=project)
        key, resp = ask(model, role, intro + view + REVIEW, packet, review_schema(mode), base_seed + 10 + i, 1100)
        calls.append(key)
        if resp:
            questions.extend(q.strip() for q in resp['questions'] if q.strip())
            if resp['issue'].strip():
                issues.append(resp['issue'])
    return dict(brief=project['brief'], code=source, questions=list(dict.fromkeys(questions)), review=issues, calls=calls)


def save(folder, name, value):
    folder.mkdir(exist_ok=True, parents=True)
    freeze(folder / name, value)


def project(meta):
    return dict(brief=meta['brief'], files={'solution.py': 'def ' + meta['function'] + '(' + meta['signature'] + ') -> bool:\n    raise NotImplementedError\n'})


def caller(root, seed, log, invoke=recorded):
    def ask(model, role, prompt, packet, fmt, request_seed, cap):
        key, val = call_model(root, {'model': model}, role, prompt, packet, fmt, request_seed, cap, PORT, invoke=invoke)
        log.append(key)
        return key, val

    def writer(role, prompt, packet, fmt, cap):
        return ask(MODEL, role, prompt, packet, fmt, seed + 10, cap)
    return ask, writer


def prepare(root, folder, meta, seed, arm, invoke=recorded):
    """Same flow and statuses as festival-validation prepare(); returns the status."""
    if (folder / 'prepared.json').exists():
        return read(folder / 'prepared.json')['status']
    calls = []
    ask, writer = caller(root, seed, calls, invoke)
    try:
        packet = handoff(project(meta), ask, seed, MODE[arm])
    except (SyntaxError, ValueError) as error:
        save(folder, 'prepared.json', dict(status='draft_failed', error=str(error), calls=calls, questions=[]))
        return 'draft_failed'
    save(folder, 'handoff.json', packet)
    status, questions, error = 'no_question', [], None
    if packet['questions']:
        try:
            agenda = open_ticket(folder, packet, writer)
            questions = list(agenda['sent_questions'].values())
            status = 'ready' if agenda['slots'] else 'no_open_decisions'
        except (ValueError, SyntaxError, TypeError) as exc:
            status, error = 'agenda_failed', str(exc)
    save(folder, 'prepared.json', dict(status=status, questions=questions, error=error, calls=calls))
    return status


def cases(phase):
    if phase == 'smoke':
        yield 'cover', FESTIVAL['cover'], 941
        return
    for task, meta in DESIGN['tasks'].items():
        for seed in DESIGN['seeds']:
            yield task, meta, seed


def run(phase):
    root = OUT / 'smoke' if phase == 'smoke' else OUT
    with locked_output(root):
        started = time.time()
        with local_server(PORT, MODEL):
            print(time.strftime('%H:%M:%S'), 'server up', round(time.time() - started, 1), 's', flush=True)
            for task, meta, seed in cases(phase):
                unit = time.time()
                for arm in ARMS:
                    status = prepare(root, root / 'runs' / task / str(seed) / arm, meta, seed, arm)
                    print(time.strftime('%H:%M:%S'), task, seed, arm, status, flush=True)
                print(time.strftime('%H:%M:%S'), 'unit', task, seed, round(time.time() - unit, 1), 's', flush=True)
        print(time.strftime('%H:%M:%S'), 'done', round(time.time() - started, 1), 's', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['main', 'smoke'])
    phase = parser.parse_args().phase
    os.chdir(LAB)  # The model path in MODEL is relative to the worktree root.
    run(phase)


if __name__ == '__main__':
    main()
