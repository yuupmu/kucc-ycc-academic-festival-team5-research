"""Show the proxy the questions alone. Apply hand-coded policy labels to identical text."""
from run import OUT, DESIGN, cases, read, save

def key(task, text):
    import hashlib
    return hashlib.sha256((task+'\n'+text).encode()).hexdigest()[:12]

def collect(turn, raw=False):
    pool={}
    for task,seed,arm,folder in cases():
        file=folder/('handoff.json' if raw else 'prepared.json' if turn==1 else 'turn-1/result.json')
        if not file.exists(): continue
        for question in read(file).get('questions',[]):
            pool[key(task,question)]=(task,question)
    return pool

if __name__=='__main__':
    import sys
    turn=int(sys.argv[1])
    pool=collect(turn,'raw' in sys.argv)
    if 'apply' not in sys.argv:
        for k,(task,q) in sorted(pool.items()):
            print(k,task,q)
    else:
        labels=read(OUT/'labels.json')
        for task,seed,arm,folder in cases():
            f=folder/('prepared.json' if turn==1 else 'turn-1/result.json')
            if not f.exists():continue
            state=read(f)
            if (turn==1 and state['status']!='ready') or not state['questions']:continue
            qs=state['questions']
            meta=DESIGN[task]
            tags=list(dict.fromkeys(tag for q in qs for tag in labels[key(task,q)]))
            values=meta['by_seed'][DESIGN['seeds'].index(seed)]
            fragments=[meta['yes' if values[i] else 'no'][i] for i,tag in enumerate(meta['policies']) if tag in tags]
            # Public facts are restated only for the condition explicitly asked about.
            public={'small':'4쪽보다 얇은 원고에는 제안하지 않습니다.', 'large':'12쪽보다 두꺼운 원고에는 제안하지 않습니다.',
                    'middle':'4쪽보다 두껍고 12쪽보다 얇으면 제안합니다.',
                    'focus':'집중 보기만 켜지면 큰 표지를 사용합니다.', 'save':'데이터 절약만 켜지면 작은 표지를 사용합니다.'}
            fragments.extend(public[tag] for tag in tags if tag in public)
            reply=' '.join(fragments) or '질문하신 사항에 대해 추가로 정한 기준은 없습니다.'
            save(folder,f'owner-{turn}.json',dict(questions=qs,labels=tags,reply=reply))
