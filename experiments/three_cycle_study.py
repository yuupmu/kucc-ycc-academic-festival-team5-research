"""Research adapter for paired one- versus three-window runs on the same twenty examples."""
import argparse
from pathlib import Path

from experiments import festival_mini, region_study
from experiments.baselines.three_cycle_v1 import repeated_intervention as loop
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.rule_cycle_study import STUDY as PREVIOUS, compose, load_public


STUDY=Path(__file__).resolve().parent/'three-cycles-20261126'
CONFIG=STUDY/'design.json'


def root(task,role):
    design=read(CONFIG)
    if task not in design['projects'] or role not in design['first_cycle']:
        raise ValueError('설계에 없는 과제나 조건입니다.')
    return STUDY/'runs'/task/role


def preregister():
    config=read(CONFIG)
    original=region_study.preflight()
    if any(config[k]!=original[k] for k in ('model','projects','seed')):
        raise ValueError('고정 모델·표본과 연구 설정이 다릅니다.')
    checksum=festival_mini.checksum
    freeze(STUDY/'manifest.json',dict(design=checksum(CONFIG),previous_writer=checksum(PREVIOUS/'regions-manifest.json'),
           sample=checksum(festival_mini.CONFIG),previous_inputs=checksum(festival_mini.STUDY/'manifest.json'),
           owner_cards=checksum(festival_mini.FIXTURES/'operator-cards.json'),owner_variants=checksum(festival_mini.STUDY/'operator-variants.json'),
           implementation={p.name:checksum(p) for p in [Path(loop.__file__),Path(loop.__file__).with_name('three_cycle_study.py')]},
           baseline={t:{r:checksum(PREVIOUS/'runs'/t/'candidates'/a/'final.json') for r,a in config['first_cycle'].items()}
                     for t in config['projects']}))
    return config


def first_cycle(task,role,audit=False):
    out=root(task,role)
    folder=loop.directory(out,1)
    if not audit:
        folder.mkdir(parents=True,exist_ok=True)
    earlier,parent,_,design,draft=load_public(task)
    arm=read(CONFIG)['first_cycle'][role]
    original=region_study.record(task,arm,0,audit=True)
    if role=='multi':
        inquiry=read(earlier/'intake.json')
        selection=read(earlier/'operator.json')
    else:
        review=read(parent/'self/v1/review.json')
        inquiry=dict(questions=review['questions'],calls=review['calls'][1:],reviews=review['reviewers'],
                     withheld=review['withheld'],invalid=review['status']=='invalid_output')
        selection=read(festival_mini.selection_path(task,'self',1))
    if (selection['text'],inquiry['questions'])!=(original['reply'],selection['questions']) or selection['questions']!=original['questions']:
        raise ValueError('첫 회차의 질문·답변 원문이 다릅니다.')
    intake=loop.intake_for(1,role,draft['files'],[],inquiry)
    for name in ('snapshot.json','answer.json','intake.json','operator.json'):
        if audit and not (folder/name).is_file():
            raise ValueError('첫 회차 재생 기록이 누락됐습니다.')
    freeze(folder/'intake.json',intake)
    receipt=loop.accept(folder,intake,selection['text'],'delegated_policy_card')
    freeze(folder/'operator.json',dict(ticket=intake['ticket'],selections=selection['selections']))
    original_calls=original['calls']
    prefix=[draft['author_call'],*inquiry['calls']]
    if original_calls[:len(prefix)]!=prefix:
        raise ValueError('공통 초안 또는 첫 질문 호출이 다릅니다.')
    outcome={**original,'calls':original_calls[len(prefix):]}
    first=loop.snapshot(1,draft['files'],intake,[receipt],outcome,[draft['author_call']])
    if first['calls']!=original_calls or first['sha256']!=original['sha256'] or first['status']!=original['status']:
        raise ValueError('원래 첫 회차와 다릅니다.')
    freeze(folder/'snapshot.json',first)
    return design,first,receipt


def answer(task,role,n,groups):
    config=read(CONFIG)
    if n<2 or n>config['cycles']:
        raise ValueError('추가 회차의 실제 질문에 답하세요.')
    out=root(task,role)
    with locked_output(STUDY/'runs'):
        folder=loop.directory(out,n)
        intake=read(folder/'intake.json')
        if not intake['questions'] or len(groups)!=len(intake['questions']):
            raise ValueError('질문마다 물어본 정책만 하나씩 연결하세요.')
        text=compose(task,groups)
        freeze(folder/'operator.json',dict(ticket=intake['ticket'],selections=groups))
        loop.accept(folder,intake,text,'delegated_policy_card')


def verify_receipts(task,out):
    for folder in sorted(out.glob('cycle-*')):
        path=folder/'answer.json'
        if path.exists():
            receipt=read(path)
            intake=read(folder/'intake.json')
            selection=read(folder/'operator.json')
            if (receipt['source']!='delegated_policy_card' or not intake['questions'] or
                    (receipt['ticket'],receipt['questions'])!=(intake['ticket'],intake['questions']) or
                    selection['ticket']!=intake['ticket'] or len(selection['selections'])!=len(intake['questions']) or
                    receipt['text']!=compose(task,selection['selections'])):
                raise ValueError('담당자 회신과 실제 질문 또는 고정 정책이 일치하지 않습니다.')


def conduct(task,role,port,audit=False):
    out=root(task,role)
    design,first,receipt=first_cycle(task,role,audit)
    verify_receipts(task,out)
    return loop.advance(out,design,role,2,first['files'],[receipt],read(CONFIG)['cycles'],port,audit=audit)


def run(port):
    with locked_output(STUDY/'runs'):
        config=preregister()
        with local_server(port,config['model']):
            for task in config['projects']:
                for role in config['first_cycle']:
                    result=conduct(task,role,port)
                    if 'waiting' in result:
                        print(task,role,'cycle',result['waiting'],flush=True)
                        for q in result['questions']:
                            print(' ',q['question'],flush=True)
                    else:
                        print(task,role,result['status'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    start=commands.add_parser('run')
    start.add_argument('--port',type=int,default=18770)
    reply=commands.add_parser('answer')
    reply.add_argument('cycle',type=int)
    reply.add_argument('task')
    reply.add_argument('role')
    reply.add_argument('selections',nargs='+')
    commands.add_parser('report')
    args=parser.parse_args()
    if args.action=='run':
        run(args.port)
    elif args.action=='answer':
        answer(args.task,args.role,args.cycle,[g.split(',') for g in args.selections])
    else:
        from experiments.three_cycle_report import report
        report()
