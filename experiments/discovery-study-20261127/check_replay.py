"""Model-free equivalence proof: this runner's handoff reproduces festival-validation's committed handoffs.

Uses a temporary copy of festival-validation-20261127/calls/ as the cache and a generator that raises on any
new model call. Arms self1/ind1/split3 are compared with festival modes self/one/three on papers/cover x 941/967/991.
The full prepare() (agenda stage) is replayed too and its prepared.json compared, as an extra check.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import run
from experiments.local_transport import read, recorded

FEST = run.LAB / 'experiments/festival-validation-20261127'
PAIRS = dict(self1='self', ind1='one', split3='three')


def forbid(*_args, **_kw):
    raise RuntimeError('replay attempted a new model call')


def invoke(path, *args):
    if not path.exists():
        raise RuntimeError('replay attempted a new model call: ' + path.name)
    return recorded(path, *args, generator=forbid)


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='discovery-replay-') as tmp:
        root = Path(tmp)
        shutil.copytree(FEST / 'calls', root / 'calls')
        before = sorted(p.name for p in (root / 'calls').iterdir())
        for task in ('papers', 'cover'):
            meta = run.FESTIVAL[task]
            for seed in run.FESTIVAL['seeds']:
                for arm, old in PAIRS.items():
                    ref = FEST / 'runs' / task / str(seed) / old
                    log = []
                    ask, _ = run.caller(root, seed, log, invoke)
                    mine = run.handoff(run.project(meta), ask, seed, run.MODE[arm])
                    folder = root / 'runs' / task / str(seed) / arm
                    status = run.prepare(root, folder, meta, seed, arm, invoke)
                    theirs_prep = read(ref / 'prepared.json')
                    mine_prep = read(folder / 'prepared.json')
                    row = dict(task=task, seed=seed, arm=arm, reference=str(ref.relative_to(run.LAB)),
                               handoff_equal=canon(mine) == canon(read(ref / 'handoff.json')),
                               stored_handoff_equal=canon(read(folder / 'handoff.json')) == canon(read(ref / 'handoff.json')),
                               prepared_equal=canon(mine_prep) == canon(theirs_prep), status=status)
                    # festival's primary agenda stage used decision_ledger_v1; its supplement/ re-ran the one
                    # affected path with the current decision_ledger, which is the one pinned for this study.
                    supp = FEST / 'supplement' / ref.relative_to(FEST)
                    if (supp / 'prepared.json').exists():
                        row['supplement_reference'] = str(supp.relative_to(run.LAB))
                        # supplement prepare() started from the stored handoff, so its call log holds only agenda calls.
                        agenda_only = dict(mine_prep, calls=mine_prep['calls'][len(mine['calls']):])
                        row['prepared_equal_supplement'] = canon(agenda_only) == canon(read(supp / 'prepared.json'))
                        if (supp / 'agenda.json').exists():
                            row['agenda_equal_supplement'] = canon(read(folder / 'agenda.json')) == canon(read(supp / 'agenda.json'))
                    if (ref / 'agenda.json').exists():
                        row['agenda_equal'] = canon(read(folder / 'agenda.json')) == canon(read(ref / 'agenda.json'))
                    results.append(row)
                    print(task, seed, arm, row, flush=True)
        after = sorted(p.name for p in (root / 'calls').iterdir())
    matched = sum(r['handoff_equal'] and r['stored_handoff_equal'] for r in results)
    report = dict(note=__doc__.strip(), compared=len(results), handoff_matched=matched,
                  prepared_matched=sum(r['prepared_equal'] for r in results),
                  prepared_matched_current_ledger=sum(r.get('prepared_equal_supplement', r['prepared_equal']) for r in results),
                  agenda_compared=sum('agenda_equal' in r for r in results),
                  agenda_matched=sum(r.get('agenda_equal', False) for r in results),
                  new_calls=len(after) - len(before), rows=results)
    (run.OUT / 'replay-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('handoff matched', matched, 'of', len(results), '| prepared matched', report['prepared_matched'])
    sys.exit(0 if matched == len(results) == 18 and report['new_calls'] == 0 else 1)


if __name__ == '__main__':
    main()
