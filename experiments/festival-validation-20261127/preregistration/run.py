"""Run frozen reviews, collect natural-language owner replies, then seal the submissions."""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from backend.project_review import digest
from experiments import decision_ledger as ledger
from experiments.festival_protocol import MODEL, call_model
from experiments.ledger_pipeline import open_ticket
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.mixed_review_ledger import handoff
from experiments.project_review import freeze
from experiments.receipt_pipeline import checkpoint

DESIGN = read(OUT / 'design.json')
PILOT = LAB.parent / 'output/reports/festival-talk-20261127/pilot'
PORT = 18992


def save(folder, name, value):
    folder.mkdir(exist_ok=True, parents=True)
    freeze(folder / name, value)


def project(t):
    meta = DESIGN[t]
    return dict(brief=meta['brief'], files={'solution.py': 'def '+meta['function']+'('+meta['signature']+') -> bool:\n    raise NotImplementedError\n'})


def cases():
    for t in ('papers','cover'):
        for seed in DESIGN['seeds']:
            for arm in DESIGN['arms']:
                yield t, seed, arm, OUT/'runs'/t/str(seed)/arm


def caller(folder, seed, log):
    def ask(model, role, prompt, packet, fmt, request_seed, cap):
        def invoke(path, *args):
            original = PILOT/'shared/calls'/path.name
            if folder.name=='pilot' and not path.exists() and original.exists():
                shutil.copyfile(original,path)
            return recorded(path,*args)
        key,val=call_model(OUT, {'model':model}, role,prompt,packet,fmt,request_seed,cap,PORT,invoke=invoke)
        log.append(key)
        return key,val
    def writer(role,prompt,packet,fmt,cap):
        return ask(MODEL,role,prompt,packet,fmt,seed+10,cap)
    return ask,writer


def prepare(folder, seed, src=None, arm=None, task=None):
    if (folder/'prepared.json').exists():
        return
    calls=[]
    ask,writer=caller(folder,seed,calls)
    if src:
        packet=read(src)
    else:
        try:
            packet=handoff(project(task),ask,seed,arm)
        except (SyntaxError,ValueError) as error:
            save(folder,'prepared.json',dict(status='draft_failed',error=str(error),calls=calls,questions=[]))
            return
    save(folder,'handoff.json',packet)
    status, questions, error='no_question', [], None
    if packet['questions']:
        try:
            agenda=open_ticket(folder,packet,writer)
            questions=list(agenda['sent_questions'].values())
            status='ready' if agenda['slots'] else 'no_open_decisions'
        except (ValueError,SyntaxError,TypeError) as exc:
            status,error='agenda_failed',str(exc)
    save(folder,'prepared.json',dict(status=status,questions=questions,error=error,calls=calls))
    print(folder.relative_to(OUT),status,flush=True)


def receipt(folder, seed, turn, answer, dest=None):
    agenda=read(folder/'agenda.json')['agenda']
    assert digest(agenda)==read(folder/'agenda.json')['digest']
    initial=ledger.start(agenda) if turn==1 else read(folder/'turn-1/state.json')
    calls=[]
    _,writer=caller(folder,seed,calls)
    dest=dest or folder/f'turn-{turn}'
    if (dest/'result.json').exists():
        return
    try:
        state=checkpoint(dest,agenda,initial,answer,writer)
        status='submitted'
        questions=ledger.questions(agenda,state)
        error=None
    except (ValueError,SyntaxError,TypeError) as exc:
        status,questions,error='edit_failed',[],str(exc)
    save(dest,'result.json',dict(status=status,questions=questions,error=error,calls=calls,answer=answer))


def prepare_all():
    prepare(OUT/'pilot',907,PILOT/'shared/handoff.json')
    # Negative control: two closely worded questions have distinct input conditions.
    control=dict(brief=DESIGN['cover']['brief'],code=project('cover')['files']['solution.py'],
                 questions=['집중 보기와 데이터 절약이 모두 켜졌을 때 큰 표지를 사용하나요?',
                            '집중 보기와 데이터 절약이 모두 꺼졌을 때 큰 표지를 사용하나요?'],review=[])
    save(OUT,'control-input.json',control)
    prepare(OUT/'control',907,OUT/'control-input.json')
    for task,seed,arm,folder in cases():
        prepare(folder,seed,arm=arm,task=task)


def seal():
    manifests={}
    for t,seed,arm,folder in cases():
        prep=read(folder/'prepared.json')
        code=None
        status=prep['status']
        if status in ('no_question','no_open_decisions'):
            code=read(folder/'handoff.json')['code']
        if status=='ready':
            first=read(folder/'turn-1/result.json')
            last=folder/('turn-2' if first['questions'] else 'turn-1')
            result=read(last/'result.json')
            status=result['status']
            if status=='submitted':
                code=(last/'solution.py').read_text()
        save(folder,'final.json',dict(status=status,code=code))
        manifests[str(folder.relative_to(OUT))]=digest(read(folder/'final.json'))
    pilot=read(OUT/'pilot/prepared.json')
    if (OUT/'pilot-delivery.json').exists() and read(OUT/'pilot-delivery.json')['qualified']:
        for side in ('display','hide'):
            branch=OUT/'pilot'/side
            result=read(branch/'result.json')
            manifests['pilot/'+side]=dict(result=digest(result),code=digest((branch/'solution.py').read_text()) if result['status']=='submitted' else None)
    manifests['pilot/prepared']=digest(pilot)
    save(OUT,'final-seal.json',manifests)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['prepare','one','two','seal'])
    phase=parser.parse_args().phase
    if phase=='seal':
        seal()
        return
    with local_server(PORT,MODEL):
        if phase=='prepare':
            prepare_all()
            return
        turn=1 if phase=='one' else 2
        if turn==1 and read(OUT/'pilot-delivery.json')['qualified']:
            for side in ('display','hide'):
                receipt(OUT/'pilot',907,1,(PILOT/(side+'.txt')).read_text().strip(),OUT/'pilot'/side)
        for t,seed,arm,folder in cases():
            previous=folder/('prepared.json' if turn==1 else 'turn-1/result.json')
            if not previous.exists():
                continue
            state=read(previous)
            if (turn==1 and state['status']!='ready') or not state['questions']:
                continue
            delivery=read(folder/f'owner-{turn}.json')
            assert delivery['questions']==state['questions']
            receipt(folder,seed,turn,delivery['reply'])


if __name__=='__main__':
    with locked_output(OUT):
        main()
