"""Matched compact-writer supplement. All receipts and candidates are fixed before scoring."""
from pathlib import Path

from backend import anchored_program
from experiments import festival_mini as old, rule_program_cycle
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls
from experiments.rule_cycle_experiment import preflight
from experiments.rule_cycle_study import STUDY, load_public, paths


VARIANTS={'apply-program':'apply','both-program':'both','self-program':'self-apply'}


def program_preflight():
    design=preflight()
    files=(Path(anchored_program.__file__),Path(rule_program_cycle.__file__),Path(__file__))
    freeze(STUDY/'program-manifest.json',dict(source={p.name:old.checksum(p) for p in files},base=old.checksum(STUDY/'implementation-v2-manifest.json'),
           variants=VARIANTS,scope='Fixed after viewing source and output-format failures, before any new candidate grading. '
           'Same public inputs, actual initial reviews, owner replies, first main plan, model, seed, and final review. '
           'Only the last writer representation changes. General pure decision expressions, no task-specific code substitution.',
           native_finals={t:{arm:old.checksum(paths(t)[0]/'candidates'/arm/'final.json') for arm in VARIANTS.values()} for t in design['projects']}))
    return design


def program_record(task,arm,port,audit=False):
    out,parent,prior,design,draft=load_public(task)
    sibling=VARIANTS[arm]
    original=read(out/'candidates'/sibling/'final.json')
    own=arm=='self-program'
    if arm=='both-program':
        intake=read(out/'intake.json')
        initial=[draft['author_call'],*intake['calls']]
        questions=intake['questions']
        receipt=read(out/'operator.json') if questions else None
    else:
        review=read((parent/'self' if own else prior/'p4')/'v1/review.json')
        questions,initial=review['questions'],review['calls']
        receipt=read(old.selection_path(task,'self' if own else 'p4',1)) if questions else None
    reply=receipt['text'] if receipt else None
    if (receipt and questions!=receipt['questions']) or (questions,reply)!=(original['questions'],original['reply']):
        raise ValueError('작성 방식 비교에 다른 질문이나 담당자 답변이 들어왔습니다.')
    ask=Calls(out,design,port,(parent/'calls',prior/'calls'),audit)
    final=rule_program_cycle.revise(design['project'],draft['files'],reply,design['seed'],'self' if own else 'multi',ask)
    if final['writer']['calls'][0]!=original['writer']['calls'][0] or initial!=original['calls'][:len(initial)]:
        raise ValueError('초안, 질문 또는 메인 규칙 메모가 짝지은 조건과 다릅니다.')
    final.update(arm=arm,initial_sha256=draft['sha256'],questions=questions,reply=reply,
                 owner_source='delegated_policy_card' if receipt else None,selections=receipt['selections'] if receipt else [],
                 calls=[*initial,*final['calls']])
    folder=out/'candidates'/arm
    if audit:
        target=folder/'submissions/candidate'
        exported={f.relative_to(target).as_posix():f.read_bytes() for f in target.rglob('*') if f.is_file()}
        if read(folder/'final.json')!=final or exported!={p:s.encode() for p,s in final['files'].items()}:
            raise ValueError('고정된 후보와 호출 재구성이 다릅니다.')
    else:
        folder.mkdir(exist_ok=True,parents=True)
        publish(folder,'candidate',final['files'])
        freeze(folder/'final.json',final)
    return final


def run(port):
    with locked_output(STUDY/'runs'):
        config=program_preflight()
        with local_server(port,config['model']):
            for task in config['projects']:
                with locked_output(paths(task)[0]):
                    for arm in VARIANTS:
                        final=program_record(task,arm,port)
                        print(task,arm,final['status'],final['writer']['error'],flush=True)
