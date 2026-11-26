"""Check that confirmed reviewer repairs keep other executable decisions intact."""
import unittest

from backend import review_contracts
from experiments import review_patch


def reply(cycle, text, question):
    return {
        'cycle': cycle,
        'text': text,
        'questions': [{'question': question, 'proposed_by': ['A']}],
    }


def finding(situation, question):
    return {
        'role': 'A',
        'response': {
            'needs_code_fix': True,
            'questions': [{
                'situation': situation,
                'question': question,
                'outcome_a': 'True',
                'outcome_b': 'False',
            }],
        },
    }


def run_function(files, name, *args):
    names = {}
    exec(files['device.py'], names)
    return names[name](*args)


class ReviewScopedRepair(unittest.TestCase):
    def setUp(self):
        self.before = {
            'device.py': '# Calibration record\n'
                         'def open_gate(load_bytes):\n'
                         '    if load_bytes == 4096:\n'
                         '        return False\n'
                         '    return load_bytes > 4096\n'
        }
        brief = ('Implement open_gate(load_bytes) -> bool. Values start at 0. '
                 'The changeover limit is 4 KiB. Allowed means True, denied means False.')
        self.project = {'brief': brief, 'files': self.before.copy()}
        self.question = 'If load_bytes == 4096, should the gate be open?'
        self.review = finding('load_bytes == 4096', self.question)

    def ask(self, role, system, packet, schema, seed, limit):
        self.packets.append((role, packet))
        if role == 'main-rule-plan':
            scopes = [key for key, scope in packet['editable_scopes'].items()
                      if scope['kind'] == 'body' and 'load_bytes' in scope['parameters']]
            notes = {key: {'established': text, 'input': 'load_bytes', 'still_open': ''}
                     for key, text in packet['public_and_owner_sources'].items()}
            return role, {'scopes': scopes, 'notes': notes}
        if role == 'main-region-decisions':
            return role, {'applicable': True, 'regions': {
                cell: {'result': 'False', 'sources': ['P1']} for cell in packet['입력영역']
            }}
        if role in ('A', 'B', 'C', 'main-self'):
            return role, {'needs_code_fix': False, 'questions': []}
        self.fail('Unexpected model packet for the explicit predicate: ' + role)

    def revise(self, receipts, *, before=None, reviews=None):
        self.packets = []
        return review_patch.revise(
            self.project, self.before if before is None else before, receipts, 79, 'multi', self.ask,
            reviews=[self.review] if reviews is None else reviews,
            questions=receipts[-1]['questions'] if receipts else [],
        )

    def test_claim_and_previous_behavior_not_model_batch_choices_set_the_new_function(self):
        owner = reply(1, 'If load_bytes == 4096, return True.', self.question)
        owner['private_diagnostic'] = {'grader': 'must never reach the author'}
        self.review['response']['benchmark_score'] = 73
        outcome = self.revise([owner])
        actual = [run_function(outcome['files'], 'open_gate', n) for n in (1, 4095, 4096, 4097, 8384)]
        self.assertEqual(actual, [False, False, True, True, True])
        self.assertTrue(outcome['files']['device.py'].startswith('# Calibration record\n'))
        self.assertEqual(run_function(self.before, 'open_gate', 4096), False)
        protected_keys = {'grader', 'expected_output', 'test_cases', 'benchmark_score'}
        def assert_clean(item):
            if isinstance(item, dict):
                self.assertFalse(protected_keys.intersection(item))
                for value in item.values():
                    assert_clean(value)
            if isinstance(item, list):
                for value in item:
                    assert_clean(value)
        for _, packet in self.packets:
            assert_clean(packet)

    def test_invented_review_answer_never_supplies_policy(self):
        proposal = finding('load_bytes == 4096', 'If load_bytes == 4096, should we return True?')
        owner = reply(1, 'That policy is undecided.', self.question)
        outcome = self.revise([owner], reviews=[proposal])
        self.assertEqual(outcome['files'], self.before)

    def test_correcting_one_site_keeps_an_unrelated_function_and_other_file_intact(self):
        owner = reply(1, 'If load_bytes == 4096, return True.', self.question)
        unrelated = '\n\ndef badge(operator):\n    return operator.casefold()\n'
        before = {'device.py': self.before['device.py'] + unrelated, 'board.txt': 'panel v1\n'}
        self.project['files'] = before.copy()
        outcome = self.revise([owner], before=before)
        self.assertTrue(run_function(outcome['files'], 'open_gate', 4096))
        self.assertTrue(outcome['files']['device.py'].endswith(unrelated))
        self.assertEqual(outcome['files']['board.txt'], before['board.txt'])


    def test_qualified_review_keeps_preceding_side_effects(self):
        self.before['device.py'] = ('history = []\n'
                                    'def open_gate(load_bytes):\n'
                                    '    history.append(load_bytes)\n'
                                    '    return load_bytes > 4096\n')
        self.project['files'] = self.before.copy()
        owner = reply(1, 'If load_bytes == 4096, return True.', self.question)
        outcome = self.revise([owner])
        env = {}
        exec(outcome['files']['device.py'], env)
        for value in (4096, 4100):
            result = env['open_gate'](value)
            if value == 4100:
                self.assertTrue(result)
            elif not result:
                self.assertNotEqual(outcome['status'], 'reviewed_complete')
        self.assertEqual(env['history'], [4096, 4100])


    def test_last_review_gets_one_repair_without_another_owner_answer(self):
        seen = []
        self.packets = []
        def ask(role, system, packet, schema, seed, limit):
            seen.append(role)
            if role == 'A' and seen.count('A') == 1:
                return role, self.review['response']
            return self.ask(role, system, packet, schema, seed, limit)

        owner = reply(1, 'If load_bytes == 4096, return True.', self.question)
        out = review_patch.revise(self.project, self.before, [owner], 79, 'multi', ask,
                                  reviews=[], questions=[], final_round=True)
        self.assertTrue(run_function(out['files'], 'open_gate', 4096))
        self.assertTrue(run_function(out['files'], 'open_gate', 4098))
        self.assertEqual([name for name in seen if name in ('A', 'B', 'C')], ['A', 'B', 'C'] * 2)
        self.assertEqual(seen.count('main-rule-plan'), 1)
        self.assertEqual(out['calls'], seen)


    def test_unanswered_review_survives_a_silent_review_round(self):
        unknown = reply(1, 'Please check back later.', self.question)
        first = self.revise([unknown], reviews=[self.review])
        self.assertTrue(first['writer']['unresolved_findings'])
        self.packets = []
        second = review_patch.revise(self.project, self.before, [unknown], 79, 'multi', self.ask,
                                     reviews=[], questions=[], prior_writer=first['writer'])
        outstanding = second['writer']['unresolved_findings']
        self.assertTrue(any(entry['reviewer'] == 'A' and entry['situation'] == 'load_bytes == 4096'
                            for entry in outstanding))
        self.assertEqual(second['files'], self.before)
        self.assertEqual(second['status'], 'open_limit')

        owner = reply(3, 'If load_bytes == 4096, return True.', self.question)
        third = review_patch.revise(self.project, self.before, [unknown, owner], 79, 'multi', self.ask,
                                    questions=owner['questions'], prior_writer=second['writer'])
        self.assertTrue(run_function(third['files'], 'open_gate', 4096))
        self.assertFalse(third['writer']['unresolved_findings'])

    def test_fresh_normal_runner_passes_each_prior_review_and_answer_to_the_scoped_writer(self):
        from contextlib import nullcontext
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from experiments import repeated_intervention as loop
        from experiments.local_transport import read

        calls = []
        q = {'question': self.question, 'proposed_by': ['A']}
        owner_text = 'If load_bytes == 4096, return True.'
        def inquiry(project, files, role, seed, ask, receipts):
            return dict(questions=[] if receipts else [q], reviews=[], calls=['inspect'], invalid=False)

        def revision(project, previous, receipts, seed, role, ask, **kwargs):
            calls.append((receipts, kwargs))
            writer = {'unresolved_findings': [], 'index': len(calls)}
            return dict(files=previous, sha256=loop.base.core.digest(previous), status='open_limit',
                        reviews=[self.review], writer=writer, calls=['write'])

        draft = {'files': self.before, 'author_call': 'initial'}
        with TemporaryDirectory() as tmp, patch.object(loop, 'local_server', return_value=nullcontext()), \
             patch.object(loop.base, 'record_version', return_value=(draft, {})), \
             patch.object(loop, 'questions_for', side_effect=inquiry), \
             patch.object(review_patch, 'revise', side_effect=revision):
            out = Path(tmp) / 'run'
            waiting = loop.run(out, self.project, 'multi', 2, 79)
            self.assertEqual(waiting['waiting'], 1)
            self.assertFalse(calls)
            self.assertEqual(read(out/'design.json')['writer_version'], review_patch.VERSION)
            answer = Path(tmp) / 'reply.txt'
            answer.write_text(owner_text)
            self.assertEqual(loop.run(out, answer_file=answer, reply_to=1)['cycle'], 2)
            self.assertEqual(len(calls), 2)
            self.assertEqual([call[1]['final_round'] for call in calls], [False, True])
            self.assertEqual([call[1]['questions'] for call in calls], [[q], []])
            self.assertIsNone(calls[0][1]['prior_writer'])
            self.assertEqual(calls[1][1]['prior_writer'], read(out/'cycle-1/snapshot.json')['writer'])
            self.assertEqual(calls[1][1]['reviews'], [self.review])
            self.assertEqual([call[0][0]['text'] for call in calls], [owner_text, owner_text])



    def test_chained_scope_can_never_expand_to_the_equality_or_negative_region(self):
        cells = ['gap_seconds < 0', 'gap_seconds == 0', '0 < gap_seconds < 7200',
                 'gap_seconds == 7200', 'gap_seconds > 7200']
        axes = review_patch.answer_contracts.numeric_axes(cells)
        selected = review_patch.located_cells(
            {'situation': 'The branch with 0 < gap_seconds < 7200 returns the wrong result.'},
            axes, cells)
        self.assertEqual(selected, {'0 < gap_seconds < 7200'})
        ambiguous = review_patch.located_cells(
            {'situation': 'Investigate gap_seconds < 7200 except for VIP members.'},
            axes, cells)
        self.assertFalse(ambiguous)


    def test_non_numeric_label_patch_preserves_every_other_label_and_type(self):
        files = {'device.py': 'def dispatch(mode):\n    return "unchanged"\n'}
        self.project = {'brief': 'Choose a text label from the public mode string.', 'files': files.copy()}
        q = "When mode is 'archive', which label should be used?"
        owner = reply(1, "When mode is 'archive', return 'cold'.", q)
        issue = finding("mode == 'archive'", q)

        def ask(role, system, packet, schema, seed, limit):
            if role == 'main-rule-plan':
                body = next(k for k, scope in packet['editable_scopes'].items() if scope['kind'] == 'body')
                notes = {k: dict(established=v, input='mode', still_open='')
                         for k, v in packet['public_and_owner_sources'].items()}
                return role, {'scopes': [body], 'notes': notes}
            if role in ('A', 'B', 'C'):
                return role, dict(questions=[], needs_code_fix=False)
            self.fail('Unexpected callback ' + role)

        out = review_patch.revise(self.project, files, [owner], 11, 'multi', ask,
                                  reviews=[issue], questions=owner['questions'])
        for value, label in [('archive', 'cold'), ('active', 'unchanged'), ('Archive', 'unchanged'), (None, 'unchanged')]:
            self.assertEqual(run_function(out['files'], 'dispatch', value), label)

        withdrawal = reply(2, 'I retract my previous answer.', q)
        reopened = review_patch.revise(self.project, files, [owner, withdrawal], 11, 'multi', ask,
                                       reviews=[issue], questions=withdrawal['questions'])
        self.assertEqual(reopened['files'], files)
        self.assertNotEqual(reopened['status'], 'reviewed_complete')




class CompositePolicy(unittest.TestCase):
    # A time window for badge reissue on a different interface, with different cutoffs.
    public = 'lag_seconds는 발급 생성부터 현재까지 경과한 시간(0 이상), gap_seconds는 입장까지 남은 시간(0은 입장 순간, 음수는 이미 시작)입니다.'
    cutoff = '일반 접수 마감은 입장 2시간 전입니다.'
    anchor = '재심 시간은 발급을 생성한 때부터 셉니다.'
    duration = '재심 가능 기간은 3분입니다.'
    end = '재심 기간이 정확히 끝나는 순간도 포함합니다.'
    exception = '입장이 시작되는 순간에는 재심 기간이 남아 있어도 거부합니다.'
    effect = '재심 기간 안이면 일반 마감이 지난 요청도 접수할 수 있습니다.'
    endpoint = 'lag_seconds == 180 and 0 < gap_seconds < 7200'
    at_entry = 'lag_seconds == 180 and gap_seconds == 0'

    def resolve(self, clauses, *, reverse=False):
        polarity = '허용하면 False, 거부하면 True입니다.' if reverse else '허용하면 True, 거부하면 False입니다.'
        cells = [f'{age} and {gap}' for age in ('lag_seconds < 0', 'lag_seconds == 0',
                                                 '0 < lag_seconds < 180', 'lag_seconds == 180', 'lag_seconds > 180')
                 for gap in ('gap_seconds < 0', 'gap_seconds == 0', '0 < gap_seconds < 7200',
                             'gap_seconds == 7200', 'gap_seconds > 7200')]
        sources = {'P1': self.public, 'P2': self.cutoff, 'P3': polarity}
        sources.update({f'H{n}': text for n, text in enumerate(clauses, 1)})
        packet = {'함수': 'badge_reissue(lag_seconds, gap_seconds)', '원문': sources, '입력영역': cells,
                  '가능한결과': {k: {'동작': k, '근거': []} for k in ('True', 'False', 'defer')}}
        receipts = [reply(1, '\n'.join(clauses), '재심 기간을 어떻게 운영하나요?')]
        return review_contracts.resolve(packet, receipts, [])

    def test_owner_sentences_compose_under_a_different_interface_and_boolean_polarity(self):
        clauses = [self.anchor, self.duration, self.end, self.exception, self.effect]
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                decisions = self.resolve(clauses, reverse=reverse)
                self.assertEqual(decisions[self.endpoint]['result'], 'False' if reverse else 'True')
                self.assertEqual(decisions[self.at_entry]['result'], 'True' if reverse else 'False')
                self.assertIn('H2', decisions[self.endpoint]['sources'])
                self.assertIn('H3', decisions[self.endpoint]['sources'])
                self.assertIn('H5', decisions[self.endpoint]['sources'])

    def test_inclusion_or_duration_without_an_outcome_cannot_authorize_a_return(self):
        clauses = [self.anchor, self.duration, self.end, self.exception]
        self.assertNotIn(self.endpoint, self.resolve(clauses))
        for qualification in ('VIP 고객이면 재심 기간 안에만 접수를 허용합니다.',
                              '재심 기간 안이면 일반 마감이 지난 요청도 VIP일 때만 접수할 수 있습니다.',
                              '재심 기간 안이면 일반 마감이 지난 요청도 조회할 수 있습니다.'):
            with self.subTest(qualification=qualification):
                result = self.resolve([*clauses, qualification])
                self.assertNotIn(result.get(self.endpoint, {}).get('result'), ('True', 'False'))

    def test_conflicting_endpoints_never_silently_choose_an_inclusive_boundary(self):
        clauses = [self.anchor, self.duration, self.end, self.exception, self.effect,
                   '재심 기간이 정확히 끝나는 순간은 포함하지 않습니다.']
        decision = self.resolve(clauses).get(self.endpoint, {})
        self.assertNotEqual(decision.get('result'), 'True')


    def test_numeric_proofs_follow_packet_order_including_when_order_is_reversed(self):
        flow = ['flow_ml < 2', 'flow_ml == 2', 'flow_ml > 2']
        pressure = ['pressure_kpa < 5', 'pressure_kpa == 5', 'pressure_kpa > 5']
        grid = [f'{x} and {y}' for x in flow for y in pressure]
        # The two policies disagree in one intersection; four others have unique evidence.
        expected = {grid[0]: 'False', grid[3]: 'False', grid[7]: 'True', grid[8]: 'True'}
        sources = {'P1': 'allowed means True. denied means False.',
                   'H1': 'If flow_ml > 2, return True.', 'H2': 'If pressure_kpa < 5, return False.'}
        receipts = [reply(1, sources['H1'] + '\n' + sources['H2'], 'Which limits apply?')]
        previous = None
        order = grid[::2] + grid[1::2]
        for cells in (order, list(reversed(order))):
            packet = {'함수': 'accept(flow_ml, pressure_kpa)', '원문': sources, '입력영역': cells,
                      '가능한결과': {k: {'동작': k, '근거': []} for k in ('True', 'False', 'defer')}}
            result = review_contracts.resolve(packet, receipts)
            self.assertEqual(list(result), [key for key in cells if key in expected])
            self.assertEqual({key: entry['result'] for key, entry in result.items()}, expected)
            if previous is not None:
                self.assertEqual(result, previous)
            previous = result



