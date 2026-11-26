"""Research-only adapter for the existing two projects, fixed 20 items and scoped operator replies."""
import argparse
from pathlib import Path

from experiments import festival_mini as old, festival_protocol as base, rule_intake
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.rule_cycle_calls import Calls


STUDY = Path(__file__).resolve().parent / 'rule-cycle-20261126'
CONFIG = STUDY / 'design.json'


def paths(task):
    if task not in read(CONFIG)['projects']:
        raise ValueError('등록되지 않은 연구 과제입니다.')
    return STUDY/'runs'/task, old.STUDY/'runs'/task, old.STUDY/'refined-v2'/task


def load_public(task):
    out, parent, previous = paths(task)
    design = read(parent/'design.json')
    config = read(CONFIG)
    if any(config[k] != design[k] for k in ('seed','model')):
        raise ValueError('원본과 모델·시드가 다릅니다.')
    draft = read(parent/'p3/v1/snapshot.json')
    if (draft['sha256'] != base.core.digest(draft['files']) or draft != read(parent/'self/v1/snapshot.json')
            or draft != read(previous/'p4/v1/snapshot.json')):
        raise ValueError('세 조건의 공통 초안이 다릅니다.')
    return out, parent, previous, design, draft


def record_intake(task, port, audit=False):
    out, parent, previous, design, draft = load_public(task)
    ask = Calls(out, design, port, (parent/'calls', previous/'calls'), audit)
    result = rule_intake.inspect(design['project'], draft['files'], design['seed'], ask)
    path = out/'intake.json'
    if audit:
        if read(path) != result:
            raise ValueError('처음 감시 질문이 원래 호출에서 재현되지 않습니다.')
    else:
        freeze(path, result)
    return result


def start(port):
    config = read(CONFIG)
    with locked_output(STUDY/'runs'):
        old.preregister(read(old.CONFIG))
        freeze(STUDY/'intake-manifest.json', {
            'design_sha256':old.checksum(CONFIG), 'reference_sha256':old.checksum(old.CONFIG),
            'policy_sha256':old.checksum(old.FIXTURES/'operator-cards.json'),
            'operator_variants_sha256':old.checksum(old.STUDY/'operator-variants.json'),
            'intake_sha256':old.checksum(Path(rule_intake.__file__))})
        with local_server(port,config['model']):
            for task in config['projects']:
                with locked_output(paths(task)[0]):
                    r = record_intake(task, port)
                    print(task, [q['question'] for q in r['questions']], flush=True)


def select(task, selections):
    out = paths(task)[0]
    questions = read(out/'intake.json')['questions']
    if len(selections) != len(questions):
        raise ValueError('실제 질문마다 요청한 규칙만 지정하세요.')
    if not questions:
        raise ValueError('담당자에게 전달된 질문이 없습니다.')
    freeze(out/'operator.json',dict(questions=questions,selections=selections,text=compose(task,selections),
                                    source='delegated_policy_card'))


def compose(task, selections):
    clauses = old.lexicon(task)
    if task == 'triage':
        # The third watcher asked for one concrete outcome of the already frozen rank policy.
        clauses['three_known'] = '말씀하신 billing, account, privacy가 모두 있는 요청은 privacy 팀으로 보냅니다.'
    if not selections or any(not group or any(k not in clauses for k in group) for group in selections):
        raise ValueError('질문에 해당하는 고정 정책의 문장만 선택하세요.')
    return '\n'.join(dict.fromkeys(clauses[k] for group in selections for k in group))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('ask','select','run','program','regions','report'))
    parser.add_argument('selection',nargs='*')
    parser.add_argument('--port',type=int,default=18769)
    args = parser.parse_args()
    if args.action == 'ask':
        start(args.port)
    elif args.action == 'select':
        task, *groups = args.selection
        select(task,[g.split(',') for g in groups])
    elif args.action == 'run':
        from experiments.rule_cycle_experiment import run
        run(args.port)
    elif args.action == 'program':
        from experiments.rule_program_study import run
        run(args.port)
    elif args.action == 'regions':
        from experiments.region_study import run
        run(args.port)
    else:
        from experiments.rule_cycle_report import report
        report()
