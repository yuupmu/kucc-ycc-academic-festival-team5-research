import copy
import tempfile
import unittest
from pathlib import Path

from backend.allocation_repair import pending_sites
from experiments import decision_ledger as ledger, ledger_pipeline, receipt_pipeline


class DecisionLedgerTests(unittest.TestCase):
    def setUp(self):
        code = 'def active(level: int) -> bool:\n    if level < -3:\n        return False\n    raise NotImplementedError\n'
        self.agenda = dict(code=code, editing_base=code, brief='Return a Boolean for an integer level.',
            slots={'threshold':dict(kind='quantity',question='What is the threshold?'),
                   'at':dict(kind='decision',question='Enable it exactly at the threshold?')},
            names=['level'],mode='integer',public={'P':'Values below -3 are invalid.'},
            scope=dict(accepted=True,sites=list(pending_sites(code))),
            rules=[{'when':'level < threshold','then':'True'}, {'when':'level == threshold','then':'at'},
                   {'when':'level > threshold','then':'False'}])

    def invoke(self, role,prompt,packet,schema,limit):
        if role=='owner-statements':
            reply=packet['owner_reply']
            return role, {'facts':[dict(quote=reply,kind='quantity' if 'threshold is' in reply else 'decision')]}
        if role=='bind-owner-statement':
            quantity=packet['kind']=='quantity'
            return role,dict(item='threshold' if quantity else 'at',
                             value='7' if quantity else str(packet['statement']=='Yes.'))
        self.fail(role)

    def test_two_replies_fork_one_pending_input_without_reopening_public_rules(self):
        parent=ledger.receive(self.agenda,ledger.start(self.agenda),'The threshold is 7.',self.invoke)
        self.assertEqual(ledger.questions(self.agenda,parent),['Enable it exactly at the threshold?'])
        snapshot=copy.deepcopy(parent)
        with tempfile.TemporaryDirectory() as path:
            branches=[]
            for reply in ('Yes.','No.'):
                folder=Path(path)/reply
                result=ledger_pipeline.checkpoint(folder,self.agenda,parent,reply,self.invoke)
                branches.append(result)
                self.assertEqual(result,ledger_pipeline.checkpoint(folder,self.agenda,parent,reply,None))
                self.assertEqual(result['confirmed']['threshold'],parent['confirmed']['threshold'])
            self.assertEqual(parent,snapshot)
            self.assertEqual(len([1 for a,b in zip(branches[0]['code'].splitlines(),branches[1]['code'].splitlines()) if a!=b]),1)
            for state,decision in zip(branches,(True,False)):
                self.assertFalse(state['pending'])
                ns={}
                exec(state['code'],ns)
                for x in range(-6,12):
                    self.assertIs(ns['active'](x),decision if x==7 else -3<=x<7)

    def test_multi_item_yes_and_invented_quotation_close_nothing(self):
        initial=ledger.start(self.agenda)
        result=ledger.receive(self.agenda,initial,'Yes.',self.invoke)
        self.assertFalse(result['confirmed'])
        self.assertEqual(ledger.source_quote('허용 여부는 미정입니다.','허용합니다.'),'')
        self.assertEqual(ledger.source_quote('값은 -7입니다.','값은 -7 입니다.'),'값은 -7입니다.')

    def test_shared_flag_leaf_with_a_public_return_is_never_reopened(self):
        code='def display(a: bool, b: bool) -> bool:\n    if a:\n        return True\n    return False\n'
        rules=[dict(when='a and b',then='together'),dict(when='a',then='True'),dict(when='True',then='False')]
        self.assertEqual(ledger.reopen_flag_decisions(code,'',rules,['together']),(code,{}))

    def test_literal_reader_handles_every_sentence_and_reserves_an_unanswered_endpoint(self):
        calls=[]
        def ask(role,prompt,packet,schema,limit):
            self.assertEqual(role,'receipt-item')
            calls.append(packet['owner_statement'])
            if packet['owner_statement']=='기준은 7단계예요.':
                self.assertEqual(list(packet['sent_items']),['threshold'])
                self.assertNotIn('value',schema['properties'])
                return role,{'item':'threshold'}
            return role,{'item':'at','value':'True' if '켜' in packet['owner_statement'] else 'False'}
        parent=receipt_pipeline.receive(self.agenda,ledger.start(self.agenda),'기준은 7단계예요.',ask)
        self.assertEqual(parent['pending'],['at'])
        for text,answer in [('같을 때 켜 주세요.',True),('같을 때 끕니다.',False)]:
            updated=receipt_pipeline.receive(self.agenda,parent,text,ask)
            self.assertIs(updated['confirmed']['at']['value'],answer)
        calls.clear()
        contradicted=receipt_pipeline.receive(self.agenda,ledger.start(self.agenda),
            '기준은 7단계예요. 같을 때 켜 주세요. 같을 때 끕니다.',ask)
        self.assertEqual(len(calls),3)
        self.assertEqual(contradicted['pending'],['at'])


if __name__=='__main__':
    unittest.main()
