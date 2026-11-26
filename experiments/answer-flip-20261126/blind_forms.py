"""Prepare two shuffled copies with no condition, program, or evaluator label in the form."""
from pathlib import Path
import html
import json
import random
import sys
OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from experiments.local_transport import read
from experiments.project_review import freeze

def build():
    late=read(LAB/'var/reservation-family-v1/details.json')['reservation']['A-self']
    prev=read(LAB/'var/family-100-v1/previous-process.json')['trace']
    bank={r['id']:r for r in read(LAB/'experiments/transfer100-20261126/evaluator/cases.json')}
    reserve=next(r for r in read(LAB/'experiments/pipeline100/sample.json') if r['id']=='R28')
    live=read(LAB/'experiments/pipeline100/runs/reservation/live-multi/cycle-1/answer.json')
    tag=next(r for r in read(LAB/'experiments/pipeline100/research/items.json') if (r['id'],r['arm'],r['cycle'])==('R28','live-multi',1))['evidence']
    records=[]; keys=[]
    def add(public,dialogue,args,label,expected,source):
        i=len(records)+1
        records.append(dict(brief=public,dialogue=dialogue,args=args))
        keys.append(dict(id=i,sufficient=label,expected=expected,source=source))
    rb=read(LAB/'var/reservation-family-v1/public/reservation.json')['brief']
    add(rb,[(r['questions'],r['answer']) for r in late['rounds']],reserve['inputs'],late['cases']['R28']['sufficient_evidence'],reserve['expected'],'family/reservation/self/R28')
    add(rb,[([q['question'] for q in live['questions']],live['text'])],reserve['inputs'],tag=='회신 확보',reserve['expected'],'pipeline100/live-multi/round1/R28')
    selected=[('suffix-06','A-self'),('suffix-06','A-abc'),('suffix-15','A-abc'),('suffix-16','A-abc'),
              ('suffix-17','A-self'),('upload-13','A-self'),('upload-13','A-abc'),('print-10','A-abc'),
              ('mask-09','A-self'),('upload-02','A-solo')]
    for i,arm in selected:
        r=bank[i];t=r['task']
        v=prev[arm][t]
        public=read(LAB/'experiments/transfer100-20261126/public'/f'{t}.json')['brief']
        add(public,[(w['delivered'],w['answer']) for w in v['rounds']],r['args'],v['cases'][i]['sufficient'],r['expected'],f'scoped/{arm}/{i}')
    b=OUT/'blind';b.mkdir(exist_ok=True)
    freeze(b/'inputs.json',records)
    freeze(OUT/'evaluator/rating-key.json',keys)
    for reviewer,seed in [('A',16363),('B',94211)]:
        order=list(range(len(records))); random.Random(seed).shuffle(order)
        freeze(OUT/'evaluator'/('order-'+reviewer+'.json'),order)
        visible=[records[i] for i in order]
        enc=json.dumps(visible,ensure_ascii=False).replace('<','\\u003c')
        template=(OUT/'rating-form.html').read_text()
        (b/('평가자-'+reviewer+'.html')).write_text(template.replace('[[REVIEWER]]',reviewer).replace('[[ITEMS]]',enc))
    print('Blinded forms written:',len(records),'cases each')
if __name__=='__main__':build()

