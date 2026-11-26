"""Run the fixed study with server diagnostics and bounded retry of transport interruptions."""
import argparse
import http.client
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from experiments import transfer100_study as study
from experiments.local_transport import save

@contextmanager
def logged_server(port,model):
    logs=study.STUDY/'transport'
    logs.mkdir(exist_ok=True)
    number=len(list(logs.glob('server-*.log')))+1
    log=logs/f'server-{number:03d}.log'
    cmd=[str(study.ROOT/'var/local-models/llama-b12706/llama-server'),'--model',model,'--host','127.0.0.1',
         '--port',str(port),'-c','8192','-np','1','--no-webui','--reasoning-format','deepseek']
    with log.open('wb') as output,subprocess.Popen(cmd,stdout=output,stderr=output) as proc:
        try:
            for _ in range(150):
                if proc.poll() is not None:
                    raise RuntimeError('Local model stopped')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=1):
                        break
                except OSError:
                    time.sleep(.4)
            else:
                raise RuntimeError('Local model unavailable')
            yield
        except BaseException as exc:
            save(log.with_suffix('.json'),dict(command=cmd,returncode=proc.poll(),error=type(exc).__name__,message=str(exc),usage_available=False))
            raise
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait()

def run(port):
    study.local_server=logged_server
    for attempt in range(3):
        try:
            return study.run(port)
        except (http.client.RemoteDisconnected,ConnectionError,TimeoutError,URLError) as exc:
            print('transport retry',attempt+1,type(exc).__name__,flush=True)
            if attempt==2:
                raise

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=18773)
    run(p.parse_args().port)
