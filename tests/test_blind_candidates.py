import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import blind_candidates as workflow


class BlindCandidateTests(unittest.TestCase):
    def test_fixed_calls_and_unfiltered_choices_without_execution(self):
        prompts = []

        def record(path, role, system, user, seed, limit, port, fmt=None):
            prompts.append((path, user, fmt))
            if role == 'D':
                return {'text': '{"chosen":"draft"}'}
            return {'text': f'def allow_cancel(a,b): return {role!r}'}

        with tempfile.TemporaryDirectory() as tmp, patch.object(workflow, 'recorded', side_effect=record), \
             patch('backend.isolated.run_cases', side_effect=AssertionError('execution before seal')):
            rows = workflow.generate_seed(Path(tmp), 131, 0, 0)
        self.assertEqual({r['arm']:len(r['calls']) for r in rows},
                         dict(direct=1, self_short=2, self_serial=5, abcd=5))
        self.assertEqual(len(prompts), 8)
        for _, _, fmt in (p for p in prompts if p[0].name == 'D.json'):
            self.assertEqual(fmt['json_schema']['schema']['properties']['chosen']['enum'], list(workflow.OPTIONS))
        self.assertTrue(all(('같은 개발자로서 앞서 작성한 후보' in user) == (path.parent.name == 'self_serial')
                            for path,user,_ in prompts if path.name in ('B.json', 'C.json')))

    def test_missing_or_altered_submissions_cannot_reach_grader(self):
        seed = 131
        rows = [dict(seed=seed,arm=a,code='source',sha256=workflow.digest('source')) for a in workflow.ARMS]
        bad_hash = [dict(r, code='changed') for r in rows]
        for invalid in (rows[:-1], rows + rows[:1], bad_hash):
            with tempfile.TemporaryDirectory() as tmp, patch('backend.isolated.grade_isolated') as grade:
                out = Path(tmp)
                workflow.save(out/'submissions.json', invalid)
                with self.assertRaises(ValueError):
                    workflow.grade_sealed(out, [seed])
                grade.assert_not_called()
