"""Repeat the owner-mediated question, revision and review cycle on a public project."""
import argparse
from pathlib import Path

from experiments import answer_fidelity, festival_protocol as base, region_cycle, review_patch, rule_intake
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls


FOLLOW_UP = (' The previous owner replies in this request are authoritative alongside the public request. '
             'Ask only when two different rules still fit both. A mismatch between existing code and an already given '
             'answer is an implementation issue. A new unanswered situation can still justify a question.')


def directory(out, number):
    return out / f'cycle-{number}'


def owner_text(receipts):
    return '\n'.join(r['text'] for r in receipts) or None


def questions_for(project, files, role, seed, ask, receipts):
    replies=[r['text'] for r in receipts]
    if role=='multi':
        def with_history(member,system,packet,schema,call_seed,limit):
            if replies:
                packet={**packet,'prior_owner_replies':replies}
                system+=FOLLOW_UP
            return ask(member,system,packet,schema,call_seed,limit)
        return rule_intake.inspect(project,files,seed,with_history)
    if role!='self':
        raise ValueError('질문은 자체 검토 또는 독립 감시 조건에서만 생성합니다.')
    packet={'공개 요구사항':project['brief'],'담당자 답변 원문':replies,'프로젝트 파일':files}
    system=' '.join((base.SELF,base.GENERAL,base.CHECK))+(FOLLOW_UP if replies else '')
    call,response=ask('main-self',system,packet,base.review_schema(False),seed+1,base.REVIEW_LIMIT)
    evidence=base.core.sources(project['brief'],receipts)
    questions,withheld=base.collect_questions([('main-self',response)],evidence)
    return dict(questions=questions,calls=[call],reviews=[{'role':'main-self','response':response}],
                withheld=withheld,invalid=response is None)


def intake_for(number,role,previous,receipts,inquiry):
    prior=base.core.digest(previous)
    ticket=base.core.digest([number,role,prior,receipts,inquiry['questions']])
    return dict(cycle=number,role=role,previous_sha256=prior,ticket=ticket,**inquiry)


def accept(folder, intake, text, source='human'):
    if not intake['questions'] or source not in ('human','delegated_policy_card'):
        raise ValueError('실제로 전달한 질문이 있어야 담당자 답변을 접수합니다.')
    reply=dict(cycle=intake['cycle'],ticket=intake['ticket'],questions=intake['questions'],
               text=base.core.natural_reply(text),source=source)
    freeze(folder/'answer.json',reply)
    return reply


def received(folder,intake):
    path=folder/'answer.json'
    if not path.exists():
        return None
    receipt=read(path)
    return accept(folder,intake,receipt['text'],receipt['source'])


def snapshot(number,previous,intake,receipts,outcome,initial_calls=()):
    return dict(cycle=number,previous_sha256=base.core.digest(previous),sha256=outcome['sha256'],files=outcome['files'],
                ticket=intake['ticket'],received_cycles=[r['cycle'] for r in receipts],
                status='invalid_output' if intake.get('invalid') else outcome['status'],
                writer=outcome['writer'],reviews=outcome['reviews'],calls=[*initial_calls,*intake['calls'],*outcome['calls']])


def finish(out,current,audit=False):
    record={k:current[k] for k in ('cycle','status','sha256','files')}
    if audit:
        target=out/'submissions/candidate'
        exported={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
        if read(out/'final.json')!=record or exported!={k:v.encode() for k,v in current['files'].items()}:
            raise ValueError('마지막 회차와 고정한 제출 파일이 다릅니다.')
    else:
        publish(out,'candidate',current['files'])
        freeze(out/'final.json',record)
    return record


def advance(out,design,role,first,previous,receipts,total,port,*,first_inquiry=None,initial_calls=(),audit=False):
    """Return a pending window or the final snapshot. Reruns verify cached requests and immutable receipts."""
    for n in range(first,total+1):
        folder=directory(out,n)
        if not audit:
            folder.mkdir(parents=True,exist_ok=True)
        ask=Calls(folder,design,port,audit=audit)
        inquiry=(first_inquiry if n==first and first_inquiry is not None else
                 questions_for(design['project'],previous,role,design['seed'],ask,receipts))
        intake=intake_for(n,role,previous,receipts,inquiry)
        if audit and not (folder/'intake.json').is_file():
            raise ValueError('질문 원기록이 누락됐습니다.')
        freeze(folder/'intake.json',intake)
        response=received(folder,intake)
        if intake['questions'] and response is None:
            if audit:
                raise ValueError('미응답 질문이 있어 회차를 검증할 수 없습니다.')
            return {'waiting':n,'questions':intake['questions']}
        if response:
            receipts=[*receipts,response]
        if design.get('writer_version')==review_patch.VERSION:
            prior_snapshot=read(directory(out,n-1)/'snapshot.json') if n>1 else {}
            reports=[*prior_snapshot.get('reviews',[]),*inquiry.get('reviews',[])]
            outcome=review_patch.revise(design['project'],previous,receipts,design['seed'],role,ask,
                                        reviews=reports,questions=intake['questions'] if response else [],
                                        prior_writer=prior_snapshot.get('writer'),final_round=n==total)
        elif design.get('writer_version')==answer_fidelity.VERSION:
            prior=read(directory(out,n-1)/'snapshot.json')['writer'] if n>1 else None
            outcome=answer_fidelity.revise(design['project'],previous,receipts,design['seed'],role,ask,prior)
        else:
            outcome=region_cycle.revise(design['project'],previous,owner_text(receipts),design['seed'],role,ask)
        current=snapshot(n,previous,intake,receipts,outcome,initial_calls if n==first else ())
        if audit and not (folder/'snapshot.json').is_file():
            raise ValueError('회차 코드 원기록이 누락됐습니다.')
        freeze(folder/'snapshot.json',current)
        previous=current['files']
    return finish(out,current,audit)


def run(out,project=None,role=None,cycles=None,seed=None,answer_file=None,reply_to=None,port=18770):
    with locked_output(out):
        existing=read(out/'design.json') if (out/'design.json').exists() else {}
        project=project if project is not None else existing.get('project')
        base.core.validate_project(project)
        role=role or existing.get('role','multi')
        cycles=cycles if cycles is not None else existing.get('cycles',3)
        seed=seed if seed is not None else existing.get('seed',263)
        if role not in ('solo','self','multi') or type(cycles) is not int or cycles<1:
            raise ValueError('유효한 역할과 양의 회차 수를 지정하세요.')
        config=dict(project=project,role=role,cycles=cycles,seed=seed,model=base.MODEL)
        version=existing.get('writer_version') if existing else review_patch.VERSION
        if version:
            if version not in (answer_fidelity.VERSION,review_patch.VERSION):
                raise ValueError('등록되지 않은 작성기 버전입니다.')
            config['writer_version']=version
        freeze(out/'design.json',config)
        if bool(answer_file)!=(reply_to is not None):
            raise ValueError('답변 파일과 그 질문의 회차 번호를 함께 입력하세요.')
        if answer_file:
            folder=directory(out,reply_to)
            if role=='solo' or not 1<=reply_to<=cycles or not (folder/'intake.json').is_file():
                raise ValueError('해당 회차의 질문이 아직 접수되지 않았습니다.')
            accept(folder,read(folder/'intake.json'),answer_file.read_text())
        if (out/'final.json').is_file():
            return read(out/'final.json')
        for n in range(1,cycles+1):
            folder=directory(out,n)
            if (folder/'intake.json').exists() and not (folder/'answer.json').exists():
                questions=read(folder/'intake.json')['questions']
                if questions:
                    return dict(waiting=n,questions=questions)
        with local_server(port,base.MODEL):
            arm='self' if role=='self' else 'solo'
            design=base.spec(project,seed,base.MODEL,(arm,),2)
            if version:
                design['writer_version']=version
            initial=out/'initial'
            with locked_output(initial):
                draft,review=base.record_version(initial,design,arm,1,None,[],port)
            if role=='solo':
                return finish(out,dict(cycle=0,status='one_shot',sha256=draft['sha256'],files=draft['files']))
            inquiry=None
            if role=='self':
                inquiry=dict(questions=review['questions'],calls=review['calls'][1:],reviews=review['reviewers'],
                             withheld=review['withheld'],invalid=review['status']=='invalid_output')
            return advance(out,design,role,1,draft['files'],[],cycles,port,
                           first_inquiry=inquiry,initial_calls=[draft['author_call']])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--role',choices=('solo','self','multi'))
    parser.add_argument('--cycles',type=int)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--answer-file',type=Path)
    parser.add_argument('--reply-to',type=int)
    parser.add_argument('--port',type=int,default=18770)
    args=parser.parse_args()
    result=run(args.out,read(args.project) if args.project else None,args.role,args.cycles,args.seed,args.answer_file,args.reply_to,args.port)
    if 'waiting' in result:
        print(f"{result['waiting']}회차 담당자 질문")
        for question in result['questions']:
            print(question['question'])
    else:
        print(result['status'])
