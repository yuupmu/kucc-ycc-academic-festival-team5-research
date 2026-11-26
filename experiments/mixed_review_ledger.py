"""Create the usual mixed review and record its decision ticket before handing questions to the owner."""
import argparse
from contextlib import ExitStack
from pathlib import Path

from backend.structured_output import array, obj
from experiments.festival_protocol import MODEL, call_model
from experiments.ledger_pipeline import open_ticket
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.project_review import freeze
from experiments.scoped_transfer import BANK, STRING, VIEWS
from experiments.scoped_transfer_v2 import DRAFT, REVIEW

REVIEWERS=(MODEL,'var/local-models/google_gemma-3-4b-it-Q4_K_M.gguf','var/local-models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf')


def handoff(project,ask,base_seed=263):
    calls,questions,issues=[],[],[]
    key,draft=ask(MODEL,'main',DRAFT,project,obj({'code':STRING}),base_seed,1100)
    if not draft:
        raise ValueError('Invalid draft')
    calls.append(key)
    source=draft['code']
    compile(source,'solution.py','exec')
    for i,(model,view) in enumerate(zip(REVIEWERS,VIEWS)):
        key,resp=ask(model,'observer-'+'ABC'[i],'당신은 독립 감시자입니다. '+view+REVIEW,
                     dict(brief=project['brief'],code=source,dialogue=[]),
                     obj({'questions':array(STRING,0,1),'issue':STRING}),base_seed+10+i,1100)
        calls.append(key)
        if resp:
            questions.extend(q.strip() for q in resp['questions'] if q.strip())
            if resp['issue'].strip():
                issues.append(resp['issue'])
    return dict(brief=project['brief'],code=source,questions=list(dict.fromkeys(questions)),review=issues,calls=calls)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project')
    p.add_argument('out',type=Path)
    p.add_argument('--port',type=int,default=18984)
    p.add_argument('--seed',type=int,default=263)
    args=p.parse_args()
    path=Path(args.project)
    project=read(path if path.is_file() else BANK/(args.project+'.json'))
    with locked_output(args.out), ExitStack() as servers:
        freeze(args.out/'config.json',dict(model=MODEL,seed=args.seed+10,reader='literal-sentences-v1'))
        freeze(args.out/'project.json',project)
        current=None
        def invoke(file,role,system,user,seed,cap,port,fmt,model):
            nonlocal current
            if not file.exists() and current!=model:
                servers.close()
                servers.enter_context(local_server(port,model))
                current=model
            return recorded(file,role,system,user,seed,cap,port,fmt,model)
        def ask(model,role,prompt,packet,fmt,seed,cap):
            return call_model(args.out,{'model':model},role,prompt,packet,fmt,seed,cap,args.port,invoke=invoke)
        packet=handoff(project,ask,args.seed)
        freeze(args.out/'handoff.json',packet)
        if packet['questions']:
            agenda=open_ticket(args.out,packet,lambda role,prompt,payload,fmt,cap:
                              ask(MODEL,role,prompt,payload,fmt,args.seed+10,cap))
            print(*agenda['sent_questions'].values(),sep='\n')
        else:
            print('감시자가 담당자에게 보낼 질문을 제시하지 않았습니다.')


if __name__=='__main__':
    main()
