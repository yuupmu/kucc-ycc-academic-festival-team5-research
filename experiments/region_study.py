"""Final writer representation fixed before the twenty-case evaluation."""
from pathlib import Path

from backend import decision_regions
from experiments import festival_mini as old, region_cycle
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls
from experiments.rule_cycle_study import STUDY,load_public,paths
from experiments.rule_program_study import program_preflight


VARIANTS={'apply-regions':'apply','both-regions':'both','self-regions':'self-apply'}


def preflight():
    config=program_preflight()
    frozen=[Path(m.__file__) for m in (decision_regions,region_cycle)]+[Path(__file__)]
    freeze(STUDY/'regions-manifest.json',dict(base=old.checksum(STUDY/'program-manifest.json'),variants=VARIANTS,
          sources={p.name:old.checksum(p) for p in frozen},
          reason='Before grading: the free-expression writer applied sequence operations to numbers or bound a sourced quantity '
                 'to the wrong variable. Replace free expressions with disjoint symbolic regions on applicable functions. '
                 'Same actual owner replies, first main plan, first code, seed and reviewers. No new benchmark inputs or labels.',
          prior_outputs={t:{a:old.checksum(paths(t)[0]/'candidates'/a/'final.json') for a in ('apply-program','both-program','self-program')}
                         for t in config['projects']}))
    return config


def record(task,arm,port,audit=False):
    out,parent,prior,design,draft=load_public(task)
    own=arm=='self-regions'
    sibling=read(out/'candidates'/VARIANTS[arm]/'final.json')
    questions,reply=sibling['questions'],sibling['reply']
    if arm=='both-regions':
        intake=read(out/'intake.json')
        initial=[draft['author_call'],*intake['calls']]
        receipt=read(out/'operator.json') if intake['questions'] else None
    else:
        intake=read((parent/'self' if own else prior/'p4')/'v1/review.json')
        initial=intake['calls']
        receipt=read(old.selection_path(task,'self' if own else 'p4',1)) if intake['questions'] else None
    if (questions!=intake['questions'] or (receipt and (receipt['questions'],receipt['text'])!=(questions,reply))
            or (not receipt and reply is not None) or initial!=sibling['calls'][:len(initial)]):
        raise ValueError('질문 또는 허가된 자연어 정보가 짝지은 조건과 다릅니다.')
    ask=Calls(out,design,port,(parent/'calls',prior/'calls'),audit)
    final=region_cycle.revise(design['project'],draft['files'],reply,design['seed'],'self' if own else 'multi',ask)
    if final['writer']['calls'][0]!=sibling['writer']['calls'][0]:
        raise ValueError('같은 작성 메모를 재사용하지 않았습니다.')
    final.update(arm=arm,initial_sha256=draft['sha256'],questions=questions,reply=reply,selections=receipt['selections'] if receipt else [],
                 owner_source='delegated_policy_card' if receipt else None,calls=[*initial,*final['calls']])
    folder=out/'candidates'/arm
    if audit:
        dest=folder/'submissions/candidate'
        exported={p.relative_to(dest).as_posix():p.read_bytes() for p in dest.rglob('*') if p.is_file()}
        if read(folder/'final.json')!=final or exported!={p:s.encode() for p,s in final['files'].items()}:
            raise ValueError('저장한 최종 코드 또는 출처가 재현되지 않았습니다.')
    else:
        folder.mkdir(exist_ok=True,parents=True)
        publish(folder,'candidate',final['files'])
        freeze(folder/'final.json',final)
    return final


def run(port):
    with locked_output(STUDY/'runs'):
        config=preflight()
        with local_server(port,config['model']):
            for task in config['projects']:
                with locked_output(paths(task)[0]):
                    for arm in VARIANTS:
                        final=record(task,arm,port)
                        print(task,arm,final['status'],final['writer'].get('format'),flush=True)
