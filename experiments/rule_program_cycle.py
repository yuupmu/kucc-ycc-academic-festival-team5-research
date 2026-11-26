"""Owner-mediated review with a compact, source-cited writer for decision functions."""
import argparse
from pathlib import Path

from backend import anchored_program as compiler, scoped_implementation as edits
from backend.structured_output import array, obj
from experiments import festival_protocol as base, rule_intake, rule_writer
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls


PROGRAM = ('You are the main programmer implementing this decision function. Choose ordered decision rows, first matching row wins. '
           'Write short Python expressions using the actual arguments. Each row and the fallback must cite the source IDs that authorize it. '
           'The public text and the exact owner replies are authoritative. Your preliminary notes can be mistaken. The previous code supplies no policy. '
           'Order exceptions and general conditions so a broad early return cannot erase a more specific confirmed decision. An ambiguous boundary '
           'can be its own narrow row; it does not erase facts on either side. Defer only where different policies consistent with the sources '
           'would change the result. Never choose a missing priority, duration, default, exception, or label. '
           'Use exact identifiers from the literal table in expressions when available. A quantity is already converted to the argument unit. '
           'Bind it to the right input. A listed sequence supplies membership only. An ordered sequence also supplies precedence. '
           'has_present(sequence, input) tests overlap; first_present(ordered_sequence, input) returns the highest-priority present item. '
           'Usual Python boolean expressions, membership, length and sets also work. Quote string results as Python literals. '
           'The action defer takes an empty value. Omit comments and explanations. Mark complete false for any unresolved outcome. '
           'Set applicable false if this target needs effects, state changes, or other behavior outside a pure decision function.')


def same_plan(project, previous, reply, seed, ask):
    sources=rule_writer.evidence(project['brief'],reply)
    regions=edits.targets(previous,project['files'])
    public={k:{field:r[field] for field in ('path','name','parameters','kind','signature')} for k,r in regions.items()}
    params=list(dict.fromkeys(p for r in regions.values() for p in r['parameters']))
    detail=obj({'established':base.TEXT,'input':{'type':'string','enum':['none',*[p for p in params if p!='none']]},
                'still_open':base.TEXT})
    schema=obj({'scopes':array({'type':'string','enum':list(regions)},1,min(16,len(regions))),'notes':obj({k:detail for k in sources})})
    key,intent=ask('main-rule-plan',rule_writer.PLAN,{'editable_scopes':public,'public_and_owner_sources':sources},schema,seed+600,2000)
    return key,intent,sources,regions


def body_scopes(regions, selected):
    result=[]
    for k in dict.fromkeys(selected):
        if regions[k]['kind']=='body':
            result.append(k)
            continue
        bodies=[i for i,r in regions.items() if r['path']==regions[k]['path'] and r['kind']=='body']
        if len(bodies)!=1:
            return []
        result.append(bodies[0])
    return list(dict.fromkeys(result))


def write(project,previous,reply,seed,ask):
    plan_key,intent,sources,regions=same_plan(project,previous,reply,seed,ask)
    result=dict(files=previous,calls=[plan_key],decisions={},bindings={},programs=[],issues=[],error=None,complete=False)
    if intent is None:
        result['error']='invalid_model_output'
        return result
    notes=intent['notes']
    decisions={k:{**n,'status':'rule' if n['established'].strip() else 'undetermined'} for k,n in notes.items()}
    result['decisions']=decisions
    scopes=body_scopes(regions,intent['scopes'])
    def general_writer():
        native=rule_writer.write(project,previous,reply,seed,ask)
        if native['calls'][0]!=plan_key:
            raise ValueError('작성자가 같은 근거 메모를 재사용하지 않았습니다.')
        native['calls']=result['calls']+native['calls'][1:]
        native.update(programs=result['programs'],issues=result['issues'],format='native')
        return native
    if not scopes:
        return general_writer()
    patches=[]
    ready=True
    for i,k in enumerate(scopes):
        r=regions[k]
        atoms=compiler.catalogue(sources,r['parameters'])
        payload={'signature':f"{r['name']}({r['signature']})",'public_request':project['brief'],
                 'exact_owner_replies':[v for i,v in sources.items() if i.startswith('H')], 'sources':sources,
                 'my_preliminary_notes':notes,'literal_table':atoms}
        schema=compiler.program_schema(sources)
        schema['properties']['applicable']={'type':'boolean'}
        schema['required'].append('applicable')
        call,program=ask('main-rule-program',PROGRAM,payload,schema,seed+1000+i,1650)
        result['calls'].append(call)
        if program is None:
            result['error']='invalid_model_output'
            return result
        result['programs'].append({'target':k,'atoms':atoms,'decision':program})
        if not program['applicable']:
            return general_writer()
        patch,issues=compiler.compile_rows(k,r,program,sources,atoms,notes)
        result['issues'].extend(issues)
        patches.append(patch)
        ready=ready and program['complete'] and not issues and all(v['action']=='return' for v in [*program['rules'],program['otherwise']])
    try:
        files,bindings=edits.apply(previous,regions,patches,decisions)
    except (SyntaxError,ValueError,RecursionError) as exc:
        result['error']=str(exc)
        return result
    result.update(files=files,bindings=bindings,format='program',complete=bool(ready and all(
        bindings[k]['structural_support'] and not note['still_open'].strip() and note['status']=='rule' for k,note in decisions.items())))
    return result


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
        reviews.append({'role':member,'response':response})
    ready=work['complete'] and all(r['response'] and not r['response']['questions'] and not r['response']['needs_code_fix'] for r in reviews)
    status=('invalid_output' if work['error']=='invalid_model_output' or any(not r['response'] for r in reviews)
            else 'reviewed_complete' if ready else 'open_limit')
    return dict(writer=work,reviews=reviews,calls=calls,files=work['files'],sha256=base.core.digest(work['files']),status=status)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--role',choices=('solo','self','multi'))
    parser.add_argument('--seed',type=int)
    parser.add_argument('--answer-file',type=Path)
    parser.add_argument('--port',type=int,default=18769)
    args=parser.parse_args()
    out=args.out
    with locked_output(out):
        existing=read(out/'project.json') if (out/'project.json').exists() else {}
        project=read(args.project) if args.project else existing.get('project')
        base.core.validate_project(project)
        role=args.role or existing.get('role','multi')
        seed=args.seed if args.seed is not None else existing.get('seed',263)
        freeze(out/'project.json',dict(project=project,role=role,seed=seed))
        if (out/'final.json').exists():
            if args.answer_file:
                parser.error('이미 고정한 실행입니다.')
            print(read(out/'final.json')['status'])
            return
        receipt=out/'reply.json'
        waiting=out/'questions.json'
        received=read(waiting)['questions'] if waiting.exists() else []
        if args.answer_file:
            if not received or role=='solo':
                parser.error('실제로 접수된 질문이 있어야 답변을 등록할 수 있습니다.')
            freeze(receipt,dict(questions=received,text=base.core.natural_reply(args.answer_file.read_text()),source='human'))
        if received and not receipt.exists():
            print('\n'.join(q['question'] for q in received))
            return
        with local_server(args.port,base.MODEL):
            initial=out/'initial'
            with locked_output(initial):
                arm='self' if role=='self' else 'solo'
                design=base.spec(project,seed,base.MODEL,(arm,),2)
                draft,review=base.record_version(initial,design,arm,1,None,[],args.port)
            if role=='solo':
                final=dict(files=draft['files'],sha256=draft['sha256'],status='one_shot',calls=review['calls'])
            else:
                ask=Calls(out,design,args.port)
                intake=(rule_intake.inspect(project,draft['files'],seed,ask) if role=='multi' else
                        dict(questions=review['questions'],calls=review['calls'][1:]))
                freeze(waiting,intake)
                if intake['questions'] and not receipt.exists():
                    print('\n'.join(q['question'] for q in intake['questions']))
                    return
                reply=read(receipt) if receipt.exists() else None
                if reply and reply['questions']!=intake['questions']:
                    raise ValueError('질문과 담당자 회신이 일치하지 않습니다.')
                final=revise(project,draft['files'],reply['text'] if reply else None,seed,role,ask)
                final['calls']=[draft['author_call'],*intake['calls'],*final['calls']]
            publish(out,'candidate',final['files'])
            freeze(out/'final.json',final)
            print(final['status'])


if __name__=='__main__':
    main()
