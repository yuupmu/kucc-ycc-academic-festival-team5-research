"""Describe where information was lost and which writer mechanisms actually ran."""
from pathlib import Path

from experiments import transfer100_study as s
from experiments.local_transport import read
from experiments.festival_report import write_csv
from experiments.project_review import freeze

def diagnostics():
    research=s.STUDY/'research'
    if not (research/'observations.json').exists():
        raise ValueError('최종 제출의 평가를 먼저 완료하세요.')
    records=read(research/'observations.json')
    scores={(v['task'],v['arm']):v['correct'] for v in records['by_project']}
    routing=[]
    for task in s.TASKS:
        for folder in sorted((s.root(task)/'dialogues').glob('*/cycle-*')):
            doc=read(folder/'intake.json')
            proposals=[];inactive=[]
            for rev in doc.get('reviews',[]):
                if 'analysis' in rev:
                    a=rev['analysis']
                    if a and a['owner_question'].strip():
                        (proposals if a['needed'] else inactive).append(dict(role=rev['role'],question=a['owner_question']))
                else:
                    response=rev.get('response') or {}
                    for q in response.get('questions',[]):
                        proposals.append(dict(role=rev['role'],question=q['question'] if isinstance(q,dict) else q))
            delivered={s.base.text_key(q['question']) for q in doc['questions']}
            excluded=[p for p in proposals if s.base.text_key(p['question']) not in delivered]
            routing.append(dict(task=task,group=folder.parent.name,cycle=int(folder.name.removeprefix('cycle-')),
                proposed=len(proposals),delivered=len(delivered),needed_false=len(inactive),
                not_forwarded_verbatim=len(excluded),inactive=inactive,reworded_or_omitted=excluded,withheld=doc.get('withheld',[])))
    paired=[]
    for task in s.TASKS:
        for role in ('self','multi'):
            before=role+'-regions-3';after=role+'-fidelity-3'
            for n in (1,2,3):
                old=read(s.root(task)/'cycles'/before/f'cycle-{n}/snapshot.json')
                new=read(s.root(task)/'cycles'/after/f'cycle-{n}/snapshot.json')
                application=new['writer'].get('answer_application',[])
                old_scores=next(c['metrics']['correct'] for c in records['cycles'] if (c['metrics']['task'],c['metrics']['arm'],c['metrics']['cycle'])==(task,before,n))
                new_scores=next(c['metrics']['correct'] for c in records['cycles'] if (c['metrics']['task'],c['metrics']['arm'],c['metrics']['cycle'])==(task,after,n))
                paired.append(dict(task=task,role=role,cycle=n,before=old_scores,after=new_scores,
                    same_previous_files=old['previous_sha256']==new['previous_sha256'],
                    same_natural_answers=[r['text'] for r in old['receipts']]==[r['text'] for r in new['receipts']],
                    same_questions=[r['questions'] for r in old['receipts']]==[r['questions'] for r in new['receipts']],
                    old_format=old['writer'].get('format'),new_format=new['writer'].get('format'),
                    direct_rules=sum(len(a.get('rules',[])) for a in application),
                    direct_changes=sum(len(a.get('changes',[])) for a in application),
                    unbound=sum(len(a.get('unbound',[])) for a in application),
                    same_final_files=old['files']==new['files']))
    write_csv(research/'question-routing.csv',routing)
    write_csv(research/'paired-writers.csv',paired)
    effects=[]
    for task in s.TASKS:
        initial=read(s.root(task)/'candidates/solo/final.json')
        initial_cases=[c for c in records['cases'] if (c['task'],c['arm'])==(task,'solo')]
        for arm in s.ARMS:
            if arm=='solo':
                continue
            prior=initial
            prior_cases=initial_cases
            numbers=(1,2,3) if arm in s.CYCLES else (1,)
            for n in numbers:
                if arm in s.CYCLES:
                    rec=read(s.root(task)/'cycles'/arm/f'cycle-{n}/snapshot.json')
                    current=next(c['cases'] for c in records['cycles'] if (c['metrics']['task'],c['metrics']['arm'],c['metrics']['cycle'])==(task,arm,n))
                else:
                    rec=read(s.root(task)/'candidates'/arm/'final.json')
                    current=[c for c in records['cases'] if (c['task'],c['arm'])==(task,arm)]
                old={c['id']:c for c in prior_cases}
                gained=[c for c in current if c['status']=='correct' and old[c['id']]['status']!='correct']
                lost=[c for c in current if c['status']!='correct' and old[c['id']]['status']=='correct']
                receipt=next((r for r in rec['receipts'] if r['cycle']==n),None)
                effects.append(dict(task=task,arm=arm,cycle=n,
                    questions=[q['question'] for q in receipt['questions']] if receipt else [],
                    reply=receipt['text'] if receipt else '',before_sha256=prior['sha256'],after_sha256=rec['sha256'],
                    before=sum(c['status']=='correct' for c in prior_cases),after=sum(c['status']=='correct' for c in current),
                    gained=[c['id'] for c in gained],lost=[c['id'] for c in lost],
                    improved_types=sorted({c['category'] for c in gained}),regressed_types=sorted({c['category'] for c in lost})))
                prior,prior_cases=rec,current
    write_csv(research/'dialogue-effects.csv',effects)
    freeze(research/'diagnostics-manifest.json',dict(source=s.checksum(Path(__file__)),
          evaluation=s.checksum(research/'manifest.json'),artifacts={f:s.checksum(research/f) for f in ('question-routing.csv','paired-writers.csv','dialogue-effects.csv')}))
    for row in paired:
        if row['cycle']==3:
            print(row)
if __name__=='__main__':
    diagnostics()
