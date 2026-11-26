import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import festival_protocol as protocol, festival_refinement as refinement, festival_guarded as guarded
from experiments.local_transport import read, recorded, request_body, save


class MatchedExperiments(unittest.TestCase):
    def test_sources_review_ownership_shared_draft_and_replay(self):
        project = {'brief': 'Choose a status for a document.', 'files': {'src/item.py': 'def item():\n    raise NotImplementedError\n'}}
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)
            design, state = protocol.setup(out, project, 14, 'test-model', ['solo', 'self', 'p2', 'p3'], 2)
            physical = []
            def invoke(path, role, system, user, seed, limit, port, fmt, model):
                def generate(_, model, messages, seed, limit, thinking, fmt):
                    request = request_body(model, messages, seed, limit, thinking, fmt)
                    payload = json.loads(messages[1]['content'])
                    self.assertEqual(set(payload), {'공개 요구사항', '담당자 답변 원문', '프로젝트 파일'})
                    physical.append(role)
                    if role == 'main-author':
                        data = {'files': project['files'], 'complete': False}
                    else:
                        q = 'Which status should apply?'
                        if 'outcome_a' in str(fmt):
                            q = {'situation': 'Unspecified status', 'outcome_a': 'open', 'outcome_b': 'closed', 'question': q}
                        data = {'questions': [q], 'needs_code_fix': False}
                    return {'model': model, 'request': request, 'text': json.dumps(data), 'finish_reason': 'stop',
                            'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}
                return recorded(path, role, system, user, seed, limit, port, fmt, model, generate)
            for arm in design['arms']:
                protocol.advance(out, design, state, arm, 0, invoke)
            self.assertEqual(physical.count('main-author'), 1)
            self.assertEqual(read(out/'solo/v1/review.json')['questions'], [])
            self.assertEqual(read(out/'self/v1/review.json')['questions'][0]['proposed_by'], ['main-self'])
            self.assertEqual(read(out/'p2/v1/review.json')['questions'][0]['proposed_by'], ['A', 'B', 'C'])
            self.assertEqual(len(read(out/'p3/v1/review.json')['questions']), 1)
            with self.assertRaises(ValueError):
                protocol.answer(out, state, 'solo', 1, 'Closed.')
            with self.assertRaises(ValueError):
                protocol.answer(out, state, 'self', 2, 'Closed.')
            with self.assertRaises(ValueError):
                protocol.answer(out, state, 'self', 1, '가채점 결과는 15점')
            protocol.answer(out, state, 'self', 1, 'Use a closed status.')
            protocol.advance(out, design, state, 'self', 0, invoke)
            protocol.answer(out, state, 'p2', 1, 'Leave the document open.')
            protocol.advance(out, design, state, 'p2', 0, invoke)
            for arm, own in [('self', 'Use a closed status.'), ('p2', 'Leave the document open.')]:
                key = read(out/arm/'v2/snapshot.json')['author_call']
                data = json.loads(read(out/'calls'/(key+'.json'))['request']['messages'][1]['content'])
                self.assertEqual(data['담당자 답변 원문'], [own])
            self.assertEqual(len(protocol.audit(out)), len(physical))
            with self.assertRaises(ValueError):
                protocol.answer(out, state, 'self', 1, 'Overwrite the record.')

    def test_refinement_requires_a_real_executable_change_or_explicit_open_decision(self):
        previous = {'f.py': 'def f():\n    return False\n'}
        facts = ['Allow it when confirmed.']
        def apply(line, status, code):
            return refinement.apply_reply(previous, facts, {'files': {'f.py': code},
                'bindings': [{'reply': facts[0], 'file': 'f.py', 'status': status, 'line': line}], 'complete': True})
        self.assertIn('claimed_change_on_unchanged_line', apply('return False', 'changed', previous['f.py'])[2])
        self.assertIn('missing_executable_line', apply('# confirmed', 'changed', previous['f.py']+'# confirmed\n')[2])
        self.assertEqual(apply('return True', 'changed', 'def f():\n    return True\n')[2], [])
        self.assertEqual(apply('', 'open', previous['f.py'])[2], [])
        self.assertEqual(apply('return False', 'present', previous['f.py'])[2], [])
        self.assertEqual(apply('return True', 'changed', 'def f():\nreturn True\n')[0], previous)

    def test_indirect_question_without_question_mark_reaches_human(self):
        with tempfile.TemporaryDirectory() as temp:
            parent, out = Path(temp)/'initial', Path(temp)/'refined'
            parent.mkdir()
            out.mkdir()
            project = {'brief': '공개 원문', 'files': {'f.py': 'pass'}}
            save(parent/'design.json', protocol.spec(project, 263, 'test'))
            snap = {'sha256': 'draft', 'files': project['files']}
            reviews = {'calls': [], 'reviewers': [{'role': 'A', 'response': {'questions': [{'question': '처리 기준'}]}}]}
            q = '어떤 기준을 쓸지 알려 주세요.'
            with patch.object(protocol, 'record_version', return_value=(snap, reviews)), patch.object(
                    protocol, 'call_model', return_value=('call', {'questions': [{'basis': 'A1', 'question': q}]})):
                state = refinement.stage(parent, out)
            self.assertEqual(state['arms']['p4']['status'], 'awaiting_human')
            self.assertEqual(read(out/'p4/v1/review.json')['questions'][0]['question'], q)

    def test_revision_view_keeps_supplied_contract_and_executable_string(self):
        starter = 'def f():\n    """public contract"""\n    return 0\n'
        code = '"""invented authority"""\n' + starter + '\nvalue = "keep this string"\n'
        view = refinement.revision_view('file.py', code, starter)
        self.assertNotIn('invented authority', view)
        self.assertIn('public contract', view)
        self.assertIn('value = "keep this string"', view)
        self.assertEqual(refinement.revision_view('file.txt', code, starter), code)

    def test_atomic_guard_rejects_signature_as_evidence_and_keeps_supported_edit(self):
        before = {'f.py': 'def f():\n    return False\n', 'g.py': 'a = 1\n'}
        proposed = {'f.py': 'def f():\n    return True\n', 'g.py': 'a = 2\n'}
        first = {'reply': 'Open it.', 'status': 'changed', 'file': 'f.py', 'line': 'def f():'}
        second = {'reply': 'Use two.', 'status': 'changed', 'file': 'g.py', 'line': 'a = 2'}
        files, check = guarded.decide(before, proposed, ['Open it.', 'Use two.'], [first, second])
        self.assertTrue(check['held'])
        self.assertEqual(files, before)
        changed = {**first, 'line': 'return True'}
        files, check = guarded.decide(before, proposed, ['Open it.', 'Use two.'], [changed, second])
        self.assertFalse(check['held'])
        self.assertEqual(files, proposed)
        files, check = guarded.decide(before, proposed, ['Open it.', 'Use two.'], [{**first, 'status': 'present'}, second])
        self.assertEqual(check['unverified'], ['Open it.'])
        self.assertFalse(check['held'])
        files, check = guarded.decide(before, proposed, ['Open it.', 'Use two.'],
                                      [{**first, 'status':'present', 'line':'# only a comment'}, second], ['missing_executable_line'])
        self.assertFalse(check['held'])
        self.assertEqual(files, proposed)
