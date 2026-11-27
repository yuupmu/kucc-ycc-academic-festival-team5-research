"""Apply the supplemental matcher only to study paths that reached its new condition."""
import json
import sys
from run import OUT, MODEL, PORT, cases, prepare, receipt, local_server, locked_output, read, save, digest
from owner import key

def inventory():
    rows=[]
    for task,seed,arm,folder in cases():
        calls=read(folder/'prepared.json')['calls']
        checks=[read(OUT/'calls'/(k+'.json')) for k in calls]
        changed=False
        for c in checks:
            if c['role']=='review-duplicate-decisions':
                try:
                    v=json.loads(c['text'])
                    changed |= c['finish_reason']!='stop' or not v.get('same') or not v.get('question','').strip()
                except ValueError:
                    changed=True
        rows.append(dict(path=str(folder.relative_to(OUT)), affected=changed, before=digest(read(folder/'prepared.json')),
                         task=task,seed=seed,arm=arm))
    return rows

def main(phase):
    rows=inventory()
    save(OUT,'supplement-matrix.json',rows)
    for row in rows:
        if not row['affected']:continue
        base=OUT/row['path']
        dest=OUT/'supplement'/row['path']
        if phase=='prepare':
            prepare(dest,row['seed'],base/'handoff.json')
        else:
            turn=int(phase)
            prev=dest/('prepared.json' if turn==1 else 'turn-1/result.json')
            if prev.exists():
                status=read(prev)
                if status['questions'] and (turn!=1 or status['status']=='ready'):
                    delivery=read(dest/f'owner-{turn}.json')
                    assert delivery['questions']==status['questions']
                    receipt(dest,row['seed'],turn,delivery['reply'])

if __name__=='__main__':
    with locked_output(OUT), local_server(PORT,MODEL):
        main(sys.argv[1])
