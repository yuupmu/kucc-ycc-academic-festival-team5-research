"""Start at a review handoff; receive one natural-language reply for the recorded ticket."""
import argparse
import hashlib
from pathlib import Path

from backend.project_review import digest
from experiments import decision_ledger as ledger
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze


def open_ticket(folder, handoff, ask):
    folder.mkdir(parents=True,exist_ok=True)
    key = digest({k:handoff[k] for k in ('brief','code','questions','review')})
    path = folder/'agenda.json'
    if path.exists():
        saved = read(path)
        if saved['handoff']!=key or digest(saved['agenda'])!=saved['digest']:
            raise ValueError('The saved agenda belongs to a different handoff')
        return saved['agenda']
    agenda = ledger.prepare(handoff['brief'],handoff['code'],handoff['questions'],handoff['review'],ask)
    freeze(path,dict(handoff=key, digest=digest(agenda), agenda=agenda))
    return agenda


def checkpoint(folder, agenda, parent, reply, ask):
    folder.mkdir(parents=True,exist_ok=True)
    ticket = digest([digest(agenda), digest(parent), reply])
    if (folder/'seal.json').exists():
        seal = read(folder/'seal.json')
        state = read(folder/'state.json')
        if (seal['ticket']!=ticket or seal['state']!=digest(state) or
            (folder/'solution.py').read_bytes()!=state['code'].encode() or seal['code']!=hashlib.sha256(state['code'].encode()).hexdigest()):
            raise ValueError('Checkpoint and receipt do not match')
        return state
    state = ledger.receive(agenda,parent,reply,ask)
    freeze(folder/'state.json',state)
    path = folder/'solution.py'
    if path.exists() and path.read_bytes()!=state['code'].encode():
        raise ValueError('Existing submitted source differs')
    if not path.exists():
        path.write_bytes(state['code'].encode())
    freeze(folder/'seal.json',dict(ticket=ticket,state=digest(state),code=hashlib.sha256(path.read_bytes()).hexdigest()))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--handoff',type=Path,help='JSON with brief, code, questions, and review')
    action.add_argument('--answer-file',type=Path)
    parser.add_argument('--turn',type=int)
    parser.add_argument('--port',type=int,default=18984)
    parser.add_argument('--seed',type=int,default=273)
    args=parser.parse_args()
    out=args.out
    with locked_output(out):
        freeze(out/'config.json',dict(model=MODEL,seed=args.seed))
        with local_server(args.port,MODEL):
            def ask(role,prompt,packet,fmt,cap):
                return call_model(out,{'model':MODEL},role,prompt,packet,fmt,args.seed,cap,args.port)
            if args.handoff:
                packet=read(args.handoff)
                agenda=open_ticket(out,packet,ask)
                print(*agenda['sent_questions'].values(),sep='\n')
                return
            if not args.turn or args.turn<1:
                parser.error('Specify the turn of the ticket being answered')
            record=read(out/'agenda.json')
            agenda=record['agenda']
            if record['digest']!=digest(agenda):
                raise ValueError('Agenda changed')
            parent=ledger.start(agenda)
            for turn in range(1,args.turn):
                prior=out/f'turn-{turn}'
                reply=read(prior/'state.json')['history'][-1]['reply']
                parent=checkpoint(prior,agenda,parent,reply,ask)
            state=checkpoint(out/f'turn-{args.turn}',agenda,parent,args.answer_file.read_text(),ask)
            print(*ledger.questions(agenda,state) or ['담당자 결정 항목이 모두 확정되었습니다.'],sep='\n')


if __name__=='__main__':
    main()
