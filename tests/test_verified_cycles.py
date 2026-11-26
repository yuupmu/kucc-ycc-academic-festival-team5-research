import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import candidate_cycles, verified_cycles as workflow


class VerifiedCycleTests(unittest.TestCase):
    def test_accepts_only_strict_superset_of_passing_checks(self):
        def rows(*passed):
            return [dict(passed=value) for value in passed]

        before = rows(False, False, True)
        self.assertTrue(workflow.improves(before, rows(False, True, True)))
        self.assertFalse(workflow.improves(before, rows(True, True, False)))
        self.assertFalse(workflow.improves(before, before))

    def test_customer_notice_uses_same_start_time_for_new_and_old_booking(self):
        _, _, notice, partial = workflow.specification('public')
        self.assertNotIn('10분', notice)
        self.assertEqual(set(partial), set(workflow.NOTICE_CHECKS))
        self.assertTrue(set(partial).isdisjoint(workflow.DISCLOSED_CHECKS))
        with patch.object(workflow, 'run_cases',
                          return_value=[dict(actual=True, error=None)] * len(partial)) as execute:
            rows = workflow.observe('def allow_cancel(age, until): return True', partial)
        sent = execute.call_args.args[1]
        self.assertEqual([(r['now'], r['booked_at']) for r in sent], [p[:2] for p in partial])
        self.assertEqual([r['passed'] for r in rows], [True, False, True, False])

    def test_no_revision_when_all_disclosed_checks_pass(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(workflow, 'recorded') as call:
            d = Path(temp)/'abcd'
            workflow.run_arm(d, 'abcd', 'brief', 'code', [], [dict(passed=True)], 71, 0)
            self.assertEqual(workflow.read(d/'decision.json')['selected'], 'draft')
            call.assert_not_called()

    def test_contrast_for_failed_case_only_and_no_new_policy_threshold(self):
        rows = [dict(age_seconds=age, until_start_seconds=21600, expected=expected, actual=False,
                     passed=not expected, basis='공개 안내', error=None)
                for age, expected in ((0, True), (259200, False))]
        report = workflow.contrast_report(rows)
        self.assertIn('assert allow_cancel(0, 21600) is True', report)
        self.assertIn('age_seconds만 달라', report)
        self.assertNotIn('10분', report)

    def test_transfer_inputs_are_distinct_and_only_graded_after_submission(self):
        from experiments.cancellation_transfer import transfer_checks
        checks = transfer_checks(workflow.NOTICE_CHECKS + workflow.DISCLOSED_CHECKS)
        self.assertEqual(len({c[:2] for c in checks}), 56)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, '모든 조건의 제출'):
                workflow.score_all(Path(temp), [17], repaired=True)

    def test_self_history_independent_reviews_and_lossless_handoff(self):
        for arm in ('abcd', 'self_serial'):
            calls = []

            def record(path, role, system, user, *unused):
                calls.append(user)
                if role == 'D':
                    return dict(text='{}')
                return dict(text=workflow.compact(dict(question='Q-' + role, feedback='F-' + role)))

            with patch.object(workflow, 'recorded', side_effect=record):
                packet = workflow.review_packet(Path('.'), arm, '실제 관측값', 71, 0)
            self.assertEqual('F-A' in calls[1], arm == 'self_serial')
            self.assertEqual('F-B' in calls[2], arm == 'self_serial')
            self.assertIn('실제 관측값', calls[3])
            self.assertEqual(packet['fallback_ids'], list(workflow.IDS))
            self.assertEqual(packet['verbatim_reviews']['C'], dict(question='Q-C', feedback='F-C'))


class VerifiedCandidateTests(unittest.TestCase):
    def test_best_tier_excludes_a_high_scoring_regression(self):
        observed = {k: [dict(passed=bool(n)) for n in ns] for k, ns in
                    dict(draft=[1, 0, 0, 0], A=[0, 1, 1, 1], B=[1, 1, 0, 0], C=[1, 1, 0, 0]).items()}
        self.assertEqual(candidate_cycles.contenders(observed), ['B', 'C'])
        observed['C'][2]['passed'] = True
        self.assertEqual(candidate_cycles.contenders(observed), ['C'])

    def test_no_candidate_improves_without_regression(self):
        observed = {'draft': [dict(passed=True), dict(passed=False)],
                    'A': [dict(passed=False), dict(passed=True)]}
        with tempfile.TemporaryDirectory() as temp, patch.object(candidate_cycles, 'recorded') as call:
            self.assertEqual(candidate_cycles.choose(Path(temp), 'abcd', 'brief', {}, observed, 131, 0), 'draft')
            call.assert_not_called()

    def test_d_cannot_choose_an_ineligible_candidate(self):
        observed = {'draft': [dict(passed=False)], 'B': [dict(passed=True)], 'C': [dict(passed=True)]}
        pool = {k: dict(text='def allow_cancel(a,b): return True') for k in observed}
        with tempfile.TemporaryDirectory() as temp, patch.object(candidate_cycles, 'recorded',
                                                                 return_value=dict(text='{"chosen":"A"}')):
            with self.assertRaisesRegex(ValueError, '허용된 후보'):
                candidate_cycles.choose(Path(temp), 'abcd', 'brief', pool, observed, 131, 0)

    def test_rebuild_is_shared_and_applied_only_to_unresolved_selections(self):
        good = [dict(passed=True), dict(passed=True)]
        failed = [dict(passed=True), dict(passed=False)]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for info in ('public', 'full'):
                for arm in candidate_cycles.STAGES[1:]:
                    target = out/info/'131'/arm
                    target.mkdir(parents=True)
                    checks = good if arm == 'abcd' else failed
                    workflow.save(target/'decision.json', dict(chosen='draft', observations={'draft': checks}))
            with patch.object(candidate_cycles, 'recorded', return_value=dict(text='code')) as call, \
                 patch.object(candidate_cycles, 'observe', return_value=good):
                candidate_cycles.resolve_remaining(out, [131], 0)
            self.assertEqual(call.call_count, 2)
            for info in ('public', 'full'):
                for arm in candidate_cycles.STAGES[1:]:
                    decision = workflow.read(out/info/'131'/arm/'final-decision.json')
                    self.assertEqual(decision['chosen'], 'draft' if arm == 'abcd' else 'fresh')
