"""Time fresh, paired A/B/C runs using the established local pilot protocol."""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from backend.isolated import grade_isolated
from experiments.local_baseline import BENCHMARK, IMPLEMENT, ROOT, SECONDS_ADAPTER, generate, submission_text
from experiments.monitor_pilot import FORMAT, PILOT, REVISE, SEEDS, msg, parsed_feedback, review_messages, save
from experiments.review_delivery import packet, delivery_message, confirmed_answers, enforce, submission_status


SERIES = ('7b-seconds', '14b-seconds', 'qwen3-8b-off')


def read(path):
    return json.loads(path.read_text())


def operator(questions, old_questions, old_answer, prefix):
    questions = [q.strip() for q in questions if q.strip()]
    if not questions:
        return ''
    if questions == [q.strip() for q in old_questions if q.strip()]:
        return old_answer
    pending = prefix.with_suffix('.questions.json')
    answer = prefix.with_suffix('.answer.json')
    save(pending, questions)
    print('OPERATOR', pending, flush=True)
    while not answer.exists():
        time.sleep(0.5)
    return read(answer)['answer']


def trial(series, seed, order, out, port):
    old = read(PILOT / f'{series}-{seed}.json')
    model = old['model_file']
    def call(messages, limit, fmt=None):
        response = generate(port, model, messages, seed, limit, old.get('thinking'), fmt)
        if response['model'] != model:
            raise ValueError('Loaded model does not match the request')
        return response
    def finish(label, calls, answer, started, wait, parent=None, delivery=None):
        source = submission_text(calls[-1]['text'])
        grade = grade_isolated(source + SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
        if delivery:
            first_index = delivery['first_submission_call']
            first = submission_text(calls[first_index]['text'])
            first_grade = grade if first == source else grade_isolated(first + SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
            delivery['first_submission_score'] = first_grade['score']
            repairs = calls[first_index+1:]
            delivery['repair_cost'] = dict(calls=len(repairs), elapsed_s=round(sum(c['elapsed_seconds'] for c in repairs), 2),
                                           tokens=sum(c['usage']['total_tokens'] for c in repairs))
        path = out / f'{series}-{seed}-{label}.json'
        status = submission_status(delivery['verification'][-1]) if delivery else 'submitted'
        save(path, dict(series=series, seed=seed, condition=label, calls=calls, operator_answer=answer,
                        submission=source, report=grade, phase_wall_s=time.perf_counter()-started,
                        operator_wait_s=wait, shared_draft_sha256=parent, delivery=delivery, status=status))
        print(path.name, status, grade['score'], flush=True)
        return path
    started = time.perf_counter()
    messages = old['calls'][0]['request']['messages']
    question = call(messages, 450)
    tick = time.perf_counter()
    answer = operator([question['text']], [old['calls'][0]['text']], old['operator_answer'], out/f'{series}-{seed}-A')
    wait = time.perf_counter()-tick
    messages = messages + [msg('assistant', question['text']), msg('user', (answer+'\n' if answer else '')+IMPLEMENT)]
    draft = call(messages, 1500)
    path = finish('A', [question, draft], answer, started, wait)
    base_answer = answer
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    history = messages + [msg('assistant', draft['text'])]
    for label in order:
        arm = 'self' if label == 'B' else 'monitors'
        started = time.perf_counter()
        prefix = out/f'{series}-{seed}-{label}'
        progress = prefix.with_suffix('.progress.json')
        calls = []
        for i in range(3):
            response = call(review_messages(history, arm, i, calls), 320, FORMAT)
            response['review'] = parsed_feedback(response)
            calls.append(response)
            save(progress, dict(status='reviewing', shared_draft_sha256=digest, calls=calls))
        reviews = [c['review'] for c in calls]
        tick = time.perf_counter()
        batch = packet(history, reviews)
        save(prefix.with_suffix('.reviews.json'), batch)
        replies = prefix.with_suffix('.decisions.json')
        print('OPERATOR', prefix.with_suffix('.reviews.json'), '->', replies, flush=True)
        while True:
            if replies.exists():
                try:
                    answers = read(replies)
                    sent = delivery_message(batch, answers)
                    break
                except ValueError as exc:
                    save(prefix.with_suffix('.operator-error.json'), {'error':str(exc)})
            time.sleep(0.5)
        wait = time.perf_counter()-tick
        final = REVISE + '\n검토별 원문과 담당자 결정\n' + sent
        delivery = {'operator_packet': batch, 'decisions': answers, 'first_submission_call':3}
        save(progress, dict(status='awaiting_main', calls=calls, delivery=delivery, shared_draft_sha256=digest))
        calls.append(call(history + [msg('user', final)], 1500))
        def checkpoint(checks):
            delivery['verification'] = checks
            save(progress, dict(calls=calls, delivery=delivery, shared_draft_sha256=digest))
        # Baseline answers already disclosed remain regression checks when a finding is confirmed.
        enforce(confirmed_answers(answers, base_answer), calls, call, checkpoint)
        finish(label, calls, '\n'.join(a for a in answers.values() if a), started, wait, digest, delivery)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18752)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    for idx, series in enumerate(SERIES):
        model = read(PILOT / f'{series}-17.json')['model_file']
        cmd = [str(ROOT/'var/local-models/llama-b12706/llama-server'), '--model', model, '--host', '127.0.0.1',
               '--port', str(args.port), '-c', '8192', '-np', '1', '--no-webui']
        if series == 'qwen3-8b-off':
            cmd.extend(['--reasoning-format', 'deepseek'])
        with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as server:
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError('Local model server stopped')
                    try:
                        with urlopen(f'http://127.0.0.1:{args.port}/health', timeout=1) as health:
                            if health.status == 200:
                                break
                    except OSError:
                        time.sleep(0.4)
                else:
                    raise RuntimeError('Server readiness timed out')
                for i, seed in enumerate(SEEDS):
                    trial(series, seed, 'BC' if (idx+i)%2 == 0 else 'CB', args.out, args.port)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
    save(args.out/'timing.json', {'batch_elapsed_s':time.perf_counter()-started})
