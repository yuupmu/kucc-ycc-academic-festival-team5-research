from run import OUT, read, save, digest
rows=read(OUT/'supplement-matrix.json')
seal={}
for row in rows:
    path=row['path']
    src=OUT/path
    if row['affected']:
        folder=OUT/'supplement'/path
        pre=read(folder/'prepared.json')
        status=pre['status']
        code=None
        if status in ('no_question','no_open_decisions'):
            code=read(folder/'handoff.json')['code']
        if status=='ready':
            first=read(folder/'turn-1/result.json')
            branch=folder/('turn-2' if first['questions'] else 'turn-1')
            status=read(branch/'result.json')['status']
            if status=='submitted':code=(branch/'solution.py').read_text()
        save(folder,'final.json',dict(status=status,code=code))
        src=folder
    seal[path]=digest(read(src/'final.json'))
for side in ('display','hide'):
    branch=OUT/'supplement/pilot'/side
    seal['pilot/'+side]=digest(read(branch/'seal.json'))
save(OUT,'supplement-final-seal.json',seal)
