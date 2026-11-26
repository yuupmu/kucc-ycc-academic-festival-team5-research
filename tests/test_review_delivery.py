import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.decision_checks import answer_cases
from backend.live_workflow import LiveWorkflow
from experiments.monitor_pilot import parsed_feedback
from experiments.review_delivery import delivery_message, enforce, packet, submission_status, verify
from experiments import timed_abc


LOGS = Path(__file__).resolve().parents[1] / 'experiments' / 'abc-timed-run'


def historic(series):
    record = json.loads((LOGS / f'{series}-43-C.json').read_text())
    return record, packet(record['calls'][-1]['request']['messages'][:-1], [c['review'] for c in record['calls'][:3]])


class DeliveryTests(unittest.TestCase):
    def test_paired_runner_saves_fixed_budget_score_and_only_repairs_confirmed_findings(self):
        record, _ = historic('qwen3-8b-off')
        series, seed = record['series'], record['seed']
        original = json.loads((timed_abc.PILOT / f'{series}-{seed}.json').read_text())
        responses = [c['text'] for c in original['calls']]
        for label in 'BC':
            responses.extend(c['text'] for c in record['calls'])
        responses.append(record['calls'][-1]['text'].replace('until_start_seconds < 0:', 'until_start_seconds <= 0:'))
        def generate(port, model, messages, seed, limit, thinking, fmt):
            return dict(text=responses.pop(0), model=model, request={'messages':messages},
                        elapsed_seconds=0.5, usage={'total_tokens':100})
        with tempfile.TemporaryDirectory() as tmp, patch.object(timed_abc, 'generate', generate):
            out = Path(tmp)
            for label, answer in [('B', ''), ('C', '검사 300 0 거부')]:
                (out/f'{series}-{seed}-{label}.decisions.json').write_text(json.dumps(dict(R1='', R2=answer, R3='')))
            timed_abc.trial(series, seed, 'BC', out, 0)
            b, c = [json.loads((out/f'{series}-{seed}-{label}.json').read_text()) for label in 'BC']
            self.assertEqual(b['status'], 'submitted_no_confirmed_findings')
            self.assertEqual(b['delivery']['repair_cost']['calls'], 0)
            self.assertEqual(c['status'], 'verified')
            self.assertEqual(c['delivery']['first_submission_score'], 39)
            self.assertEqual(c['report']['score'], 40)
            self.assertEqual(c['delivery']['repair_cost'], dict(calls=1, elapsed_s=0.5, tokens=100))
            self.assertEqual(c['shared_draft_sha256'], b['shared_draft_sha256'])
            self.assertFalse(responses)

    def test_blank_question_still_delivers_original_feedback_and_matching_reply(self):
        record, batch = historic('14b-seconds')
        decisions = dict(R1='검사 300 7200 허용', R2='', R3='')
        sent = json.loads(delivery_message(batch, decisions))
        self.assertTrue(all(not entry['review']['question'] for entry in sent))
        self.assertEqual([e['review'] for e in sent], [c['review'] for c in record['calls'][:3]])
        self.assertIn('이 부분을 확인해주세요', sent[0]['review']['feedback'])
        self.assertEqual(sent[0]['operator_answer'], decisions['R1'])
        for invalid in ({'R1': ''}, dict(decisions, R2=None), dict(decisions, R1='새로운 정책')):
            with self.assertRaises(ValueError):
                delivery_message(batch, invalid)
        self.assertEqual(parsed_feedback({'text':'중간에 잘린 의견'})['feedback'], '중간에 잘린 의견')

    def test_no_finding_keeps_submission_and_adds_no_checks_or_retries(self):
        record, batch = historic('7b-seconds')
        answers = dict.fromkeys(batch['reviews'], '')
        sent = json.loads(delivery_message(batch, answers))
        for entry in sent:
            routed = LiveWorkflow._route_review(dict(decision='continue', reason=entry['review']['feedback'], requests=[], checks=[]))
            self.assertEqual(routed['requests'], [])
        generate = Mock(side_effect=AssertionError('unexpected retry'))
        trace = enforce(answers, [record['calls'][-1]], generate, Mock())
        self.assertEqual(trace[0]['results'], [])
        self.assertEqual(submission_status(trace[0]), 'submitted_no_confirmed_findings')
        generate.assert_not_called()
        grace = '예약 생성 후 10분까지는 일반 취소 마감이 지나도 허용합니다.'
        self.assertTrue(all(c['expected'] for c in answer_cases(grace)))
        self.assertEqual(verify(record['submission'], {'R2':'맥락만\n고객 안내용 설명입니다.'})['results'], [])

    def test_failed_confirmed_case_is_repaired_or_stays_unresolved(self):
        record, _ = historic('qwen3-8b-off')
        answers = {'R2':'검사 300 0 거부'}
        first = record['calls'][-1]
        repair = dict(text='def allow_cancel(age_seconds, until_start_seconds):\n    return until_start_seconds > 0',
                      request=first['request'])
        generate = Mock(return_value=repair)
        trace = enforce(answers, [first], generate, Mock())
        self.assertEqual([v['status'] for v in trace], ['failed', 'verified'])
        prompt = generate.call_args.args[0][-1]['content']
        self.assertIn('[R2]', prompt)
        self.assertIn('assert allow_cancel(300, 0) is False', prompt)
        self.assertIn('실행 결과 True', prompt)
        generate = Mock(return_value=first)
        calls = [first]
        trace = enforce(answers, calls, generate, Mock(), limit=2)
        self.assertEqual(submission_status(trace[-1]), 'paused_unresolved')
        self.assertEqual(generate.call_count, 2)
        resumed = enforce(answers, calls, Mock(side_effect=AssertionError), Mock(), first_submission=0, limit=2)
        self.assertEqual(resumed, trace)
