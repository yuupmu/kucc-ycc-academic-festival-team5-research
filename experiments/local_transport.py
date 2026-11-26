"""Loopback model transport and replayable local records, independent of the project and its evaluator."""
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parents[1]
MODEL = 'var/local-models/Qwen3-8B-Q4_K_M.gguf'


def read(path):
    return json.loads(path.read_text())


@contextmanager
def locked_output(out):
    import fcntl  # Local model evaluation uses the macOS isolated runner.
    out.mkdir(exist_ok=True, parents=True)
    directory = os.open(out, os.O_RDONLY)
    try:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('같은 결과 폴더에서 이미 실험을 실행 중입니다.') from exc
        yield
    finally:
        os.close(directory)


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def msg(role, content):
    return {'role': role, 'content': content}


def save(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def request_body(model, messages, seed, limit, thinking=None, response_format=None):
    payload = {'model': model, 'messages': messages, 'seed': seed, 'temperature': 0.3,
               'top_p': 0.9, 'top_k': 40, 'max_tokens': limit, 'stream': False}
    if thinking is not None:
        payload['chat_template_kwargs'] = {'enable_thinking': thinking == 'on'}
    if response_format is not None:
        payload['response_format'] = response_format
    return payload


def generate(port, model, messages, seed, limit, thinking=None, response_format=None):
    payload=request_body(model,messages,seed,limit,thinking,response_format)
    request = Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                      json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    started = time.monotonic()
    with build_opener(ProxyHandler({})).open(request, timeout=240) as response:
        data = json.load(response)
    choice = data['choices'][0]
    return {'text': choice['message']['content'] or '', 'model': data.get('model'), 'usage': data.get('usage'),
            'server_timings': data.get('timings'),
            'finish_reason': choice['finish_reason'], 'elapsed_seconds': round(time.monotonic() - started, 2),
            'request': payload}


def recorded(path, role, system, user, seed, limit, port, fmt=None, model=MODEL, generator=generate):
    messages = [msg('system', system), msg('user', user)]
    if path.exists():
        record = read(path)
        old = record['request']
        if (old['messages'], old['seed'], old['model'], old['max_tokens'], old.get('response_format'), record['role']) != (
                messages, seed, model, limit, fmt, role):
            raise ValueError(f'저장된 호출과 실행 조건이 다릅니다: {path}')
        return record
    record = generator(port, model, messages, seed, limit, 'off', fmt)
    if record['model'] != model:
        raise ValueError('서버 모델이 실험 설정과 다릅니다.')
    record['role'] = role
    save(path, record)
    return record


@contextmanager
def local_server(port,model=MODEL,health_check=urlopen):
    cmd = [str(ROOT/'var/local-models/llama-b12706/llama-server'), '--model', model, '--host', '127.0.0.1',
           '--port', str(port), '-c', '8192', '-np', '1', '--no-webui', '--reasoning-format', 'deepseek']
    with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
        try:
            for _ in range(150):
                if proc.poll() is not None:
                    raise RuntimeError('Local model stopped')
                try:
                    with health_check(f'http://127.0.0.1:{port}/health', timeout=1):
                        break
                except OSError:
                    time.sleep(.4)
            else:
                raise RuntimeError('Local model unavailable')
            yield
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
