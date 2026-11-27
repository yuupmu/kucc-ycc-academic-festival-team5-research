from pathlib import Path
import sys,hashlib
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]))
from experiments.local_transport import read
from experiments.project_review import freeze
from experiments.scoped_transfer_grade import grade
from backend.project_review import digest
protocol=read(root/'protocol.json'); tasks,arms=protocol['tasks'],protocol['arms']
seals=read(root/'sealed-all.json')
for t in tasks:
    assert seals[t]==read(root/t/'sealed-confirmation.json')
    for a in arms:
        assert hashlib.sha256((root/t/'submissions'/a/'solution.py').read_bytes()).hexdigest()==seals[t][a]
sums={a:dict(correct=0,cases=0,tokens=0,prompt_tokens=0,completion_tokens=0,calls=0,errors=0) for a in arms}
data={}; comparisons={}; confirmation={}; unique={}; questions={}
for t in tasks:
    d=root/t; grade(d); result=read(d/'scores.json')
    data[t]={}; confirmation[t]=read(d/'abc-confirmed.json')['confirmed']
    questions[t]={a:sum(len(read(f)) for f in d.glob(a+'-*-questions.json')) for a in ('self','abc')}
    for a,row in result.items():
        assert len(row['cases'])==20 and len({c['id'] for c in row['cases']})==20
        counts=dict(correct=row['correct'],cases=20,tokens=row['tokens'],calls=row['calls'],errors=sum(bool(c['error']) for c in row['cases']),prompt_tokens=0,completion_tokens=0)
        for k in read(d/(a+'.json'))['calls']:
            raw=read(d/'calls'/(k+'.json'))
            assert digest([raw['role'],raw['request']])==k
            unique[k]=raw['usage']['total_tokens']
            for typ in ('prompt_tokens','completion_tokens'): counts[typ]+=raw['usage'][typ]
        assert counts['tokens']==counts['prompt_tokens']+counts['completion_tokens']
        data[t][a]=counts
        for k,v in counts.items(): sums[a][k]+=v
    for a,b in [('solo','self'),('solo','abc'),('self','abc'),('abc','abc-confirmed'),('solo','abc-confirmed'),('self','abc-confirmed')]:
        pair=comparisons.setdefault(a+' -> '+b,dict(improved=[],lost=[]))
        for x,y in zip(result[a]['cases'],result[b]['cases']):
            assert x['id']==y['id']
            if x['correct']!=y['correct']:pair['improved' if y['correct'] else 'lost'].append(x['id'])
assert all(v['cases']==100 for v in sums.values())
freeze(root/'results.json',dict(protocol=protocol,by_task=data,totals=sums,paired=comparisons,confirmation=confirmation,questions=questions,unique_calls=len(unique),unique_tokens=sum(unique.values())))
print('TOTALS',sums,'TASKS',{t:[data[t][a]['correct'] for a in arms] for t in tasks},'CONFIRMED',confirmation)
