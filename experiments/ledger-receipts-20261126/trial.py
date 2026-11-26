"""Replace only the owner-reply reader on the two already frozen topic agendas."""
import argparse
import hashlib
import sys
from contextlib import nullcontext
from pathlib import Path

OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
PREV=OUT.parent/'decision-ledger-20261126'
sys.path.insert(0,str(LAB))
from backend.project_review import digest
from experiments import decision_ledger as ledger, receipt_pipeline as writer
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze

ARCHIVE=OUT.parent/'mixed-upload-three-answers-writer-20261126'
CASES=LAB/'experiments/transfer100-20261126/evaluator/cases.json'
BLOCKS={'upload':'upload','reworded':'upload','fan':'fan'}
MISSING='unmentioned'
ARMS=('include','exclude',MISSING)
PORT=18984


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup():
    prior=read(PREV/'design-v3.json')
    files=[PREV/'final-seal.json',PREV/'agenda-seal.json',PREV/'operator.json',PREV/'assess.py',
           PREV/'agendas/upload/agenda.json',PREV/'agendas/fan/agenda.json',Path(writer.__file__),
           Path(ledger.__file__),Path(__file__),OUT/'assess.py',CASES]
    freeze(OUT/'design.json',dict(model=prior['model'],weights=prior['weights'],seed=prior['seed'],
        comparison='Same frozen scopes, atomic questions, public rules, implementation, proxy responses, evaluator, and fork gate. Only receipt ingestion changes. The previous raw calls omitted entire sentences and emitted a closing brace for an explicit numeric value. Both protocols are retained and graded after the last submission.',
        primary=prior['primary'],blocks=prior['blocks'],checks=prior['checks'],
        files={str(p.relative_to(LAB)):sha(p) for p in files}))
    freeze(OUT/'agenda-seal.json',dict(design=sha(OUT/'design.json'),prior=sha(PREV/'agenda-seal.json')))


def design():
    d=read(OUT/'design.json')
    assert all(sha(LAB/p)==h for p,h in d['files'].items())
    return d


def get_agenda(topic):
    ref=read(OUT/'agenda-seal.json')
    assert ref['design']==sha(OUT/'design.json') and ref['prior']==sha(PREV/'agenda-seal.json')
    path=PREV/'agendas'/topic/'agenda.json'
    assert read(PREV/'agenda-seal.json')['agendas'][topic]==sha(path)
    wrapper=read(path)
    assert digest(wrapper['agenda'])==wrapper['digest']
    return wrapper['agenda']


def initial(ask):
    first=read(PREV/'operator.json')['first']
    submissions={}
    for block,topic in BLOCKS.items():
        agenda=get_agenda(topic)
        for arm in ARMS:
            f=OUT/'runs'/block/arm/'initial'
            state=writer.checkpoint(f,agenda,ledger.start(agenda),first[block][arm],ask)
            freeze(f/'questions.json',ledger.questions(agenda,state))
            submissions[block+'/'+arm]=[sha(f/'seal.json'),sha(f/'questions.json')]
    freeze(OUT/'first-seal.json',dict(agendas=sha(OUT/'agenda-seal.json'),submissions=submissions))


def follow(ask):
    first=read(OUT/'first-seal.json')
    delivery=read(OUT/'delivery.json')
    assert first['agendas']==sha(OUT/'agenda-seal.json') and delivery['first']==sha(OUT/'first-seal.json')
    forks={}
    for block,topic in BLOCKS.items():
        agenda=get_agenda(topic)
        folder=OUT/'runs'/block/MISSING
        start=folder/'initial'
        parent=read(start/'state.json')
        q=read(start/'questions.json')
        ticket=delivery['tickets'][block]
        assert first['submissions'][block+'/'+MISSING]==[sha(start/'seal.json'),sha(start/'questions.json')]
        assert digest(parent)==read(start/'seal.json')['state']
        assert ledger.questions(agenda,parent)==q==ticket['questions']
        if not ticket['target_only']:
            continue
        for side,answer in read(PREV/'operator.json')['follow'][topic].items():
            dest=folder/side
            state=writer.checkpoint(dest,agenda,parent,answer,ask)
            freeze(dest/'questions.json',ledger.questions(agenda,state))
            forks[block+'/'+side]=dict(parent=digest(parent),seal=sha(dest/'seal.json'),questions=sha(dest/'questions.json'))
    freeze(OUT/'final-seal.json',dict(first=sha(OUT/'first-seal.json'),delivery=sha(OUT/'delivery.json'),
                                      forks=forks,calls={p.stem:sha(p) for p in (OUT/'calls').glob('*.json')}))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('phase',choices=('setup','initial','follow'))
    p.add_argument('--replay',action='store_true')
    opts=p.parse_args()
    with locked_output(OUT):
        if opts.phase=='setup':
            setup()
        else:
            d=design()
            if not opts.replay and sha(LAB/d['model'])!=d['weights']:
                raise ValueError('Weights changed')
            def ask(role,prompt,packet,fmt,cap):
                return call_model(OUT,d,role,prompt,packet,fmt,d['seed'],cap,PORT,audit=opts.replay)
            with nullcontext() if opts.replay else local_server(PORT,d['model']):
                (initial if opts.phase=='initial' else follow)(ask)
