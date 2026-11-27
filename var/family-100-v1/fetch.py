import hashlib,json,sys,subprocess
from pathlib import Path
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor
root=Path('var/local-models')
def fetch(stem):
    repo='bartowski/'+stem+'-GGUF'
    file=stem+'-Q4_K_M.gguf'
    with urlopen(Request('https://huggingface.co/api/models/'+repo+'?blobs=true',headers={'User-Agent':'local-model-benchmark'}),timeout=40) as response:info=json.load(response)
    meta=next(x for x in info['siblings'] if x['rfilename']==file)
    digest=meta['lfs']['sha256']
    target=root/file
    part=target.with_suffix('.gguf.part')
    if not target.exists():
        url='https://huggingface.co/'+repo+'/resolve/'+info['sha']+'/'+file
        subprocess.run(['curl','-fLsS','--retry','3','-C','-','-o',str(part),url],check=True)
    path=target if target.exists() else part
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(8*1024**2):h.update(block)
    if path.stat().st_size!=meta['size'] or h.hexdigest()!=digest:raise RuntimeError('Weight checksum mismatch '+file)
    if path==part:part.rename(target)
    Path('var/family-100-v1',stem+'.json').write_text(json.dumps(dict(repo=repo,revision=info['sha'],file=file,sha256=digest,size=meta['size']),indent=2))
    print('Verified',file,meta['size'],flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(fetch,['google_gemma-3-4b-it','microsoft_Phi-4-mini-instruct']))
