import ast
import unittest

from backend import anchored_program as program, scoped_implementation as edits
from experiments import rule_program_cycle


class GroundedDecisions(unittest.TestCase):
    def setUp(self):
        self.sources={'P1':'Inspect a parcel in bytes. Return small or large.',
                      'H1':'The large threshold is 3 KiB of package size.',
                      'H2':'For example, 7 MiB might be a future policy.'}
        self.params=['package_bytes','overhead_bytes']
        self.notes={k:{'input':'package_bytes'} for k in self.sources}
        self.atoms=program.catalogue(self.sources,self.params)

    def expr(self,text,refs=('P1','H1'),value=False):
        return program.expression(text,refs,self.sources,self.atoms,self.params,self.notes,value)

    def test_unchanged_compiler_handles_another_domain_and_a_different_duration(self):
        ident=next(iter(self.atoms))
        self.assertEqual(self.expr('package_bytes >= '+ident),'package_bytes >= 3072')
        self.assertEqual(self.expr('package_bytes >= 3*1024'),'package_bytes >= 3 * 1024')
        self.assertFalse(any(s['source']=='H2' for s in self.atoms.values()))
        times=program.catalogue({'P1':'Refresh after 7 minutes.'},['elapsed_seconds'])
        self.assertEqual(next(iter(times.values()))['value'],420)

    def test_wrong_input_unstated_label_and_fabricated_threshold_are_rejected(self):
        for expr in ['overhead_bytes >= Q_H1_1_bytes','package_bytes > 2*2*1024','package_bytes > 4096']:
            with self.assertRaises(ValueError):
                self.expr(expr)
        with self.assertRaises(ValueError):
            self.expr('Q_H1_1_bytes',('P1',),True)
        with self.assertRaises(ValueError):
            self.expr("'oversize'",value=True)

    def test_membership_is_distinct_from_explicit_priority(self):
        sources={'P1':'Labels are blue, red, green.', 'H1':'Priority order: green, blue, red.'}
        notes={k:{'input':'colors'} for k in sources}
        atoms=program.catalogue(sources,['colors'])
        def low(expr,refs):
            return program.expression(expr,refs,sources,atoms,['colors'],notes)
        self.assertTrue(low('has_present(L_P1_1,colors)',['P1']).startswith('any('))
        self.assertTrue(low('first_present(L_H1_1,colors)',['H1']).startswith('next('))
        with self.assertRaises(ValueError):
            low('first_present(L_P1_1,colors)',['P1'])
        with self.assertRaises(ValueError):
            low("first_present(('red','blue','green'), colors)",['H1'])

    def test_unresolved_inputs_and_bad_branch_never_fall_through_to_an_unrelated_return(self):
        r={'parameters':self.params}
        authorized={'when':'package_bytes >= Q_H1_1_bytes','action':'return','value':"'large'",'sources':['P1','H1']}
        defer={'action':'defer','value':'','sources':[]}
        patch,issues=program.compile_rows('T1',r,{'rules':[authorized],'otherwise':defer},self.sources,self.atoms,self.notes)
        self.assertFalse(issues)
        self.assertEqual([row['code'] for row in patch['lines']],['if package_bytes >= 3072:',"return 'large'",'raise NotImplementedError'])
        invalid={**authorized,'when':'package_bytes > 1+2+3'}
        patch,issues=program.compile_rows('T1',r,{'rules':[invalid,authorized],'otherwise':defer},self.sources,self.atoms,self.notes)
        self.assertTrue(issues)
        self.assertEqual([r['code'] for r in patch['lines']],['raise NotImplementedError'])

    def test_main_receives_only_sources_and_own_plan_and_edits_one_named_body(self):
        project={'files':{'parcel.py':'def tag(package_bytes):\n    return "no"\n'},'brief':'Return large or small for a parcel.'}
        reply='The large threshold is 3 KiB of package size.'
        class Main:
            def __call__(self,role,system,packet,schema,seed,limit):
                if role=='main-rule-plan':
                    return 'same-plan',{'scopes':['T2','T1'],'notes':{k:{'input':'package_bytes','established':v,'still_open':''}
                        for k,v in packet['public_and_owner_sources'].items()}}
                self_packet=set(packet)
                assert self_packet=={'signature','public_request','sources','exact_owner_replies','my_preliminary_notes','literal_table'}
                assert packet['exact_owner_replies']==[reply]
                return 'decision',{'applicable':True,'complete':False,'rules':[
                    {'when':'package_bytes >= Q_H1_1_bytes','action':'return','value':"'large'",'sources':['P1','H1']}],
                    'otherwise':{'action':'defer','value':'','sources':[]}}
        output=rule_program_cycle.write(project,project['files'],reply,13,Main())
        self.assertEqual(output['calls'],['same-plan','decision'])
        self.assertFalse(output['complete'])
        self.assertTrue(output['bindings']['H1']['structural_support'])
        self.assertIn('package_bytes >= 3072',output['files']['parcel.py'])
        self.assertEqual(len(ast.parse(output['files']['parcel.py']).body),1)
        other={'guide.txt':'document'}
        self.assertEqual(rule_program_cycle.body_scopes(edits.targets(other,other),['T1']),[])
