import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import monitor_cycles, policy_finalization as policy, rule_edits as rules, serial_revisions as workflow
from experiments.revision_summary import age_changes_answer, pair_changes
from experiments.source_revisions import SourceRevisions


BRIEF = '설명. “먼저 3시간을 고려합니다. 방금 생성한 기록은 별도로 처리합니다.”'
DRAFT = ('def helper(a, b):\n    return a == b\n\n'
         'def allow_cancel(age_seconds, until_start_seconds):\n'
         '    """Keep the public contract."""\n    return helper(age_seconds, until_start_seconds)\n')
CLAUSES = rules.notice_clauses(BRIEF)


def group(field=None, op='<', bound=None, allow=False, rank=2, at='ENTRY'):
    branches = [] if field is None else [{'at':at, 'when':[dict(input=field, op=op, bound=bound)], 'allow':allow}]
    return dict(rank=rank, branches=branches, assumption='')


class SourceEditTests(unittest.TestCase):
    def test_literal_units_and_preserved_fallthrough(self):
        base = SourceRevisions(DRAFT, CLAUSES)
        plan = {'R1': group('until_start_seconds', '>=', 'T1', True),
                'R2': group('age_seconds', '<', {'amount':2, 'unit':'minutes'}, False, rank=1)}
        code, locations = base.render(plan)
        self.assertEqual(base.quantities['T1']['seconds'], 10800)
        self.assertIn('age_seconds < 120', code.splitlines()[locations['R2'][0]-1])
        self.assertIn('until_start_seconds >= 10800', code.splitlines()[locations['R1'][0]-1])
        tree = ast.parse(code)
        del tree.body[1].body[1:3]
        self.assertEqual(ast.dump(tree), ast.dump(ast.parse(DRAFT)))
        scope = {}
        exec(code, scope)  # This is the hand-authored unit-test fixture only.
        fn = scope['allow_cancel']
        self.assertFalse(fn(110, 11111))
        self.assertTrue(fn(121, 11111))
        self.assertTrue(fn(121, 121))
        self.assertFalse(fn(121, 122))
        self.assertEqual(base.render(dict.fromkeys(CLAUSES, group()))[0], DRAFT)

    def test_edit_at_one_return_does_not_override_another_return_or_nested_function(self):
        src = ('def allow_cancel(age_seconds, until_start_seconds):\n'
               '    def nested():\n        return 33\n'
               '    if until_start_seconds < 0:\n        return False\n    return True\n')
        base = SourceRevisions(src, CLAUSES)
        self.assertEqual(list(base.sites), ['ENTRY','E1','E2'])
        plan = {'R1':group('age_seconds','>=',{'amount':0,'unit':'seconds'},True,at='E1'),
                'R2':group('age_seconds','>=',{'amount':0,'unit':'seconds'},False,at='E2')}
        code, lines = base.render(plan)
        self.assertTrue(code.splitlines()[lines['R1'][0]-1].startswith('        if '))
        self.assertTrue(code.splitlines()[lines['R2'][0]-1].startswith('    if '))
        scope = {}
        exec(code, scope)
        self.assertTrue(scope['allow_cancel'](1,-9))
        self.assertFalse(scope['allow_cancel'](1,9))
        self.assertEqual(base.notes(plan)['branch_order_notes_by_site'], {'E1':[], 'E2':[]})

    def test_empty_source_requires_explicit_default_and_rejects_unknown_reference(self):
        base = SourceRevisions('def broken(', CLAUSES)
        plan = dict(R1=group(), R2=group(), otherwise=True)
        self.assertFalse(base.has_base)
        code, _ = base.render(plan)
        self.assertIn('return True', code)
        plan['R1'] = group('age_seconds', '>=', 'T9', False)
        with self.assertRaises(ValueError):
            base.render(plan)

    def test_keep_note_and_noop_are_not_counted_as_rule_changes(self):
        a = SourceRevisions(DRAFT, CLAUSES)
        plan = {'R1':group(), 'R2':group()}
        edits = {'R1':{'set':dict(plan['R1'], assumption='가정'), 'reason':'기록'},
                 'R2':{'set':plan['R2'], 'reason':'같음'}}
        before = copy.deepcopy(plan)
        updated, receipt = rules.apply_edits(plan, edits)
        self.assertEqual(plan, before)
        self.assertEqual(receipt['R1']['status'], 'note_only')
        self.assertEqual(receipt['R2']['status'], 'no_change')
        self.assertEqual(a.render(updated)[0], a.render(plan)[0])
        self.assertIsNone(rules.decode('{"R1":{"keep":"유지"}}', rules.patch_slots(a.slots)))

    def test_unreachable_condition_found_from_source_only(self):
        a = SourceRevisions(DRAFT, CLAUSES)
        plan = {'R1':group('age_seconds','>=',{'amount':1,'unit':'minutes'},True,rank=1),
                'R2':group('age_seconds','>=',{'amount':2,'unit':'minutes'},False,rank=2)}
        notes = a.notes(plan)
        self.assertIn('R1.1', notes['branch_order_notes_by_site']['ENTRY'][0])
        self.assertEqual(notes['fields_by_clause']['R2'], ['age_seconds'])

    def test_warns_about_impossible_path_and_provably_redundant_return(self):
        src = ('def allow_cancel(age_seconds, until_start_seconds):\n'
               '    if until_start_seconds > 8:\n        return True\n    return False\n')
        base = SourceRevisions(src, CLAUSES)
        zero = {'amount':0, 'unit':'seconds'}
        plan = {'R1':group('until_start_seconds','<',zero,False,at='E1'),
                'R2':group('age_seconds','>=',zero,False,at='E2')}
        notes = base.notes(plan)['branch_order_notes_by_site']
        self.assertIn('도달', notes['E1'][0])
        self.assertIn('제거', notes['E2'][0])
        plan['R1'] = group('age_seconds','>=',zero,False,rank=0,at='E2')
        plan['R2'] = group('age_seconds','>',zero,True,rank=1,at='E2')
        notes = base.notes(plan)['branch_order_notes_by_site']['E2']
        self.assertFalse(any('제거' in n for n in notes))
        self.assertTrue(any('포함됨' in n for n in notes))


class SerialHandoffTests(unittest.TestCase):
    def test_clock_review_compiles_the_public_cutoff_and_separate_chosen_window(self):
        fields = {'R1':{'공개_수량':{'seconds':3*3600}}}
        form = dict(ordinary_at_deadline=True, correction_window=dict(amount=2,unit='minutes'),
                    correction_at_window_end=False, correction_scope='before_start',
                    reasons={'R1':'일반','R2':'시작','R3':'가정'})
        text, lines = policy.render(form,fields)
        self.assertIn('10800', text.splitlines()[lines['R1'][0]-1])
        self.assertIn('age_seconds < 120', text.splitlines()[lines['R3'][-1]-1])
        namespace = {}
        exec(text,namespace)  # Unrelated hand-authored fixture, never part of the model pipeline.
        decide = namespace['allow_cancel']
        self.assertTrue(decide(6000,10800))
        self.assertTrue(decide(119,1))
        self.assertFalse(decide(120,1))
        self.assertFalse(decide(2,0))
        for scope, expected in [('through_start',(True,False)),('also_after_start',(True,True))]:
            code, _ = policy.render(dict(form,correction_scope=scope),fields)
            exec(code,namespace)
            self.assertEqual(tuple(namespace['allow_cancel'](2,t) for t in (0,-1)), expected)
        self.assertIsNone(rules.decode(json.dumps(dict(form,correction_window={'amount':0,'unit':'hours'})),policy.FORM))

    def test_integrated_mode_completes_both_reviews_before_any_grader_opens(self):
        stages = []
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv',['run','--public-clock-revisions',tmp]), \
             patch.object(monitor_cycles.subprocess,'Popen') as launch, patch.object(monitor_cycles,'urlopen'), \
             patch.object(workflow,'prepare_seal',side_effect=lambda *a: stages.append('source')), \
             patch.object(workflow,'evaluate_seal',side_effect=AssertionError('grading between reviews')), \
             patch.object(policy,'prepare_seal',side_effect=lambda *a: stages.append('contract')), \
             patch.object(policy,'evaluate_seal',side_effect=lambda *a: stages.append('offline_grading')):
            process=launch.return_value.__enter__.return_value
            process.poll.return_value=None
            process.terminate.side_effect=lambda: stages.append('model_closed')
            monitor_cycles.main()
            self.assertEqual(stages,['source','contract','model_closed','offline_grading'])

    def test_final_review_replays_valid_edit_and_keeps_previous_code_on_truncation(self):
        form = dict(ordinary_at_deadline=True, correction_window=dict(amount=2,unit='minutes'),
                    correction_at_window_end=True, correction_scope='before_start',
                    reasons={'R1':'마감','R2':'일반 취소 종료','R3':'별도 가정'})
        def call(path,role,system,prompt,schema,seed,port):
            valid = role.startswith('serial')
            finish = 'stop' if valid else 'length'
            request = dict(model=workflow.MODEL, seed=seed, max_tokens=policy.LIMIT, temperature=0.3, top_p=0.9,
                           top_k=40, stream=False, chat_template_kwargs={'enable_thinking':False},
                           response_format=workflow.response_format(schema),
                           messages=[dict(role='system',content=system),dict(role='user',content=prompt)])
            workflow.save(path,dict(model=workflow.MODEL, role=role, request=request, finish_reason=finish,
                                    text=json.dumps(form) if valid else '{'))
            return (form if valid else None),finish
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(policy,'prefix_input',return_value=(DRAFT,{},['draft.json'])), \
             patch.object(workflow,'json_call',side_effect=call):
            out=Path(tmp)
            for arm in ('self','serial'):
                (out/'11'/arm).mkdir(parents=True)
            workflow.save(out/'11/draft.json',dict(text=DRAFT))
            rows = policy.seal_seed(out,11,0,None)
            self.assertEqual(rows,policy.seal_seed(out,11,0,None,replay=True))
            outputs = {r['arm']:r['code'] for r in rows}
            self.assertEqual(outputs['self_final'],DRAFT)
            self.assertNotEqual(outputs['abcd'],DRAFT)
            receipt=out/'11/serial/contract-receipt.json'
            changed=workflow.read(receipt)
            changed['form']['correction_window']['amount']+=1
            workflow.save(receipt,changed)
            with self.assertRaises(ValueError):
                policy.seal_seed(out,11,0,None,replay=True)

    def test_model_server_stops_before_offline_grading_and_stays_closed_on_resume(self):
        stages = []
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['run', '--serial-revisions', tmp]), \
             patch.object(monitor_cycles.subprocess, 'Popen') as launch, patch.object(monitor_cycles, 'urlopen'), \
             patch.object(workflow, 'prepare_seal') as prepare, patch.object(workflow, 'evaluate_seal') as evaluate:
            process = launch.return_value.__enter__.return_value
            process.poll.return_value = None
            prepare.side_effect = lambda *a, **kw: stages.append('sealed')
            process.terminate.side_effect = lambda: stages.append('model_closed')
            evaluate.side_effect = lambda *a: stages.append('offline_grading')
            monitor_cycles.main()
            self.assertEqual(stages, ['sealed','model_closed','offline_grading'])
            workflow.save(Path(tmp)/'submissions.json', [])
            monitor_cycles.main()
            self.assertEqual(stages[-2:], ['offline_grading','offline_grading'])
            self.assertEqual(launch.call_count, 1)

    def test_case_comparison_pairs_inputs_even_if_order_changes(self):
        first = dict(age_seconds=1, until_start_seconds=3, expected=True, actual=False, error=None, passed=False)
        second = dict(first, age_seconds=2, expected=False, passed=True)
        self.assertFalse(age_changes_answer([first,second]))
        revised = [second, dict(first, actual=True, passed=True)]
        self.assertTrue(age_changes_answer(revised))
        self.assertEqual(pair_changes([first,second], revised), dict(corrected=1, regressed=0, changed=1))
        with self.assertRaises(ValueError):
            pair_changes([first,second], [first,first])

    def test_paired_run_copies_only_spec_analysis_and_draft(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(workflow, 'SEEDS', (11,)):
            previous, target = Path(tmp)/'first', Path(tmp)/'paired'
            (previous/'11/serial').mkdir(parents=True)
            workflow.save(previous/'design.json', dict(protocol='serial-rule-edits-v1', model=workflow.MODEL))
            record = {'model':workflow.MODEL, 'request':{'temperature':0.3, 'top_p':0.9, 'top_k':40,
                                                         'chat_template_kwargs':{'enable_thinking':False}}}
            workflow.save(previous/'11/draft.json', dict(record, text='draft'))
            workflow.save(previous/'11/serial/A.json', dict(record, text='public interpretation'))
            workflow.save(previous/'11/serial/D.json', {'other_method':'private to that method'})
            workflow.save(previous/'11/direct-score.json', {'after_seal_only':True})
            workflow.share_inputs(previous, target)
            self.assertEqual({str(p.relative_to(target)) for p in target.rglob('*.json')},
                             {'11/draft.json', '11/serial/A.json', 'shared-inputs.json'})
            self.assertEqual(workflow.read(target/'11/serial/A.json'), workflow.read(previous/'11/serial/A.json'))
            workflow.save(target/'11/draft.json', dict(record, text='another draft'))
            with self.assertRaises(ValueError):
                workflow.share_inputs(previous, target)

    def test_frozen_pipeline_replays_every_stage_and_never_calls_an_evaluator(self):
        seen = {}
        empty = dict.fromkeys(CLAUSES, group())
        keep = {k:{'keep':'유지'} for k in CLAUSES}
        added = group('age_seconds','<=',{'amount':7,'unit':'minutes'},True)

        def recorded(path, role, system, user, seed, limit, port, fmt=None):
            if role == 'main':
                text = DRAFT
            else:
                payload = {'A':{k:dict(intent=v,inputs=[],unspecified='') for k,v in CLAUSES.items()},
                           'B':empty, 'plan':empty, 'C':dict(keep, R2={'set':added, 'reason':'예외 추가'}),
                           'D':keep, 'review1':keep, 'review2':keep, 'final':keep}[role]
                text = json.dumps(payload, ensure_ascii=False)
            seen[role] = user
            request = dict(model=workflow.MODEL, seed=seed, max_tokens=limit, temperature=0.3, top_p=0.9,
                           top_k=40, stream=False, chat_template_kwargs={'enable_thinking':False},
                           messages=[dict(role='system',content=system),dict(role='user',content=user)])
            if fmt is not None:
                request['response_format'] = fmt
            record = dict(text=text, role=role, model=workflow.MODEL, finish_reason='stop', request=request)
            workflow.save(path, record)
            return record

        with tempfile.TemporaryDirectory() as tmp, patch.object(workflow, 'public_brief', return_value=BRIEF), \
             patch.object(workflow, 'recorded', side_effect=recorded), \
             patch('backend.isolated.run_cases', side_effect=AssertionError('execution before seal')):
            out = Path(tmp)
            batch = workflow.generate_seed(out, 11, 0, 0)
            workflow.save(out/'submissions.json', batch)
            self.assertEqual(workflow.verify_seal(out, (11,), True)['submissions'], 6)
            by_arm = {r['arm']:r for r in batch}
            self.assertEqual(len(by_arm['abcd']['calls']), 5)
            self.assertEqual(len(by_arm['self_final']['calls']), 5)
            self.assertNotIn('helper(', seen['A'])
            self.assertIn('age_seconds <= 420', seen['D'])
            self.assertEqual(by_arm['abcd']['code'], by_arm['C']['code'])
            self.assertNotEqual(by_arm['B']['sha256'], by_arm['C']['sha256'])
            a_file = out/'11/serial/A.json'
            a_original = workflow.read(a_file)
            contaminated = copy.deepcopy(a_original)
            contaminated['request']['messages'][1]['content'] += '\n이 요청에는 외부 피드백이 추가됐습니다.'
            workflow.save(a_file, contaminated)
            with self.assertRaises(ValueError):
                workflow.verify_seal(out, (11,), True)
            workflow.save(a_file, a_original)
            log_path = out/'11/serial/changes.json'
            log = workflow.read(log_path)
            log[-1]['plan']['R2'] = group()
            workflow.save(log_path, log)
            with self.assertRaises(ValueError):
                workflow.verify_seal(out, (11,), True)
