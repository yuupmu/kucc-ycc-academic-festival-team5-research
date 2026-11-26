"""Run or resume the same local author and three-reviewer protocol for a public text project."""
import argparse
import tempfile
from contextlib import ExitStack
from pathlib import Path

from backend import project_review as core
from backend import project_syntax
from backend.structured_output import decode
from experiments.local_transport import MODEL, compact, local_server, locked_output, read, recorded, request_body, save


ARMS=('self','multi')
LIMITS={'main':2200,'review':850}
MAX_VERSIONS=6


def freeze(path,value):
    if path.exists():
        if read(path)!=value:
            raise ValueError(f'기록과 재생이 다릅니다: {path}')
    else:
        save(path,value)


def prompt_fingerprint():
    return core.digest([core.AUTHOR,core.INTAKE,core.REVISE,core.VIEWS,core.CHECK,core.INTAKE_SCHEMA,
                        core.schemas({'file':''},{'P1':''})])


def setup(out,project=None,seed=None,author_model=None,review_models=None,protocol=None):
    design_file=out/'design.json'
    old=read(design_file) if design_file.exists() else {}
    project=project if project is not None else old.get('project')
    core.validate_project(project)
    main=author_model or old.get('author_model',MODEL)
    models=list(review_models or old.get('review_models',[main]*3))
    if len(models)!=3:
        raise ValueError('독립 감시자 세 명의 모델이 필요합니다.')
    protocol=protocol or old.get('protocol',core.PROTOCOL)
    if protocol not in core.PROTOCOLS:
        raise ValueError('지원하는 공통 절차 버전이 아닙니다.')
    design=dict(protocol=protocol,project=project,seed=old.get('seed',263) if seed is None else seed,
                author_model=main,review_models=models,prompts_sha256=prompt_fingerprint(),limits=LIMITS,max_versions=MAX_VERSIONS)
    if protocol==core.PROTOCOL:
        design['edit_validation']='project-file-syntax-v1'
    if not old and any(out.iterdir()):
        raise ValueError('새 실행은 빈 폴더에 기록하세요.')
    freeze(design_file,design)
    state_file=out/'state.json'
    if not state_file.exists():
        save(state_file,dict(arms={a:dict(version=0,status='running') for a in ARMS},answers=[]))
    return design,read(state_file)


def answer(out,state,arm,version,text,source='human'):
    if arm not in ARMS or source not in ('human','delegated_policy_card'):
        raise ValueError('답변 대상 또는 출처를 확인하세요.')
    text=core.natural_reply(text)
    for prior in state['answers']:
        if (prior['arm'],prior['version'])==(arm,version):
            if (prior['text'],prior['source'])!=(text,source):
                raise ValueError('기록한 답변은 바꿀 수 없습니다.')
            return
    branch=state['arms'][arm]
    if branch!={'version':version,'status':'awaiting_human'}:
        raise ValueError('현재 대기 중인 질문에 답해주세요.')
    questions=read(out/f'round-{version:03}'/arm/'review.json')['questions']
    state['answers'].append(dict(arm=arm,version=version,text=text,source=source,questions=questions))
    branch['status']='running'
    save(out/'state.json',state)


def publish(out,arm,files):
    root=out/'submissions'
    root.mkdir(exist_ok=True)
    target=root/arm
    if target.exists():
        existing={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
        if existing!={p:text.encode() for p,text in files.items()}:
            raise ValueError('보존된 제출 파일과 완료 버전이 다릅니다.')
        return
    with tempfile.TemporaryDirectory(dir=root) as staging:
        tree=Path(staging)/'files'
        for name,text in files.items():
            path=tree/name
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as handle:
                handle.write(text.encode())
        tree.rename(target)


class InvalidOutput(ValueError):
    pass


def round_record(out,design,arm,number,answers,previous,ports,audit=False,invoke=None):
    folder=out/f'round-{number:03}'
    branch=folder/arm
    calls=folder/'calls'
    if not audit:
        calls.mkdir(parents=True,exist_ok=True)
        branch.mkdir(exist_ok=True)
    def call(role,system,packet,instructions,schema,model,limit):
        path=calls/f'{role}.json'
        if audit and not path.is_file():
            raise ValueError(f'호출 기록 누락: {path}')
        fmt={'type':'json_schema','json_schema':{'name':'project_review','strict':True,'schema':schema}}
        user=compact(packet)+'\n'+instructions
        infer=invoke or recorded
        result=infer(path,role,system,user,design['seed'],limit,ports.get(model,0),fmt,model)
        if result['model']!=model:
            raise ValueError(f'실제 응답 모델과 배정이 다릅니다: {path}')
        if audit:
            messages=[dict(role='system',content=system),dict(role='user',content=user)]
            if result['request']!=request_body(model,messages,design['seed'],limit,'off',fmt):
                raise ValueError(f'모델에 전달된 전체 요청이 일치하지 않습니다: {path}')
        document=decode(result['text'],schema)
        if document is None:
            raise InvalidOutput(role)
        return document
    def artifact(name,data):
        path=branch/name
        if audit:
            if not path.is_file() or read(path)!=data:
                raise ValueError(f'회차 기록이 원문과 다릅니다: {path}')
        else:
            freeze(path,data)
    files=previous['files'] if previous else design['project']['files']
    brief=design['project']['brief']
    evidence=core.sources(brief,answers)
    packet=core.context(brief,answers,files)
    edits_schema,_=core.schemas(files,evidence)
    if previous:
        packet['자신의 직전 계획']=previous['plan']
    role=arm+'-main' if previous else 'shared-main'
    main=design['author_model']
    author=call(role,core.AUTHOR,packet,core.REVISE if previous else core.INTAKE,
                edits_schema if previous else core.INTAKE_SCHEMA,main,design['limits']['main'])
    error=None
    edits=author.get('edits',[])
    checked=design['protocol']==core.PROTOCOL
    receipt=None
    try:
        if checked:
            files,edits,receipt,error=project_syntax.transaction(files,edits,evidence,core.apply_edits)
        else:
            files=core.apply_edits(files,edits,evidence)
    except ValueError as exc:
        error=str(exc)
    if checked:
        artifact('source-check.json',receipt or {'range_error':error})
    snapshot=dict(version=number,files=files,sha256=core.digest(files),plan=author['plan'],
                  complete=author['complete'],applied_edits=edits if not error else [],edit_error=error,
                  received=[a['version'] for a in answers])
    artifact('snapshot.json',snapshot)
    _,review_schema=core.schemas(files,evidence)
    review_base=core.context(brief,answers,files)
    review_base['메인의 계획']=author['plan']
    reviews=[]
    for idx,view in enumerate(core.VIEWS):
        reviewer=arm+f'-review-{idx+1}'
        packet=dict(review_base)
        if arm=='self' and reviews:
            packet['같은 버전의 직전 자체 검토']=reviews.copy()
        system=('당신은 메인 개발자이며 지금 스스로 검토합니다. ' if arm=='self' else '당신은 독립 감시자입니다. ')+view
        model=main if arm=='self' else design['review_models'][idx]
        reviews.append(call(reviewer,system,packet,core.CHECK,review_schema,model,design['limits']['review']))
    questions,ready=core.review_decision(author,files,reviews,error)
    if receipt and 'invalid' in receipt['verified'].values():
        ready=False
    record=dict(reviews=reviews,main_questions=author['questions'],questions=questions,ready=ready)
    if checked:
        record['questions'],record['copied_statements']=core.original_statements(questions,evidence)
        questions=record['questions']
    artifact('review.json',record)
    status=('completed' if ready else 'incomplete_limit' if number==design['max_versions'] else
            'awaiting_human' if questions else 'running')
    return snapshot,status


def advance(out,design,state,ports,invoke=None):
    while any(arm['status']=='running' for arm in state['arms'].values()):
        for arm,info in state['arms'].items():
            if info['status']!='running':
                continue
            number=info['version']+1
            previous=read(out/f'round-{number-1:03}'/arm/'snapshot.json') if number>1 else None
            answers=[a for a in state['answers'] if a['arm']==arm and a['version']<number]
            try:
                snapshot,status=round_record(out,design,arm,number,answers,previous,ports,invoke=invoke)
            except InvalidOutput as exc:
                info.update(status='incomplete_output',attempted_version=number,failed_role=str(exc))
            else:
                if status=='completed':
                    freeze(out/f'round-{number:03}'/arm/'submission.json',snapshot)
                    publish(out,arm,snapshot['files'])
                info.update(version=number,status=status)
            save(out/'state.json',state)


def audit(out):
    design,state=read(out/'design.json'),read(out/'state.json')
    if design['protocol'] not in core.PROTOCOLS or design['prompts_sha256']!=prompt_fingerprint():
        raise ValueError('실행한 공통 절차의 확인값이 다릅니다.')
    core.validate_project(design['project'])
    paths=set()
    checked_answers=0
    for arm,info in state['arms'].items():
        previous=None
        for n in range(1,info['version']+1):
            answers=[a for a in state['answers'] if a['arm']==arm and a['version']<n]
            previous,status=round_record(out,design,arm,n,answers,previous,{},audit=True)
            calls=out/f'round-{n:03}'/'calls'
            paths.add(calls/('shared-main.json' if n==1 else arm+'-main.json'))
            paths.update(calls/f'{arm}-review-{i}.json' for i in range(1,4))
            receipts=[a for a in state['answers'] if (a['arm'],a['version'])==(arm,n)]
            if receipts:
                if (len(receipts)!=1 or status!='awaiting_human' or receipts[0]['source'] not in ('human','delegated_policy_card')
                        or receipts[0]['questions']!=read(calls.parent/arm/'review.json')['questions']):
                    raise ValueError('질문과 답변 수신 기록이 다릅니다.')
                core.natural_reply(receipts[0]['text'])
                checked_answers+=1
            if n==info['version'] and info['status']!='incomplete_output':
                if ('running' if receipts else status)!=info['status']:
                    raise ValueError('종료 상태가 다릅니다.')
                if status=='completed' and read(calls.parent/arm/'submission.json')!=previous:
                    raise ValueError('제출 파일이 다릅니다.')
        if info['status']=='incomplete_output':
            n=info['attempted_version']
            try:
                round_record(out,design,arm,n,[a for a in state['answers'] if a['arm']==arm and a['version']<n],previous,{},audit=True)
            except InvalidOutput as exc:
                if str(exc)!=info['failed_role']:
                    raise ValueError('미완성 모델 응답 기록이 다릅니다.')
            else:
                raise ValueError('미완성 모델 응답이 재현되지 않았습니다.')
            sequence=['shared-main' if n==1 else arm+'-main',*[f'{arm}-review-{i}' for i in range(1,4)]]
            paths.update(out/f'round-{n:03}'/'calls'/(role+'.json') for role in sequence[:sequence.index(info['failed_role'])+1])
    if paths!=set(out.glob('round-*/calls/*.json')):
        raise ValueError('기록된 전체 호출이 일치하지 않습니다.')
    if checked_answers!=len(state['answers']):
        raise ValueError('검토한 질문에 연결되지 않은 답변이 있습니다.')
    return len(paths)


def run(out,project=None,seed=None,author_model=None,review_models=None,port=18756,reply_arm=None,reply_to=None,answer_file=None):
    with locked_output(out):
        design,state=setup(out,project,seed,author_model,review_models)
        if any(x is not None for x in (reply_arm,reply_to,answer_file)):
            if None in (reply_arm,reply_to,answer_file):
                raise ValueError('답변에는 대상, 회차, 자연어 파일이 필요합니다.')
            if any(part.endswith('-research') for part in answer_file.resolve().parts):
                raise ValueError('연구자 점수 기록을 정책으로 전달할 수 없습니다.')
            answer(out,state,reply_arm,reply_to,answer_file.read_text())
        if any(a['status']=='running' for a in state['arms'].values()):
            with ExitStack() as stack:
                models=dict.fromkeys([design['author_model'],*design['review_models']])
                ports={m:port+i for i,m in enumerate(models)}
                for model,model_port in ports.items():
                    stack.enter_context(local_server(model_port,model))
                advance(out,design,state,ports)
        for arm,info in state['arms'].items():
            if info['status']=='completed':
                sealed=read(out/f"round-{info['version']:03}"/arm/'submission.json')
                publish(out,arm,sealed['files'])
            print(arm,info)
            if info['status']=='awaiting_human':
                record=read(out/f"round-{info['version']:03}"/arm/'review.json')
                for q in record['questions']:
                    print('•',q['question'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--author-model')
    parser.add_argument('--review-models',nargs=3)
    parser.add_argument('--port',type=int,default=18756)
    parser.add_argument('--reply-arm',choices=ARMS)
    parser.add_argument('--reply-to',type=int)
    parser.add_argument('--answer-file',type=Path)
    args=vars(parser.parse_args())
    if args['project']:
        args['project']=read(args['project'])
    run(**args)


if __name__=='__main__':
    main()
