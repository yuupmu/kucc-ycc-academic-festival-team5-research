"""A score-blind, single-owner clarification cycle for arbitrary public text projects."""
import argparse
from pathlib import Path

from experiments import festival_guarded as guarded, festival_protocol as base, festival_refinement as old
from experiments import rule_intake, rule_writer
from experiments.local_transport import local_server, locked_output, read, save
from experiments.project_review import freeze, publish
from experiments.rule_cycle_calls import Calls


def legacy_writer(project, previous, reply, seed, ask):
    facts = list(dict.fromkeys(s.strip() for s in (reply or '').splitlines() if s.strip()))
    schema = old.author_schema(previous,facts) if facts else old.obj({'bindings':old.array(base.TEXT,0,0),
                                                                       **base.author_schema(previous)['properties']})
    starter = project['files']
    packet = {'공개 요구사항':project['brief'],'공개 초기 파일':starter,
              '직전 작성본의 구현':{p:old.revision_view(p,c,starter[p]) for p,c in previous.items()},
              '실제 담당자 답변 원문':facts}
    calls, attempts = [], []
    for i in range(2):
        k, author = ask('main-author',old.EDIT + (old.RETRY if i else ''),packet,schema,seed+1000+i,base.AUTHOR_LIMIT)
        proposal, _, issues = old.apply_reply(previous,facts,author)
        bindings = (author or {}).get('bindings',[])
        calls.append(k)
        attempts.append({'issues':issues,'bindings':bindings})
        if not issues:
            break
    files, guard = guarded.decide(previous,proposal,facts,bindings,issues)
    return dict(files=files, review_files=proposal, calls=calls, attempts=attempts, guard=guard,
                complete=bool(author and author['complete'] and not issues and not guard['held'] and not guard['unverified']
                              and all(b['status']!='open' for b in bindings)), error=None if author else 'invalid_model_output')


def revise(project, previous, reply, seed, role, strategy, ask):
    if reply:
        base.core.natural_reply(reply)
    if role not in ('self','multi') or strategy not in ('scoped','legacy'):
        raise ValueError('지원하지 않는 역할 또는 작성 방식')
    write = rule_writer.write if strategy=='scoped' else legacy_writer
    work = write(project,previous,reply,seed,ask)
    packet = {'공개 요구사항':project['brief'],'담당자 답변 원문':[reply] if reply else [],
              '프로젝트 파일':work.get('review_files',work['files'])}
    reviews, calls = [], list(work['calls'])
    for i, member in enumerate(('main-self',) if role=='self' else base.SLOTS):
        mode = base.SELF+' '+base.GENERAL+' '+base.CHECK if role=='self' else base.WATCH+' '+base.VIEWS[i]+' '+base.CHECK+base.GROUNDED
        k, review = ask(member,mode,packet,base.review_schema(role=='multi'),seed+1001+i,base.REVIEW_LIMIT)
        calls.append(k)
        reviews.append({'role':member,'response':review})
    ready = work['complete'] and all(r['response'] and not r['response']['questions'] and not r['response']['needs_code_fix'] for r in reviews)
    status = ('invalid_output' if work['error']=='invalid_model_output' or any(not r['response'] for r in reviews) else
              'reviewed_complete' if ready else 'open_limit')
    return {'writer':work, 'reviews':reviews, 'calls':calls, 'files':work['files'], 'sha256':base.core.digest(work['files']), 'status':status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--role',choices=['solo','self','multi'])
    parser.add_argument('--seed',type=int)
    parser.add_argument('--answer-file',type=Path)
    parser.add_argument('--port',type=int,default=18769)
    args = parser.parse_args()
    with locked_output(args.out):
        start = args.out/'project.json'
        existing = read(start) if start.is_file() else {}
        project = read(args.project) if args.project else existing.get('project')
        base.core.validate_project(project)
        role = args.role or existing.get('role','multi')
        seed = args.seed if args.seed is not None else existing.get('seed',263)
        freeze(start,{'project':project,'role':role,'seed':seed})
        if (args.out/'final.json').exists():
            if args.answer_file:
                parser.error('이미 고정한 최종 코드에는 새 답변을 추가할 수 없습니다.')
            print(read(args.out/'final.json')['status'])
            return
        waiting = args.out/'questions.json'
        questions = read(waiting)['questions'] if waiting.exists() else []
        if args.answer_file and (role=='solo' or not questions):
            parser.error('실제 질문이 접수된 뒤에만 답변할 수 있습니다.')
        reply_file = args.out/'reply.json'
        if args.answer_file:
            freeze(reply_file,{'text':base.core.natural_reply(args.answer_file.read_text()),'source':'human','questions':questions})
        if questions and not reply_file.exists():
            print('\n'.join(q['question'] for q in questions))
            return
        with local_server(args.port,base.MODEL):
            initial = args.out/'initial'
            with locked_output(initial):
                design = base.spec(project,seed,base.MODEL,('self',) if role=='self' else ('solo',),2)
                draft, review = base.record_version(initial,design,'self' if role=='self' else 'solo',1,None,[],args.port)
            ask = Calls(args.out,design,args.port)
            if role=='solo':
                final = {'files':draft['files'],'sha256':draft['sha256'],'status':'one_shot','calls':review['calls']}
            else:
                intake = (rule_intake.inspect(project,draft['files'],seed,ask) if role=='multi' else
                          {'questions':review['questions'],'calls':review['calls'][1:]})
                freeze(waiting,intake)
                if intake['questions'] and not reply_file.exists():
                    print('\n'.join(q['question'] for q in intake['questions']))
                    return
                response = read(reply_file) if reply_file.exists() else None
                if response and response['questions']!=intake['questions']:
                    raise ValueError('다른 질문의 답변입니다.')
                final = revise(project,draft['files'],response['text'] if response else None,seed,role,'scoped',ask)
                final['calls'] = [draft['author_call'],*intake['calls'],*final['calls']]
            publish(args.out,'candidate',final['files'])
            freeze(args.out/'final.json',final)
            print(final['status'])


if __name__=='__main__':
    main()
