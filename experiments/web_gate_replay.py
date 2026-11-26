"""Drive the web engine with recorded submissions; never call an external provider."""
import json
import tempfile

from backend.decision_checks import answer_cases, reservation_case
from backend.engine import Engine
from experiments.local_baseline import ROOT, submission_text
from experiments.monitor_pilot import OUTPUT, PILOT, save


class RecordedProvider:
    models = ['gpt-4o-mini']

    def __init__(self, codes, question='', extra_checks=()):
        self.codes, self.question, self.extra_checks = codes, question, extra_checks
        self.position = 0

    def clear(self):
        pass

    def invoke(self, envelope, instruction, schema):
        state = envelope['project_state']
        if envelope['role'] == 'monitor':
            ask = self.question and envelope['concept'] == '감시 2' and not state['decisions']
            request = dict(key='priority', question=self.question, reason='우선순위', affected_tasks=['policy'], priority='normal')
            result = dict(decision='human' if ask else 'continue', reason='저장된 판단', checks=[], requests=[request] if ask else [])
        elif envelope['action'] == 'plan':
            result = dict(plan=['구현'], assumptions=[], requests=[])
        else:
            ids = state['required_decision_ids']
            result = dict(code=self.codes[self.position], complete=True, checks=list(self.extra_checks) if ids else [],
                          summary='저장된 제출', applied_decision_ids=ids, context_decision_ids=[], requests=[])
            if ids and self.position < len(self.codes) - 1:
                self.position += 1
        return result, dict(response_id='offline-replay', usage={})


def execute(provider, answer=''):
    cfg = dict(project={'name':'완료 경로 재현'}, mode='openai', task_id='cancellation_basic',
               mainAgent=dict(model='gpt-4o-mini', prompt='저장된 제출 재현'),
               monitors=[dict(id=i, model='gpt-4o-mini', concept=f'감시 {i}', instructions='저장된 판단 재현') for i in (1, 2, 3)])
    with tempfile.TemporaryDirectory() as tmp:
        engine = Engine(ROOT, data_dir=tmp)
        try:
            engine.api_client = provider
            rid = engine.start(cfg)['id']
            def wait(predicate):
                with engine.cv:
                    if not engine.cv.wait_for(lambda: predicate(engine.get(rid)), timeout=30):
                        raise RuntimeError('Web engine replay timed out')
                    return engine.get(rid)
            if answer:
                run = wait(lambda s: s['status'] == 'waiting')
                engine.answer(rid, run['requests'][0]['id'], {'text':answer})
            run = wait(lambda s: s['status'] in ('completed', 'paused'))
            if run['status'] == 'completed':
                engine.test(rid)
                run = wait(lambda s: s['test']['status'] != 'running')
            versions = [c['input']['project_state']['verification'] for c in run['calls']
                        if c['agent'] == 'main' and c['input']['project_state'].get('verification')]
            return dict(status=run['status'], pause_reason=run.get('pause_reason'), verification=run['verification'],
                        versions=[dict(version=v['code_version'], correct=v['correct'], total=v['total']) for v in versions],
                        requests=run['requests'], monitors=run['monitors'], hidden_score=(run['test'].get('report') or {}).get('score'))
        finally:
            engine.close()


if __name__ == '__main__':
    directory = OUTPUT / 'completion-gate'
    def read(p):
        return json.loads(p.read_text())
    empty = read(OUTPUT / 'web-completion-diagnostic.json')
    empty_after = execute(RecordedProvider([empty['code']]))
    assert empty_after['status'] == 'paused' and empty_after['verification']['status'] == 'unverified'
    save(directory / 'web-empty-after.json', empty_after)
    series = 'qwen3-8b-off'
    original = read(OUTPUT / f'{series}-monitors-43.json')
    base = read(OUTPUT / f'{series}-contract-43.json')
    gate = read(directory / f'{series}-gate-43-full.json')
    adapter = read(PILOT / f'{series}-43.json')['input_adapter']
    answer = original['operator_answer']
    # Supply the identical eight frozen public inputs through the two web check sources.
    confirmed = answer_cases(answer)
    public = [reservation_case(r['age_seconds'], r['until_start_seconds'], r['expected'] == 'allow') for r in gate['history'][0]]
    assert all(case in public for case in confirmed)
    codes = [base['submission']] + [submission_text(c['text']) for c in gate['calls']]
    replay = execute(RecordedProvider([c + adapter for c in codes], original['calls'][1]['review']['question'],
                                      [c for c in public if c not in confirmed]), answer)
    assert replay['status'] == 'completed' and replay['verification']['correct'] == 8 and replay['hidden_score'] == 40
    save(directory / 'web-qwen3-43.json', replay)
    print('empty', empty_after['status'], '0/0;', 'Qwen3', replay['status'], '8/8;', 'score', replay['hidden_score'])
