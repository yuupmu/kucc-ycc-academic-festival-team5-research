"""Local owner-mediated comparison with a bounded writer for supported decision functions."""
import argparse
from pathlib import Path

from backend import decision_regions as regions, scoped_implementation as edits
from experiments import festival_protocol as base, rule_intake, rule_program_cycle as earlier, rule_writer
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls


CHOOSE=('당신은 프로젝트의 메인 작성자입니다. 공개 원문과 실제 담당자 회신만으로 함수 동작을 구현하세요. '
        '같은 입력을 설명하는 서로 겹치지 않는 영역을 제공합니다. 각 영역 전체에 대하여 원문이 보장하는 결과를 선택하고 관련 원문 번호를 인용하세요. '
        '한 영역 안에서도 아직 가능한 정책에 따라 결과가 달라지면 defer를 고르세요. 조건식을 새로 쓰거나 미정 정책을 추측할 필요가 없습니다. '
        '경계의 정확한 순간과 양옆을 따로 읽으세요. 한 규칙이 닫힌 뒤에도 적용되는 예외가 있으면 그 정보도 사용하세요. '
        '집합에서 단 하나의 알려진 값 자체를 반환하는 선택은 그 값이 단 하나인 영역에만 쓸 수 있습니다. 원문에 주어진 순위 연산은 '
        '입력에 있는 값들 중 그 순서로 가장 앞선 값을 반환합니다. 목록만 제시된 순서는 우선순위가 아닙니다. 연산의 근거 번호도 함께 인용하세요. '
        '일반 분기 조건만으로 본래 함수 역할을 표현할 수 없을 때만 applicable을 false로 표시하세요.')


def write(project,previous,reply,seed,ask):
    key,intent,sources,targets=earlier.same_plan(project,previous,reply,seed,ask)
    work=dict(files=previous,calls=[key],decisions={},bindings={},regions=[],issues=[],error=None,complete=False)
    if intent is None:
        work['error']='invalid_model_output'
        return work
    notes=intent['notes']
    decisions={k:{**n,'status':'rule' if n['established'].strip() else 'undetermined'} for k,n in notes.items()}
    work['decisions']=decisions
    selected=earlier.body_scopes(targets,intent['scopes'])
    possible={k:regions.layout(targets[k]['parameters'],sources,notes) for k in selected}
    def normal():
        native=rule_writer.write(project,previous,reply,seed,ask)
        if native['calls'][0]!=key:
            raise ValueError('공통 규칙 메모가 다릅니다.')
        native.update(calls=work['calls']+native['calls'][1:],regions=work['regions'],format='native',issues=work['issues'])
        return native
    if not possible or not all(possible.values()):
        return normal()
    patches=[]
    exhaustive=True
    for i,(k,layout) in enumerate(possible.items()):
        cells,results,kind=layout
        packet=dict(함수=targets[k]['name']+'('+targets[k]['signature']+')',원문=sources,
                    입력영역=list(cells),가능한결과={n:{'동작':code,'근거':ids} for n,(code,ids) in results.items()})
        call,answer=ask('main-region-decisions',CHOOSE,packet,regions.form(cells,results,sources),seed+1000+i,2450)
        work['calls'].append(call)
        if answer is None:
            work['error']='invalid_model_output'
            return work
        if not answer['applicable']:
            return normal()
        patch,ledger=regions.apply_choices(k,layout,answer['regions'],sources)
        work['regions'].append(dict(scope=k,kind=kind,rows=ledger))
        work['issues'].extend(r['issue'] for r in ledger if r['issue'])
        exhaustive=exhaustive and all(r['implemented'] for r in ledger)
        patches.append(patch)
    try:
        files,bindings=edits.apply(previous,targets,patches,decisions)
    except (ValueError,SyntaxError,RecursionError) as exc:
        work['error']=str(exc)
        return work
    work.update(files=files,bindings=bindings,format='regions',complete=bool(exhaustive and all(
        n['status']=='rule' and not n['still_open'].strip() and bindings[k]['structural_support'] for k,n in decisions.items())))
    return work


def revise(project,previous,reply,seed,role,ask):
    if reply:
        base.core.natural_reply(reply)
    if role not in ('self','multi'):
        raise ValueError('자체 검토 또는 독립 감시를 선택하세요.')
    work=write(project,previous,reply,seed,ask)
    packet={'공개 요구사항':project['brief'],'담당자 답변 원문':[reply] if reply else [],'프로젝트 파일':work['files']}
    reviews,calls=[],list(work['calls'])
    for i,member in enumerate(('main-self',) if role=='self' else base.SLOTS):
        mode=base.SELF+' '+base.GENERAL+' '+base.CHECK if role=='self' else base.WATCH+' '+base.VIEWS[i]+' '+base.CHECK+base.GROUNDED
        k,response=ask(member,mode,packet,base.review_schema(role=='multi'),seed+1001+i,base.REVIEW_LIMIT)
        calls.append(k)
        reviews.append(dict(role=member,response=response))
    ready=work['complete'] and all(r['response'] and not r['response']['questions'] and not r['response']['needs_code_fix'] for r in reviews)
    status=('invalid_output' if work['error']=='invalid_model_output' or any(not r['response'] for r in reviews)
            else 'reviewed_complete' if ready else 'open_limit')
    return dict(writer=work,reviews=reviews,calls=calls,files=work['files'],sha256=base.core.digest(work['files']),status=status)


def project_run(out,project=None,role=None,seed=None,answer_file=None,port=18769):
    with locked_output(out):
        existing=read(out/'project.json') if (out/'project.json').exists() else {}
        project=project or existing.get('project')
        base.core.validate_project(project)
        role=role or existing.get('role','multi')
        seed=seed if seed is not None else existing.get('seed',263)
        freeze(out/'project.json',dict(project=project,role=role,seed=seed))
        if (out/'final.json').exists():
            if answer_file:
                raise ValueError('최종 코드를 고정한 뒤에는 같은 실행에 답변을 추가할 수 없습니다.')
            return read(out/'final.json')['status']
        waiting,receipt=out/'questions.json',out/'reply.json'
        questions=read(waiting)['questions'] if waiting.exists() else []
        if answer_file:
            if not questions or role=='solo':
                raise ValueError('실제 질문이 접수된 뒤에만 답변할 수 있습니다.')
            freeze(receipt,dict(questions=questions,text=base.core.natural_reply(answer_file.read_text()),source='human'))
        if questions and not receipt.exists():
            return '\n'.join(q['question'] for q in questions)
        with local_server(port,base.MODEL):
            initial=out/'initial'
            with locked_output(initial):
                arm='self' if role=='self' else 'solo'
                design=base.spec(project,seed,base.MODEL,(arm,),2)
                draft,review=base.record_version(initial,design,arm,1,None,[],port)
            if role=='solo':
                final=dict(files=draft['files'],sha256=draft['sha256'],status='one_shot',calls=review['calls'])
            else:
                ask=Calls(out,design,port)
                intake=(rule_intake.inspect(project,draft['files'],seed,ask) if role=='multi' else
                        dict(questions=review['questions'],calls=review['calls'][1:]))
                freeze(waiting,intake)
                if intake['questions'] and not receipt.exists():
                    return '\n'.join(q['question'] for q in intake['questions'])
                response=read(receipt) if receipt.exists() else None
                if response and response['questions']!=intake['questions']:
                    raise ValueError('실제 질문과 회신이 일치하지 않습니다.')
                final=revise(project,draft['files'],response['text'] if response else None,seed,role,ask)
                final['calls']=[draft['author_call'],*intake['calls'],*final['calls']]
            publish(out,'candidate',final['files'])
            freeze(out/'final.json',final)
            return final['status']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--role',choices=('solo','self','multi'))
    parser.add_argument('--seed',type=int)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--answer-file',type=Path)
    parser.add_argument('--port',type=int,default=18769)
    args=parser.parse_args()
    print(project_run(args.out,read(args.project) if args.project else None,args.role,args.seed,args.answer_file,args.port))
