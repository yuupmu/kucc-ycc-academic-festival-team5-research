"""A paired upload replay, a paraphrase block and one fresh mixed-review topic."""
import argparse
import hashlib
import shutil
from contextlib import nullcontext
from pathlib import Path
from prepare_topics import ARCHIVE, LAB, OUT, PORT, SETTINGS
from backend.project_review import digest
from experiments import decision_ledger as ledger, ledger_pipeline as pipeline
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.project_review import freeze

MISSING = 'unmentioned'
BLOCKS = {'upload':'upload', 'reworded':'upload', 'fan':'fan'}
ARMS = ('include','exclude',MISSING)
ARCHIVAL = [ARCHIVE/'calls']
CASES = LAB/'experiments/transfer100-20261126/evaluator/cases.json'
PROTOCOL = 'design-v2.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup():
    original = {name:read(ARCHIVE/name/'input.json')['dialogue'][0]['answer']['text'] for name in ARMS}
    alt = '빈 파일은 받지 않습니다. 용량 제한은 16바이트예요.'
    idle = '두 신호가 모두 없으면 환풍기는 끕니다.'
    schedules = dict(upload=original,
        reworded=dict(include=alt+' 한도와 딱 같은 크기도 올릴 수 있어요.',
                      exclude=alt+' 한도와 딱 같은 크기는 올릴 수 없어요.',unmentioned=alt),
        fan=dict(include=idle+' 두 신호가 함께 들어오면 환풍기를 켭니다.',
                 exclude=idle+' 두 신호가 함께 들어오면 환풍기를 끕니다.',unmentioned=idle))
    private_follow = dict(upload=dict(yes='네, 허용합니다.',no='아니요, 거부합니다.'),
                          fan=dict(yes='네, 켜 주세요.',no='아니요, 꺼 주세요.'))
    freeze(OUT/'operator.json',dict(first=schedules, follow=private_follow))
    files=[Path(__file__), OUT/'assess.py', OUT/'prepare_topics.py', OUT/'upload.json', OUT/'fan.json', OUT/'operator.json',
           Path(ledger.__file__),Path(pipeline.__file__),LAB/'experiments/partial_reply.py',CASES]
    freeze(OUT/PROTOCOL,dict(model=SETTINGS['model'],seed=273, weights=read(ARCHIVE/'design.json')['weights'],
        preflight=dict(design=sha(OUT/'design.json'),result='Before any owner reply, the free-form plan placed Boolean policy names inside numeric conditions and failed both syntax checks. Its original sources and calls are retained. Use input predicates derived from the public signature, public numbers and typed quantity slots for the comparison below.'),
        baseline=sha(ARCHIVE/'received-policy-results.json'),files={str(p.relative_to(LAB)):sha(p) for p in files},
        plan='Freeze each topic agenda before sending any reply. One main model, same three watchers. No score, arm labels or owner card in synthesis. One blind pass per reply. Only pre-answer structural validation may trigger a format correction.',
        primary='Both explicit policies immediately correct with zero questions. Omission defers only the affected input and reuses exactly one atomic stored question. Fork the identical state and answer yes/no only when that question actually asks the intended decision. Each fork changes only that input and equals its corresponding direct submission.',
        blocks='Upload canonical, paraphrases (same policy), and new two-flag fan task. Test all three first replies + both follow-ups in each block; failed question targeting is a recorded failure, never a forced delivery.',
        checks='Official upload 20 inputs scored at actually received policy, separate original inclusive key, 38 controls from -2 to 33 and both million tails, integer equivalence classes for submitted comparisons. All four fan truth assignments. All submissions and receipts sealed before opening evaluator.'))


def design():
    d=read(OUT/PROTOCOL)
    if any(sha(LAB/p)!=h for p,h in d['files'].items()):
        raise ValueError('Frozen experiment or input changed')
    return d


def author(d,replay):
    def infer(path,*params):
        for cache in ARCHIVAL:
            if not path.exists() and (cache/path.name).is_file():
                shutil.copyfile(cache/path.name,path)
        return recorded(path,*params)
    return lambda role,prompt,packet,fmt,cap: call_model(OUT,d,role,prompt,packet,fmt,d['seed'],cap,PORT,
                                                       audit=replay,invoke=infer)


def agendas(ask):
    for topic in dict.fromkeys(BLOCKS.values()):
        pipeline.open_ticket(OUT/'agendas'/topic,read(OUT/(topic+'.json')),ask)
    freeze(OUT/'agenda-seal.json',dict(design=sha(OUT/PROTOCOL),
        agendas={t:sha(OUT/'agendas'/t/'agenda.json') for t in set(BLOCKS.values())}))


def get_agenda(topic):
    manifest=read(OUT/'agenda-seal.json')
    path=OUT/'agendas'/topic/'agenda.json'
    assert manifest['design']==sha(OUT/PROTOCOL) and manifest['agendas'][topic]==sha(path)
    return read(path)['agenda']


def initial(ask):
    owner=read(OUT/'operator.json')
    submissions={}
    for block,topic in BLOCKS.items():
        agenda=get_agenda(topic)
        parent=ledger.start(agenda)
        for arm in ARMS:
            folder=OUT/'runs'/block/arm/'initial'
            state=pipeline.checkpoint(folder,agenda,parent,owner['first'][block][arm],ask)
            freeze(folder/'questions.json',ledger.questions(agenda,state))
            submissions[block+'/'+arm]=[sha(folder/'seal.json'),sha(folder/'questions.json')]
    freeze(OUT/'first-seal.json',dict(agendas=sha(OUT/'agenda-seal.json'),submissions=submissions))


def follow(ask):
    first=read(OUT/'first-seal.json')
    assert first['agendas']==sha(OUT/'agenda-seal.json')
    delivery=read(OUT/'delivery.json')
    assert delivery['first']==sha(OUT/'first-seal.json')
    submissions={}
    for block,topic in BLOCKS.items():
        agenda=get_agenda(topic)
        folder=OUT/'runs'/block/MISSING
        orig=folder/'initial'
        assert first['submissions'][block+'/'+MISSING]==[sha(orig/'seal.json'),sha(orig/'questions.json')]
        parent=read(orig/'state.json')
        assert digest(parent)==read(orig/'seal.json')['state']
        line=delivery['tickets'][block]
        assert line['questions']==read(orig/'questions.json')==ledger.questions(agenda,parent)
        if not line['target_only']:
            continue
        for direction,reply in read(OUT/'operator.json')['follow'][topic].items():
            dest=folder/direction
            state=pipeline.checkpoint(dest,agenda,parent,reply,ask)
            freeze(dest/'questions.json',ledger.questions(agenda,state))
            submissions[block+'/'+direction]=dict(parent=digest(parent),seal=sha(dest/'seal.json'),questions=sha(dest/'questions.json'))
    freeze(OUT/'final-seal.json',dict(first=sha(OUT/'first-seal.json'),delivery=sha(OUT/'delivery.json'),
        forks=submissions,calls={p.stem:sha(p) for p in (OUT/'calls').glob('*.json')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['setup','agendas','initial','follow'])
    parser.add_argument('--replay',action='store_true')
    args=parser.parse_args()
    with locked_output(OUT):
        if args.phase=='setup':
            setup()
        else:
            d=design()
            if not args.replay and sha(LAB/d['model'])!=d['weights']:
                raise ValueError('Weights changed')
            with nullcontext() if args.replay else local_server(PORT,d['model']):
                {'agendas':agendas,'initial':initial,'follow':follow}[args.phase](author(d,args.replay))
