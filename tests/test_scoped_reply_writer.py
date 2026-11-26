import copy
from pathlib import Path
import tempfile
import unittest

from experiments import confirmed_points, guarded_reply, reply_pipeline, scoped_reply_writer as writer, scoped_sites, scoped_transfer_v2 as pipeline
from experiments.local_transport import read


class ScopedWriterTest(unittest.TestCase):
    def test_human_gate_and_scoped_revision_across_three_cycles(self):
        initial = 'def mark(value):\n    if not value:\n        return ""\n    raise NotImplementedError\n'
        project = {'brief': 'Preserve empty text. Ask about other text.', 'files': {'solution.py': initial}}
        observed = []
        behavior = [{'when': 'nonempty text', 'then': 'uppercase'}]

        def transport(out, design, role, system, packet, schema, seed, limit, port):
            observed.append((role, copy.deepcopy(packet)))
            if role == 'main':
                value = {'code': initial}
            elif role == 'main-behavior':
                self.assertEqual(set(packet), {'brief', 'dialogue'})
                value = {'behavior': behavior}
            elif role == 'main-edit':
                self.assertEqual(packet['behavior'], behavior)
                self.assertEqual(list(packet['evidence']), [packet['dialogue'][0]['request_id'] + '/H1'])
                value = {'edits': [dict(before=next(iter(packet['pending'])), after='return value.upper()',
                                        evidence=next(iter(packet['evidence'])))]}
            else:
                self.assertEqual(set(packet), {'brief', 'code', 'dialogue'})
                value = {'questions': [] if packet['dialogue'] else ['How should we render nonempty text?'], 'issue': ''}
            return f'{role}-{seed}', value

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(pipeline.run(project, out, 0, transport=transport), ['self-1', 'abc-1'])
            self.assertFalse(any(role in ('main-edit', 'main-behavior') for role, _ in observed))
            with self.assertRaises(ValueError):
                pipeline.receive(out, 'abc-2', 'uppercase')
            for arm in ('self', 'abc'):
                pipeline.receive(out, arm + '-1', 'Return uppercase for nonempty text.')
            self.assertEqual(pipeline.run(project, out, 0, transport=transport), [])
            self.assertEqual(set(read(out / 'sealed.json')), {'solo','self','abc'})
            self.assertEqual((out / 'submissions/solo/solution.py').read_text(), initial)
            for arm in ('self', 'abc'):
                self.assertEqual((out / f'submissions/{arm}/solution.py').read_text(),
                                 initial.replace('raise NotImplementedError', 'return value.upper()'))
                self.assertEqual(read(out / (arm + '-3-snapshot.json'))['dialogue'],
                                 read(out / (arm + '-1-snapshot.json'))['dialogue'])
                self.assertFalse((out / (arm + '-2-writer.json')).exists())
            self.assertEqual(sum(role == 'main-behavior' for role, _ in observed), 2)
            with self.assertRaises(ValueError):
                pipeline.receive(out, 'abc-1', 'Use lowercase.')

    def test_unreadable_plan_uses_original_evidence_and_rejects_an_invalid_edit(self):
        history = [{'request_id':'r', 'questions':['Which label?'], 'answer':{'text':'Use blue.'}}]
        code = 'def label():\n    raise NotImplementedError\n'
        seen = []

        def ask(role, prompt, packet, schema, seed, limit):
            seen.append(role)
            if role == 'main-behavior':
                return f'plan-{limit}', None
            self.assertNotIn('behavior', packet)
            self.assertEqual(packet['evidence']['r/H1']['quote'], 'Use blue.')
            return str(seed), {'edits':[dict(evidence='r/H1', before='no such statement', after='return 0')]}

        actual, trace = writer.revise('Return the chosen label.', code, history, [], 5, ask)
        self.assertEqual(actual, code)
        self.assertIsNone(trace['behavior'])
        self.assertEqual(seen, ['main-behavior','main-behavior','main-edit','main-edit'])
        self.assertEqual([a['outcome'] for a in trace['attempts']], ['rejected','rejected'])
        with self.assertRaises(ValueError):
            writer.revise('Return the chosen label.', code, [], [], 5, ask)

    def test_named_operations_in_a_live_three_cycle_run(self):
        initial = 'def price(n):\n    if n < 0:\n        return 0\n    raise NotImplementedError\n'
        project = {'brief':'Ask about the amount for valid quantities.', 'files':{'solution.py':initial}}
        def transport(out, design, role, prompt, packet, schema, seed, limit, port):
            if role == 'main':
                return 'draft', {'code':initial}
            if role.startswith('observer-'):
                return role + str(seed), {'questions':[] if packet['dialogue'] else ['What is the price?'], 'issue':''}
            if role == 'main-behavior':
                return 'plan', {'behavior':[{'when':'n >= 0','then':'twice the quantity'}]}
            self.assertEqual(role, 'main-fill')
            self.assertEqual(set(packet['sites']), {'@pending:4:4'})
            self.assertNotIn('continue', schema['properties']['sites']['properties']['@pending:4:4']['properties']['form']['enum'])
            return 'fill', {'sites':{'@pending:4:4':{'evidence':'abc-1/H1','form':'return','body':'n * 2'}}, 'other_edits':[]}

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self.assertEqual(scoped_sites.run(project, out, 0, arms=('abc',), transport=transport), ['abc-1'])
            pipeline.receive(out, 'abc-1', 'Use twice the quantity.')
            self.assertEqual(scoped_sites.run(project, out, 0, arms=('abc',), transport=transport), [])
            self.assertEqual((out/'submissions/abc/solution.py').read_text(),
                             initial.replace('raise NotImplementedError', 'return n * 2'))
            self.assertEqual(read(out/'edit-method.json')['writer'], scoped_sites.VERSION)

    def test_loop_scope_and_unmodified_completed_targets(self):
        code = ('def tags(values):\n    for v in values:\n        if v:\n            raise NotImplementedError\n'
                '    else:\n        raise NotImplementedError\n')
        from backend.allocation_repair import pending_sites
        sites = scoped_sites.site_context(code, pending_sites(code))
        self.assertTrue(sites['@pending:4:12']['in_loop'])
        self.assertEqual(sites['@pending:4:12']['within'], ['v'])
        self.assertFalse(sites['@pending:6:8']['in_loop'])
        self.assertEqual(scoped_sites.replacement({'form':'continue','body':''}), 'continue')
        self.assertIsNone(scoped_sites.replacement({'form':'keep','body':''}))
        with self.assertRaises(SyntaxError):
            scoped_sites.replacement({'form':'return','body':'x\nprint(x)'})
        def echo(*args):
            return args
        args = ('out', {}, 'main-edit', 'prompt', {'pending':{}}, {}, 0, 1, 0)
        self.assertEqual(scoped_sites.with_sites(echo)(*args), args)

    def test_scalar_guard_requires_a_complete_non_overlapping_integer_partition(self):
        self.assertEqual(guarded_reply.total_guard('x <= -9 or x > 42','-9 < x <= 42','x'),
                         'x <= -9 or x > 42')
        self.assertIsNone(guarded_reply.total_guard('x < -50','x > -50','x'))
        self.assertIsNone(guarded_reply.total_guard('x <= 50','x >= 50','x'))
        self.assertEqual(guarded_reply.total_guard('False','True','x'), 'False')
        with self.assertRaises(ValueError):
            guarded_reply.total_guard('any(x)','True','x')
        with self.assertRaises(ValueError):
            guarded_reply.total_guard('x < other','False','x')

    def test_final_writer_through_human_gate(self):
        code = 'def alert(v: int) -> bool:\n    if v == -9:\n        return False\n    raise NotImplementedError\n'
        project = {'brief':'Ask when to alert. The sentinel is always quiet.', 'files':{'solution.py':code}}
        def transport(out, design, role, prompt, packet, schema, seed, limit, port):
            if role == 'main':
                return 'main', {'code':code}
            if role.startswith('observer-'):
                return role+str(seed), {'questions':[] if packet['dialogue'] else ['When?'], 'issue':''}
            if role == 'main-behavior':
                return 'plan', {'behavior':[{'when':'v is 8','then':'alert'}]}
            self.assertEqual(role, 'main-predicates')
            self.assertNotIn('code', packet)
            return 'predicates', {'true_when':'v = 8', 'false_when':'v != 8', 'evidence':'abc-1/H1'}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(reply_pipeline.run(project,out,0,arms=('abc',),transport=transport), ['abc-1'])
            pipeline.receive(out,'abc-1','Alert only for 8.')
            self.assertEqual(reply_pipeline.run(project,out,0,arms=('abc',),transport=transport), [])
            self.assertEqual((out/'submissions/abc/solution.py').read_text(),
                             code.replace('raise NotImplementedError','return v == 8'))
            self.assertEqual((out/'submissions/solo/solution.py').read_text(),code)

    def test_exact_point_changes_only_the_shared_boundary(self):
        import ast
        raw = {'true_when':'v < -8', 'false_when':'v > -8 or v = -8', 'evidence':'r/H1'}
        packet = {'parameter':'v', 'behavior':[{'when':'-8','then':'True'},{'when':'20','then':'True'}]}
        result = confirmed_points.reconcile(raw,packet)
        guard = ast.parse(result['true_when'],mode='eval').body
        for n in range(-30,31):
            self.assertEqual(guarded_reply.check_predicate(guard,'v',n),n <= -8)
        packet['behavior'][0]['then']='미정'
        unresolved = confirmed_points.reconcile(raw,packet)
        self.assertIsNone(guarded_reply.total_guard(unresolved['true_when'],unresolved['false_when'],'v'))
        self.assertEqual(confirmed_points.normalize('v != 3 or v <= 4 or v >= 9'),'v != 3 or v <= 4 or v >= 9')

    def test_final_flow_generates_values_only_from_public_and_owner_text(self):
        initial='def alert(v: int) -> bool:\n    raise NotImplementedError\n'
        project={'brief':'alert(v) -> bool은 정수 신호를 처리합니다.', 'files':{'solution.py':initial}}
        def transport(out,design,role,prompt,packet,schema,seed,limit,port):
            if role=='main':
                return 'main',{'code':initial}
            if role.startswith('observer-'):
                return role+str(seed),{'questions':[] if packet['dialogue'] else ['Is 999 relevant?'], 'issue':''}
            if role=='main-point-values':
                self.assertEqual(packet['inputs'],[-8])
                self.assertEqual(set(packet),{'brief','dialogue','inputs'})
                return 'point',{'-8':'True'}
            self.assertEqual(role,'main-predicates')
            return 'guard',{'true_when':'v < -8','false_when':'v >= -8','evidence':'abc-1/H1'}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            self.assertEqual(confirmed_points.run(project,out,0,arms=('abc',),transport=transport),['abc-1'])
            pipeline.receive(out,'abc-1','Alert up to and including -8.')
            self.assertEqual(confirmed_points.run(project,out,0,arms=('abc',),transport=transport),[])
            self.assertEqual(read(out/'abc-1-writer.json')['calls'],['point','guard'])
            self.assertEqual((out/'submissions/abc/solution.py').read_text(),
                             initial.replace('raise NotImplementedError','return v < -8 or v == -8'))
