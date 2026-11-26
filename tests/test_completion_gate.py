import tempfile
import threading
import unittest

from backend.decision_checks import answer_cases
from backend.engine import Conflict, Engine
from test_backend import ROOT, config, wait_for
from test_openai import FakeProvider


START = '현재 시각이 이용 시작 시각과 같거나 이후면, 정정 시간이 남아 있어도 거부합니다.'
WRONG = 'def can_cancel(now, booked_at, starts_at):\n    return starts_at >= now\n'
FIXED = WRONG.replace('>=', '>')


class GateProvider(FakeProvider):
    def __init__(self, ask=False, repair=False, monitor_checks=False):
        super().__init__()
        self.ask, self.repair, self.monitor_checks = ask, repair, monitor_checks

    def invoke(self, envelope, instruction, schema):
        state = envelope['project_state']
        if envelope['role'] == 'monitor':
            checks = answer_cases('검사 301 100 허용') if self.monitor_checks and state['code'] else []
            result = dict(decision='verify' if checks else 'continue', reason='고정 응답', checks=checks, requests=[])
        elif envelope['action'] == 'plan':
            question = dict(key='start', question='정각에도 허용합니까?', reason='경계 판정',
                            affected_tasks=['policy'], priority='normal')
            result = dict(plan=['규칙 적용'], assumptions=[], requests=[question] if self.ask else [])
        else:
            failures = (state.get('verification') or {}).get('repair', {}).get('failures', [])
            result = dict(code=FIXED if self.repair and failures else WRONG, complete=True, summary='고정 구현',
                          applied_decision_ids=[], context_decision_ids=state['required_decision_ids'], checks=[], requests=[])
        return result, dict(response_id='fixed-test', usage={})


class CompletionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(ROOT, data_dir=self.temp.name)
        self.engine.MAX_AUTONOMOUS_STEPS = 2

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def start(self, **options):
        self.engine.api_client = GateProvider(**options)
        cfg = config()
        cfg.update(mode='openai', task_id='cancellation_basic')
        return self.engine.start(cfg)['id']

    def test_three_continues_and_empty_suite_pause(self):
        run_id = self.start()
        done = wait_for(self.engine, run_id, lambda s: s['status'] == 'paused')
        self.assertEqual(done['verification']['status'], 'unverified')
        self.assertEqual(done['verification']['total'], 0)
        self.assertEqual([m['decision'] for m in done['monitors']], ['continue'] * 3)
        with self.assertRaises(Conflict):
            self.engine.test(run_id)

    def test_late_prose_request_is_delivered_answered_and_verified(self):
        release = threading.Event()
        reason = '담당자에게 이용 시작 정각에도 취소 가능한지 확인해 주세요.'
        provider = GateProvider()
        def invoke(envelope, instruction, schema):
            state = envelope['project_state']
            if envelope['role'] == 'monitor':
                stale = envelope['concept'] == '관점 1' and not state['code_version']
                if stale:
                    release.wait(6)
                return dict(reason=reason if stale else '추가 의견 없음', decision='continue', requests=[], checks=[]), {}
            result, meta = GateProvider.invoke(provider, envelope, instruction, schema)
            if envelope['action'] == 'implement':
                result['checks'] = answer_cases('검사 300 300 허용')
                if state['code'] == FIXED or (state.get('verification') or {}).get('repair', {}).get('failures'):
                    result['code'] = FIXED
            return result, meta
        provider.invoke = invoke
        self.engine.api_client = provider
        self.engine.MAX_AUTONOMOUS_STEPS = 6
        cfg = config()
        cfg.update(mode='openai', task_id='cancellation_basic')
        rid = self.engine.start(cfg)['id']
        try:
            active = wait_for(self.engine, rid, lambda s: all(m['version'] == 1 for m in s['monitors']))
            self.assertEqual(active['status'], 'running')
        finally:
            release.set()
        pending = wait_for(self.engine, rid, lambda s: s['status'] == 'waiting')
        request, = pending['requests']
        entry = next(r for r in pending['review_log'] if r['reason'] == reason)
        self.assertEqual(entry['request_ids'], [request['id']])
        self.assertEqual(request['question'], reason)
        self.assertEqual(request['observed_version'], 0)
        self.engine.answer(rid, request['id'], {'text': START})
        done = wait_for(self.engine, rid, lambda s: s['status'] == 'completed')
        self.assertEqual(done['requests'][0]['verified_version'], done['code_version'])
        sent = {r['id'] for c in done['calls'] if c['input']['action'] == 'implement'
                for r in c['input']['project_state']['pending_reviews']}
        self.assertEqual(sent, {r['id'] for r in done['review_log']})
        self.assertTrue(all(r['delivered_version'] for r in done['review_log']))
        raw = next(c for c in done['calls'] if c.get('review_id') == entry['id'])
        self.assertEqual(raw['output']['requests'], [])

    def test_distinct_questions_sharing_a_key_and_optional_note_reply(self):
        rid = self.start()
        run = wait_for(self.engine, rid, lambda s: s['status'] == 'paused')
        entry = run['review_log'][0]
        self.assertFalse(run['requests'])
        self.engine.open_review_request(rid, entry['id'])
        updated = self.engine.open_review_request(rid, entry['id'])
        self.assertEqual(len(updated['requests']), 1)
        self.assertEqual(updated['review_log'][0]['request_ids'], [updated['requests'][0]['id']])
        with self.engine.cv:
            state = self.engine._state(rid)
            items = [dict(key='policy', question=q, reason='판정 확인', affected_tasks=['policy'], priority='normal')
                     for q in ('첫 번째 조건은?', '두 번째 조건은?')]
            ids = self.engine._register_requests(state, items, 1, 1)
            self.assertEqual(len(set(ids)), 2)
            self.assertEqual(self.engine._register_requests(state, items, 2, 0), ids)

    def test_decision_is_rechecked_on_every_version(self):
        decisions = [dict(request_id='start', answer={'text':START})]
        self.assertFalse(answer_cases('이전 기준 예시: ' + START + ' 이번에는 운영자가 따로 결정합니다.'))
        self.assertEqual(answer_cases(''), [])
        first = self.engine._verify_revision(FIXED, [], 'cancellation_basic', decisions)
        second = self.engine._verify_revision(WRONG, [], 'cancellation_basic', decisions)
        self.assertTrue(first['decision_status']['start'])
        self.assertFalse(second['passed'])
        self.assertEqual(second['repair']['failures'][0]['request_id'], 'start')

    def test_current_monitor_evidence_counts_without_main_checks(self):
        done = wait_for(self.engine, self.start(monitor_checks=True), lambda s: s['status'] == 'completed')
        self.assertEqual(done['verification']['correct'], 3)
        self.assertEqual(done['verification']['status'], 'passed')

    def test_start_equality_must_pass_even_when_reported_as_context(self):
        run_id = self.start(ask=True, repair=True)
        req = wait_for(self.engine, run_id, lambda s: s['status'] == 'waiting')['requests'][0]
        self.engine.answer(run_id, req['id'], {'text': START})
        done = wait_for(self.engine, run_id, lambda s: s['status'] == 'completed')
        self.assertEqual(done['requests'][0]['verified_version'], done['code_version'])
        self.assertEqual(done['verification']['correct'], 2)
        failures = [r for c in done['calls'] if c['agent'] == 'main'
                    for r in (c['input']['project_state'].get('verification') or {}).get('repair', {}).get('failures', [])]
        self.assertTrue(any(r['request_id'] == req['id'] and r['now'] == r['starts_at']
                            and r['actual'] and not r['expected'] for r in failures))

    def test_unrecognized_answer_accepts_supplement_and_keeps_decision(self):
        run_id = self.start(ask=True)
        req = wait_for(self.engine, run_id, lambda s: s['status'] == 'waiting')['requests'][0]
        original = '오늘부터 시작 시각에는 거절해 주세요.'
        self.engine.answer(run_id, req['id'], {'text': original})
        wait_for(self.engine, run_id, lambda s: s['requests'][0]['status'] == 'needs_example')
        with self.assertRaises(ValueError):
            self.engine.answer(run_id, req['id'], {'text': '검사 300 0 거부'})
        self.engine.answer(run_id, req['id'], {'text': original + '\n검사 300 0 거부'})
        done = wait_for(self.engine, run_id, lambda s: s['status'] == 'paused')
        self.assertEqual(done['verification']['status'], 'failed')
        self.assertEqual(done['requests'][0]['status'], 'check_failed')
        self.assertEqual(len(done['decisions']), 1)
        self.assertEqual(done['verification']['results'][0]['request_id'], req['id'])
