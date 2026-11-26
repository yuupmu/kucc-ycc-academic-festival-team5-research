import unittest

from backend import scoped_implementation as edit
from experiments import rule_intake, rule_writer


class TargetedImplementation(unittest.TestCase):
    def setUp(self):
        self.source = {'src/names.py':'DEFAULT = 1\n\ndef badge(items):\n    """Keep this contract."""\n    return "unset"\n\ndef size(items):\n    return len(items)\n'}
        self.regions = edit.targets(self.source,self.source)
        self.body = next(k for k,r in self.regions.items() if r['name']=='badge')
        self.plan = {'H1':{'status':'rule','input':'items'}}

    def test_native_patch_preserves_other_function_and_checks_live_input_dependency(self):
        code = 'Here is the change.\n```python\ndef badge(items):\n    xs = list(items)\n    if not xs:  # [H1]\n        return "empty"  # [H1]\n    return "used"\n```\n'
        change = edit.natural_edit(self.body,self.regions[self.body],code,self.plan)
        files, receipts = edit.apply(self.source,self.regions,[change],self.plan)
        self.assertIn('"""Keep this contract."""',files['src/names.py'])
        self.assertTrue(files['src/names.py'].endswith('def size(items):\n    return len(items)\n'))
        self.assertTrue(receipts['H1']['structural_support'])
        self.assertEqual(len(receipts['H1']['locations']),2)
        self.assertTrue(all('items' in l['inputs'] for l in receipts['H1']['locations']))

    def test_unreachable_or_declaration_cannot_discharge_rule(self):
        code='def badge(items):\n    return 0\n    return len(items)  # [H1]'
        update=edit.natural_edit(self.body,self.regions[self.body],code,self.plan)
        _, receipts=edit.apply(self.source,self.regions,[update],self.plan)
        self.assertFalse(receipts['H1']['structural_support'])
        self.assertFalse(receipts['H1']['locations'][0]['reachable_statement'])
        self.assertNotIn(1,edit.behavior('def badge(items):\n    return len(items)'))

    def test_bad_edit_is_atomic_and_non_python_project_has_a_file_scope(self):
        with self.assertRaises(ValueError):
            edit.natural_edit(self.body,self.regions[self.body],'def badge(changed_name):\n    return 0',self.plan)
        with self.assertRaises(ValueError):
            edit.natural_edit(self.body,self.regions[self.body],'def badge(items):\n    return 0 # [H99]',self.plan)
        files={'display.json':'{"old":true}\n','manual.txt':'keep me'}
        regions=edit.targets(files,files)
        key=next(k for k,r in regions.items() if r['path']=='display.json')
        patch=edit.natural_edit(key,regions[key],'```json\n{"old":false}\n```',self.plan)
        after, evidence=edit.apply(files,regions,[patch],self.plan)
        self.assertEqual(after,{'display.json':'{"old":false}\n','manual.txt':'keep me'})
        self.assertFalse(evidence['H1']['structural_support'])

    def test_hypotheses_only_emit_owner_question_and_writer_receives_separate_raw_facts(self):
        project={'brief':'Display a badge.','files':self.source}
        def inspect(role,system,packet,schema,seed,limit):
            self.assertNotIn('previous_reviews',packet)
            return role,{'needed':True,'quote':'a badge','possible_rule_1':'PRIVATE HYPOTHESIS ONE',
                         'possible_rule_2':'PRIVATE HYPOTHESIS TWO','distinguishing_situation':'one display',
                         'owner_question':'Which label should appear?'}
        intake=rule_intake.inspect(project,self.source,3,inspect)
        self.assertEqual(intake['questions'],[{'question':'Which label should appear?','proposed_by':['A','B','C']}])
        target=self.body
        class Main:
            def __call__(self,role,system,packet,schema,seed,limit):
                assert 'HYPOTHESIS' not in str(packet)
                return 'plan',{'scopes':[target], 'notes':{k:{'established':v,'input':'items','still_open':''}
                        for k,v in packet['public_and_owner_sources'].items()}}
            def text(self,role,system,packet,seed,limit):
                assert 'HYPOTHESIS' not in str(packet)
                assert packet['current_owner_replies']==['Name it set.']
                return 'write','def badge(items):\n    return "set" if items else ""  # [P1, H1]\n'
        write=rule_writer.write(project,self.source,'Name it set.',3,Main())
        self.assertIsNone(write['error'])
        self.assertTrue(write['bindings']['H1']['structural_support'])
        self.assertEqual(write['calls'],['plan','write'])
