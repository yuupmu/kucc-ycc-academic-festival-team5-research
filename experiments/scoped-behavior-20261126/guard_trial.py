"""Repeat the frozen second study with only the final edit transport exchanged."""
import argparse
from pathlib import Path
from types import SimpleNamespace

import site_trial as protocol
from experiments import guarded_reply
from trial import LAB, ROOT, content_hash, freeze, locked_output, read

OUT = ROOT / 'scalar-guards'


def setup():
    previous = ROOT / 'named-operations'
    design = read(previous / 'design.json')
    paths = [previous / name for name in ('sealed.json', 'results.json', 'design.json')]
    paths += [Path(__file__).resolve(), Path(guarded_reply.__file__)]
    files = {**design['files'], **{str(p.relative_to(LAB)):content_hash(p) for p in paths}}
    freeze(OUT / 'design.json', dict(design, files=files, change=(
        'For unresolved scalar integer Boolean decisions with one grounded owner passage, '
        'compile the predicted true region only when an independently stated false region exactly '
        'partitions the integer domain. Other cases use the original direct edit. Charge the common reader.')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','run','grade'))
    action = parser.parse_args().action
    # The second trial is frozen. Reuse its identical wait, replay, seal, and grading procedures.
    protocol.OUT = OUT
    protocol.scoped_sites = SimpleNamespace(with_sites=guarded_reply.with_guards)
    with locked_output(OUT):
        {'prepare':setup, 'run':protocol.run, 'grade':protocol.grade}[action]()
