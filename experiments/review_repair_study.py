"""Compare the new production writer using frozen owner conversations. Score in a separate invocation."""
import argparse
from contextlib import nullcontext
from pathlib import Path

from experiments import festival_protocol as protocol, repeated_intervention as loop
from experiments.festival_mini import checksum
from experiments.local_transport import local_server, locked_output, read
from experiments.pipeline100.collect import Bank, bank_dirs
from experiments.project_review import freeze
from experiments.rule_cycle_study import load_public


ROOT = Path(__file__).resolve().parent
STUDY = ROOT / 'review-repair-20261126'
BASE = ROOT / 'pipeline100/runs'
TASKS = ('reservation', 'triage')
ROLES = ('multi', 'self')


def transcript(task, role, number):
    folder = BASE / task / ('live-' + role) / f'cycle-{number}'
    intake = read(folder / 'intake.json')
    answer = read(folder / 'answer.json')
    assert (intake['questions'], intake['ticket']) == (answer['questions'], answer['ticket'])
    return intake, answer


def instrument(task, folder, design, port):
    folder.mkdir(exist_ok=True, parents=True)
    archives = bank_dirs(task) + sorted((STUDY / 'preflight' / task).glob('**/calls'))
    archives.extend(sorted((STUDY / 'order-preflight/runs' / task).glob('**/calls')))
    archives.extend(sorted((STUDY / 'runs' / task).glob('**/calls')))
    return Bank(folder, design, port or 0, [p for p in archives if p != folder/'calls'], audit=port is None)


def run_arm(task, role, port):
    from experiments import review_patch
    design, draft = load_public(task)[-2:]
    previous, prior, reviews, receipts = draft['files'], None, [], []
    out = STUDY / 'runs' / task / role
    for n in (1, 2, 3):
        folder = out / f'cycle-{n}'
        ask = instrument(task, folder, design, port)
        intake, answer = transcript(task, role, n)
        receipts.append(answer)
        review_evidence = [*reviews, *[r for r in intake['reviews'] if 'response' in r]]
        outcome = review_patch.revise(design['project'], previous, receipts, design['seed'], role, ask,
                                      reviews=review_evidence, questions=intake['questions'], prior_writer=prior,
                                      final_round=(n==3))
        prefix = [draft['author_call']] if n == 1 else []
        snap = loop.snapshot(n, previous, intake, receipts, outcome, prefix)
        freeze(folder / 'snapshot.json', snap)
        previous, prior, reviews = outcome['files'], outcome['writer'], outcome['reviews']
        print(task, role, n, snap['status'], flush=True)
    loop.finish(out, snap, audit=port is None)


def focused(port):
    """Give the writer the archived code and its own reviews, without asking the owner again."""
    from experiments import review_patch
    task, role = 'reservation', 'multi'
    design = load_public(task)[-2]
    current = read(BASE / task / 'live-multi/cycle-2/snapshot.json')
    out = STUDY / 'runs' / task / 'focused'
    ask = instrument(task, out, design, port)
    receipts = [transcript(task,role,n)[1] for n in (1,2)]
    outcome = review_patch.revise(design['project'], current['files'], receipts, design['seed'], role, ask,
                                  reviews=current['reviews'], questions=[], prior_writer=current['writer'])
    freeze(out / 'snapshot.json', outcome)
    loop.finish(out, dict(cycle=3, **outcome), audit=port is None)
    print('지적된 기존 제출 수정 완료',flush=True)


def run(port):
    with locked_output(STUDY / 'runs'):
        sources = ['experiments/review_patch.py', 'experiments/repeated_intervention.py',
                   'backend/review_contracts.py','backend/review_literals.py','backend/decision_regions.py']
        check = {p:checksum(ROOT.parent/p) for p in sources}
        inputs = {str(p.relative_to(BASE)):checksum(p) for task in TASKS for role in ROLES
                  for n in (1,2,3) for p in ((BASE/task/('live-'+role)/f'cycle-{n}'/'answer.json'),
                                               (BASE/task/('live-'+role)/f'cycle-{n}'/'intake.json'))}
        freeze(STUDY/'implementation.json',dict(source=check,transcript=inputs,design=checksum(STUDY/'design.json')))
        with local_server(port, protocol.MODEL) if port is not None else nullcontext():
            focused(port)
            for task in TASKS:
                for role in ROLES:
                    run_arm(task, role, port)
        paths = sorted((STUDY / 'runs').glob('*/*/final.json'))
        assert len(paths) == 5
        assert all(checksum(ROOT.parent/p)==digest for p,digest in check.items())
        freeze(STUDY/'submissions.json', {str(p.relative_to(STUDY)):checksum(p) for p in paths})


def evaluate():
    from experiments.pipeline100.grade import verdict
    from experiments.pipeline100.records import rawcost
    for path, digest in read(STUDY/'submissions.json').items():
        assert checksum(STUDY / path) == digest
    sample = read(ROOT/'pipeline100/sample.json')
    def match(task, oldfiles, newfiles, cases):
        rows = []
        old, new = [verdict(task,next(iter(files.values())),cases) for files in (oldfiles, newfiles)]
        for i in cases:
            k = i['id']
            rows.append(dict(id=k, type=i['kind'], before=old[k], after=new[k]))
        return rows
    result = {'paired':{}, 'focused':{}}
    for task in TASKS:
        cases = [i for i in sample if i['task']==task and i['old_id']]
        for role in ROLES:
            old = read(BASE/task/('live-'+role)/'final.json')
            out = STUDY/'runs'/task/role
            new = read(out/'final.json')
            paths = [out/f'cycle-{n}' for n in (1,2,3)]
            calls = [key for path in paths for key in read(path/'snapshot.json')['calls']]
            rows = match(task,old['files'],new['files'],cases)
            result['paired'][f'{task}/{role}'] = dict(items=rows, cost=rawcost(calls,[*[p/'calls' for p in paths],*bank_dirs(task)]))
    base = BASE/'reservation/live-multi/cycle-2/snapshot.json'
    new = STUDY/'runs/reservation/focused/final.json'
    cases = [i for i in sample if i['task']=='reservation']
    result['focused']['items'] = match('reservation',read(base)['files'],read(new)['files'],cases)
    freeze(STUDY/'results.json',result)
    def counts(rows):
        return (sum(i['before']['status']=='정답' for i in rows),sum(i['after']['status']=='정답' for i in rows),
                [i['id'] for i in rows if any(i['before'][k]!=i['after'][k] for k in ('actual','status'))])
    for group, data in result['paired'].items():
        print(group, counts(data['items']),data['cost']['total_tokens'])
    print('review of archived code',counts(result['focused']['items']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('run','audit','evaluate'))
    parser.add_argument('--port',type=int,default=18784)
    args = parser.parse_args()
    if args.action == 'run':
        run(args.port)
    elif args.action == 'audit':
        run(None)
    else:
        evaluate()

