from copy import deepcopy
from unittest import TestCase

from backend import answer_contracts as a
from experiments import answer_fidelity as fix


def receipt(n, text, *questions):
    return dict(cycle=n, text=text, questions=[dict(question=q) for q in questions or ('운영 기준은 무엇인가요?',)])


class AnswerFidelity(TestCase):
    def setUp(self):
        self.cells = [f'{x} and {y}' for x in ('load < 4', 'load == 4', 'load > 4')
                      for y in ('gap_seconds < 7', 'gap_seconds == 7', 'gap_seconds > 7')]
        self.public = 'gap_seconds는 교대까지 남은 시간(7은 교대 시점)입니다. 잠금이면 True, 해제이면 False를 반환합니다.'
        self.original = dict(applicable=True, regions={c: dict(result='False', sources=['P1']) for c in self.cells})
        self.answer = '교대 시점에는 요청을 잠금으로 처리합니다.'

    def run_bind(self, receipts, original=None, public=None, prior=None, unique_scope=True):
        facts = dict.fromkeys(s for r in receipts for s in r['text'].splitlines())
        packet = {'함수':'relay(load, gap_seconds)', '입력영역':self.cells, '원문':{
            'P1':public or self.public, **{f'H{i}':s for i,s in enumerate(facts,1)}},
            '가능한결과':{v:{'근거':[]} for v in ('True','False','defer')}}
        return a.bind(original or self.original, packet, receipts, unique_scope, prior)

    def test_interface_defines_both_named_state_and_polarity(self):
        out, record = self.run_bind([receipt(1,self.answer)])
        self.assertEqual([r['condition'] for r in record['rules']], ['gap_seconds == 7'])
        self.assertEqual(len(record['changes']), 3)
        self.assertTrue(all(out['regions'][c]['result'] == ('True' if 'gap_seconds == 7' in c else 'False') for c in self.cells))
        reversed_public = self.public.replace('잠금이면 True, 해제이면 False','잠금이면 False, 해제이면 True')
        self.assertEqual(self.run_bind([receipt(1,self.answer)], public=reversed_public)[0], self.original)
        self.assertEqual(self.original['regions'][self.cells[1]]['result'], 'False')

    def test_qualifications_numbers_and_questions_cannot_invent_an_outcome(self):
        for text in ['교대 시점 직후에는 잠금으로 처리합니다.', 'VIP의 교대 시점에는 잠금으로 처리합니다.',
                     '교대 시점에는 온도가 높으면 잠금으로 처리합니다.', '교대 시점에는 잠금하지 않습니다.',
                     '교대 기간은 7초입니다.', '정해지지 않았습니다.', 'If gap_seconds == 7 and load > 4, return True.']:
            with self.subTest(text=text):
                self.assertEqual(self.run_bind([receipt(1,text,'잠금이 맞나요?')])[0], self.original)
        self.assertEqual(self.run_bind([receipt(1,self.answer)],unique_scope=False)[0],self.original)

    def test_explicit_predicate_and_unit_conversion_use_actual_interface_only(self):
        self.assertEqual(self.run_bind([receipt(1,'If gap_seconds > 7, return True.')])[1]['rules'][0]['condition'], 'gap_seconds > 7')
        self.assertEqual(self.run_bind([receipt(1,'When gap_seconds is at least 7 seconds, return True.')])[1]['rules'][0]['condition'], 'gap_seconds >= 7')
        self.assertFalse(self.run_bind([receipt(1,'When load is at least 7 seconds, return True.')])[1]['rules'])
        self.assertFalse(self.run_bind([receipt(1,'If gap_seconds >= 9, return True.')])[1]['rules'])

    def test_two_uses_of_yes_have_their_own_referents(self):
        r1 = receipt(1,'네.','교대 시점에는 잠금인가요?')
        r2 = receipt(2,'네.','If load > 4, should the result be False?')
        out, rec = self.run_bind([r1,r2])
        self.assertEqual([(r['reply'],r['condition'],r['result']) for r in rec['rules']],
                         [('R1.1','gap_seconds == 7','True'),('R2.1','load > 4','False')])
        self.assertEqual(out['regions']['load > 4 and gap_seconds == 7']['result'], 'defer')
        self.assertEqual(out['regions']['load < 4 and gap_seconds == 7']['result'], 'True')
        self.assertEqual(len(rec['issues']),1)
        no=receipt(1,'No.','If load > 4, should the result be False?')
        self.assertEqual(self.run_bind([no])[1]['rules'][0]['result'], 'True')
        for qs in [('교대 시점에는 잠금인가요?','해제인가요?'),('교대 시점에는 잠금 또는 해제인가요?',),('교대 시점에는 어떻게 처리하나요?',)]:
            self.assertFalse(self.run_bind([receipt(1,'네.',*qs)])[1]['rules'])

    def test_only_previously_implemented_and_still_cited_outcome_can_carry(self):
        sentence = '보관 요청이 유효한 때에는 별도 기한이 끝났어도 허용합니다.'
        public = self.public+' 허용하면 True, 거부하면 False입니다.'
        rows = deepcopy(self.original)
        cell = self.cells[-1]
        rows['regions'][cell] = dict(result='True',sources=['P1','H1'])
        first = receipt(1,sentence)
        prior = self.run_bind([first],rows,public)[1]
        rows['regions'][cell]['result'] = 'False'
        next_reply = receipt(2,'우선 요청이면 접수할 수 있습니다.')
        out,rec = self.run_bind([first,next_reply],rows,public,prior)
        self.assertEqual(out['regions'][cell]['result'],'True')
        self.assertEqual(rec['changes'][0]['reason'],'previously_implemented_same_answer')
        self.assertEqual(rec['changes'][0]['replies'],['R1.1'])
        for alternative in ['기준이 변경됐습니다.','다른 고객이면 거부합니다.']:
            self.assertEqual(self.run_bind([first,receipt(2,alternative)],rows,public,prior)[0],rows)
        rows['regions'][cell]['sources']=['P1']
        self.assertEqual(self.run_bind([first,next_reply],rows,public,prior)[0],rows)

    def test_list_priority_does_not_promote_a_single_example_to_general_policy(self):
        name='first present by blue > red'
        cell='several distinct declared values, only declared values'
        phrase='Priority order: blue, red'
        opts={name:{'근거':['H1']}}
        self.assertEqual(a.collection_claim(phrase,'H1',opts,[cell])[-1],name)
        self.assertIsNone(a.collection_claim('If blue and red occur together, return blue.','H1',opts,[cell]))

    def test_native_writer_gets_question_and_reply_in_one_existing_call(self):
        class Ask:
            def __init__(self):
                self.calls=[]
            def text(self,role,system,packet,seed,limit):
                self.calls.append((role,packet))
                return 'id','the original code'
        ask=Ask()
        files={'settings.json':'{}'}
        writer=fix.AnswerWriter(ask,[receipt(1,'네.','Should we retain the old name?')],files,files)
        self.assertEqual(writer.text('main-author','write',{'editable_scope':{'name':'settings.json'}},1,50),('id','the original code'))
        self.assertEqual(len(ask.calls),1)
        self.assertEqual(ask.calls[0][1]['owner_dialogue'],[dict(questions=['Should we retain the old name?'],replies=['네.'])])
        self.assertEqual(writer.records[0]['mode'],'native')

    def test_full_writer_compiles_same_confirmed_rule_for_a_different_device_interface(self):
        files={'relay.py':'def latch(wait_seconds):\n    raise NotImplementedError\n'}
        question=receipt(1,'교대 시점에는 잠금으로 처리합니다.','교대할 때 어떤 동작을 하나요?')
        for polarity, expected in [('잠금이면 True, 해제이면 False','True'),('잠금이면 False, 해제이면 True','False')]:
            public=('설비 릴레이 함수 latch(wait_seconds) -> bool을 구현합니다. '
                    'wait_seconds는 교대까지 남은 시간(7은 교대 시점)입니다. 교대 시점은 7초로 표시합니다. '+polarity+'를 반환합니다.')
            project=dict(brief=public,files=files)
            roles=[]
            default='False' if expected=='True' else 'True'
            def ask(role,system,packet,schema,seed,limit):
                roles.append(role)
                if role=='main-rule-plan':
                    facts=packet['public_and_owner_sources']
                    return role,dict(scopes=['T1'],notes={k:dict(established=v,input='wait_seconds',still_open='') for k,v in facts.items()})
                if role=='main-region-decisions':
                    return role,dict(applicable=True,regions={c:dict(result=default,sources=['P1']) for c in packet['입력영역']})
                return role,dict(questions=[],needs_code_fix=False)
            outcome=fix.revise(project,files,[question],5,'self',ask)
            self.assertEqual(roles,['main-rule-plan','main-region-decisions','main-self'])
            fn={}
            exec(outcome['files']['relay.py'],fn)
            self.assertEqual([fn['latch'](n) for n in (6,7,8)],[default=='True',expected=='True',default=='True'])
            self.assertEqual(outcome['writer']['answer_application'][0]['changes'][0]['region'],'wait_seconds == 7')
