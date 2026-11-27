from contextlib import ExitStack
from pathlib import Path
import sys,time
p=Path(__file__).resolve().parent;sys.path.insert(0,str(p.parents[1]))
from experiments.local_transport import local_server
models=['Qwen3.5-4B','google_gemma-3-4b-it','microsoft_Phi-4-mini-instruct']
with ExitStack() as stack:
    for i,name in enumerate(models):
        stack.enter_context(local_server(18841+i,'var/local-models/'+name+'-Q4_K_M.gguf'))
        print('Ready',name,18841+i,flush=True)
    while not (p/'stop-servers').exists():time.sleep(1)
