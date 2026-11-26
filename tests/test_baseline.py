import tempfile
import unittest
from pathlib import Path

from backend.engine import Engine, validate_config
from test_backend import ROOT, config, wait_for
from test_openai import FakeProvider


class BasicProvider(FakeProvider):
    def invoke(self, envelope, instruction, schema):
        assert envelope['role'] == 'main'
        assert 'requests' in schema['required']
        assert '10분' not in envelope['project_state']['task']
        if envelope['action'] == 'plan':
            result = {'plan': ['정정 시간 확인'], 'assumptions': [], 'requests': [
                {'key': 'grace', 'question': '정정 시간은 몇 분인가요?', 'reason': '마감 후 판정에 필요합니다.',
                 'affected_tasks': ['policy'], 'priority': 'normal'}]}
        else:
            result = {'code': 'def can_cancel(now, booked_at, starts_at):\n    return False\n',
                      'complete': True, 'checks': [], 'summary': '테스트용 고정 제출', 'requests': [],
                      'applied_decision_ids': [d['request_id'] for d in envelope['project_state']['decisions']],
                      'context_decision_ids': []}
        return result, {'response_id': 'test-only', 'usage': {}}


class BaselineTests(unittest.TestCase):
    def test_main_asks_then_completes_and_grades_without_reviewers(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Engine(ROOT, data_dir=temp)
            try:
                engine.api_client = BasicProvider()
                cfg = config()
                cfg.update(mode='openai', architecture='main-only', monitors=[], task_id='cancellation_basic')
                run_id = engine.start(cfg)['id']
                run = wait_for(engine, run_id, lambda s: s['status'] == 'waiting')
                self.assertEqual(run['requests'][0]['sources'], ['main'])
                engine.answer(run_id, run['requests'][0]['id'], {'text': '정정 시간은 10분입니다.\n검사 601 7200 거부'})
                run = wait_for(engine, run_id, lambda s: s['status'] == 'completed')
                self.assertFalse(run['monitors'])
                self.assertEqual({c['agent'] for c in run['calls']}, {'main'})
                self.assertEqual(run['test']['status'], 'not_run')
                engine.test(run_id)
                run = wait_for(engine, run_id, lambda s: s['test']['status'] != 'running')
                report = run['test']['report']
                self.assertEqual((report['score'], report['total'], report['accuracy_percent']), (20, 40, 50))
                self.assertEqual({v['total'] for v in report['categories'].values()}, {10})
                self.assertEqual(len({r['id'] for r in report['results']}), 40)
                self.assertTrue((Path(temp) / run_id / 'score.json').is_file())
            finally:
                engine.close()

    def test_legacy_and_mock_configurations(self):
        cfg = config()
        self.assertEqual(validate_config(cfg)['architecture'], 'main-agent-with-three-observers')
        cfg['monitors'] = []
        with self.assertRaises(ValueError):
            validate_config(cfg)
        cfg.update(mode='openai', architecture='main-agent-with-three-observers')
        with self.assertRaises(ValueError):
            validate_config(cfg)
