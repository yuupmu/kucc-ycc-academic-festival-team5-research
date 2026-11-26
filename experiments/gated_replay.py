"""One matched retry from frozen contract submissions. Score only after both arms finish."""
import argparse
import hashlib
import json

from backend.decision_checks import repair_feedback, verification_status
from backend.isolated import grade_isolated
from backend.live_workflow import LiveWorkflow
from experiments.contract_replay import observe
from experiments.local_baseline import BENCHMARK, generate, submission_text
from experiments.monitor_pilot import OUTPUT, PILOT, SEEDS, msg, save


def status(rows):
    return verification_status(sum(r['passed'] for r in rows), len(rows))


def retry(arm, before, old, draft, seed, port):
    prompt = '같은 요구사항과 담당자 답을 다시 검토해 필요한 분기와 경계를 수정하세요. 전체 함수를 하나의 Python 코드 블록으로 제출하세요.'
    if arm == 'gate':
        prompt += '\n' + json.dumps(repair_feedback(before), ensure_ascii=False)
    req = old['request']
    messages = req['messages'] + [msg('assistant', old['text']), msg('user', prompt)]
    response = generate(port, draft['model_file'], messages, seed, req['max_tokens'], draft.get('thinking'))
    if response['model'] != old['model'] or dict(response['request'], messages=req['messages']) != req:
        raise ValueError('The model or generation settings changed')
    return response


def run(series, port):
    directory = OUTPUT / 'completion-gate'
    directory.mkdir(exist_ok=True)
    for seed in SEEDS:
        path = OUTPUT / f'{series}-contract-{seed}.json'
        source = json.loads(path.read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        draft = json.loads((PILOT / f'{series}-{seed}.json').read_text())
        checks = [{k: r[k] for k in ('age_seconds', 'until_start_seconds', 'expected', 'rule')}
                  for r in source['draft_checks']]
        before = observe(source['submission'], checks)
        assert before == source['final_checks']
        old = source['calls'][0]
        for arm in ('control', 'gate'):
            dest = directory / f'{series}-{arm}-{seed}.json'
            if dest.exists():
                record = json.loads(dest.read_text())
                if record['source_sha256'] != digest:
                    raise ValueError('The frozen submission changed')
                continue
            record = dict(source=path.name, source_sha256=digest, arm=arm, seed=seed, before=before,
                          calls=[], submission=source['submission'])
            if status(before) != 'passed':
                response = retry(arm, before, old, draft, seed, port)
                record.update(submission=submission_text(response['text']), calls=[response])
            record['after'] = observe(record['submission'], checks)
            record['verification_status'] = status(record['after'])
            save(dest, record)
        for arm in ('control', 'gate'):
            dest = directory / f'{series}-{arm}-{seed}.json'
            record = json.loads(dest.read_text())
            if 'report' not in record:
                record['report'] = grade_isolated(record['submission'] + draft['input_adapter'], BENCHMARK, 'cancellation_basic')
                save(dest, record)
            print(series, seed, arm, record['verification_status'], record['report']['score'], flush=True)
        for arm in ('control', 'gate'):
            first = json.loads((directory / f'{series}-{arm}-{seed}.json').read_text())
            full_path = directory / f'{series}-{arm}-{seed}-full.json'
            if full_path.exists():
                record = json.loads(full_path.read_text())
                if record['source_sha256'] != digest:
                    raise ValueError('The frozen submission changed')
            else:
                record = dict(source=path.name, source_sha256=digest, arm=arm, seed=seed,
                              calls=first['calls'], history=[before], submission=first['submission'])
                if first['calls']:
                    record['history'].append(first['after'])
            # Count the frozen first submission as version one of the six-version window.
            while status(record['history'][-1]) != 'passed' and len(record['history']) < LiveWorkflow.MAX_AUTONOMOUS_STEPS:
                response = retry(arm, record['history'][-1], record['calls'][-1], draft, seed, port)
                record['calls'].append(response)
                record['submission'] = submission_text(response['text'])
                record['history'].append(observe(record['submission'], checks))
                save(full_path, record)
            record['status'] = 'completed' if status(record['history'][-1]) == 'passed' else 'paused'
            if 'report' not in record:
                record['report'] = grade_isolated(record['submission'] + draft['input_adapter'], BENCHMARK, 'cancellation_basic')
                save(full_path, record)
            print('full', series, seed, arm, record['status'], len(record['calls']), record['report']['score'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('series', choices=['7b-seconds', '14b-seconds', 'qwen3-8b-off'])
    parser.add_argument('--port', type=int, default=18751)
    args = parser.parse_args()
    run(args.series, args.port)
