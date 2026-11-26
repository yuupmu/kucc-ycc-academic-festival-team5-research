import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import question_guide as guide, scoped_intervention as workflow, source_thresholds as thresholds
from experiments.monitor_cycles import save


BRIEF = 'until_start_seconds는 이용 시작까지 남은 시간(0은 시작 순간)입니다. 안내문은 “일반 마감은 이용 시작 3시간 전입니다.”입니다.'
LENGTH = '확인 기간은 예약 생성 후 7분입니다.'
END = '확인 기간의 마지막 순간도 포함합니다.'
AGE = 'age_seconds · 7분'
START = 'until_start_seconds · 시작 순간'
DEADLINE = 'until_start_seconds · 3시간'


def condition(limit,side):
    return dict(limit=limit,side=side)


def row(tests,action,refs):
    return dict(when=tests,action=action,references=refs)


def compile_fixture(answers,rows,fallback='거부'):
    # Execute only a hand-authored decision table, never a model response.
    points=thresholds.catalogue(BRIEF,answers)
    program=dict(rows=rows,fallback=dict(action=fallback,references=[]))
    code,_,trace=thresholds.render(program,points,answers)
    scope={}
    exec(code,scope)
    return scope['allow_cancel'],trace


class SourceThresholdTests(unittest.TestCase):
    def test_choice_set_uses_only_authorized_sentences_and_cannot_move_a_number_to_another_clock(self):
        points=thresholds.catalogue(BRIEF,['확인 기간은 예약 생성 후 13분인가요?','예약 생성 후 9분으로 할지는 미정입니다.'])
        self.assertEqual(set(points),{START,DEADLINE})
        schema=thresholds.author_schema(points,workflow.TABLE_AUTHOR)
        self.assertNotIn('13분',json.dumps(schema,ensure_ascii=False))
        self.assertNotIn('9분',json.dumps(schema,ensure_ascii=False))
        points=thresholds.catalogue(BRIEF,[LENGTH])
        self.assertEqual(points[AGE].seconds,420)
        self.assertNotIn('until_start_seconds · 7분',points)
        self.assertEqual(points[DEADLINE].seconds,10800)

    def test_duration_literals_are_not_partially_read(self):
        cases={'예약 생성 후 1시간 30분':5400,'예약 생성 후 1.5시간':5400,
               '이용 시작까지 남은 시간 86,400초':86400,'이용 시작 14분 후':-840}
        for sentence,seconds in cases.items():
            with self.subTest(sentence=sentence):
                points=thresholds.catalogue(BRIEF,[sentence+'입니다.'])
                matches=[p.seconds for p in points.values() if any(i for i,s in p.sources)]
                self.assertEqual(matches,[seconds])
        self.assertEqual(list(thresholds.durations('0.3초')),[])

    def test_open_and_closed_ends_obey_the_cited_sentence(self):
        rule=row([condition(AGE,thresholds.BELOW)],'허용',[1,2])
        for fact,expected in ((END,True),('확인 기간의 마지막 순간은 제외합니다.',False)):
            with self.subTest(fact=fact):
                fn,trace=compile_fixture([LENGTH,fact],[rule])
                self.assertEqual([fn(x,12) for x in (419,420,421)],[True,expected,False])
                self.assertEqual(trace[0]['boundary_sources'][0]['text'],fact)
                self.assertEqual(trace[0]['seconds'],420)
                self.assertEqual(trace,json.loads(json.dumps(trace)))
        fn,_=compile_fixture([LENGTH,END],[row([condition(AGE,thresholds.ABOVE)],'거부',[1,2])],fallback='허용')
        self.assertTrue(fn(420,12))
        self.assertFalse(fn(421,12))

    def test_missing_wrong_scope_or_conflicting_edge_abstains_at_equality_only(self):
        other='현재 시각이 이용 시작 시각과 같으면 거부합니다.'
        excluded='확인 기간의 마지막 순간은 제외합니다.'
        for facts,refs in (([LENGTH],[1]),([LENGTH,END],[1]),([LENGTH,other],[1,2]),([LENGTH,END,excluded],[1,2])):
            with self.subTest(facts=facts,refs=refs):
                fn,trace=compile_fixture(facts,[row([condition(AGE,thresholds.BELOW)],'허용',refs)])
                self.assertTrue(fn(419,20))
                self.assertFalse(fn(421,20))
                with self.assertRaises(NotImplementedError):
                    fn(420,20)
                self.assertIsNone(trace[0]['equality'])
        contradictory=thresholds.catalogue(BRIEF,[LENGTH,'확인 기간은 예약 생성 후 11분입니다.',END])
        self.assertNotIn(AGE,contradictory)
        self.assertNotIn('age_seconds · 11분',contradictory)

    def test_explicit_equality_and_rule_priority_are_owned_by_different_sources(self):
        facts=['정확히 이용 시작 3시간 전이면 허용합니다.','현재 시각이 이용 시작 시각과 같으면 거부합니다.']
        fn,_=compile_fixture(facts,[row([condition(DEADLINE,thresholds.ABOVE)],'허용',[1]),
                                    row([condition(START,thresholds.EXACT)],'거부',[2])])
        self.assertTrue(fn(0,10800))
        self.assertFalse(fn(0,10799))
        self.assertFalse(fn(0,0))
        # The same cited amount can have the opposite policy at the exact instant.
        changed=['정확히 이용 시작 3시간 전이면 거부합니다.']
        fn,_=compile_fixture(changed,[row([condition(DEADLINE,thresholds.ABOVE)],'허용',[1])])
        self.assertFalse(fn(0,10800))
        self.assertTrue(fn(0,10801))
        high=row([condition(DEADLINE,thresholds.ABOVE)],'거부',[1])
        low=row([condition(AGE,thresholds.BELOW)],'허용',[2,3])
        fn,_=compile_fixture(changed+[LENGTH,END],[high,low])
        swapped,_=compile_fixture(changed+[LENGTH,END],[low,high])
        self.assertFalse(fn(3,10801))
        self.assertTrue(swapped(3,10801))

    def test_unknown_duration_respects_other_conditions_and_earlier_returns(self):
        definite=row([condition(DEADLINE,thresholds.ABOVE)],'거부',[])
        unknown=row([condition(START,thresholds.ABOVE),condition(thresholds.UNKNOWN,thresholds.BELOW)],'허용',[])
        fn,_=compile_fixture([], [definite,unknown])
        self.assertFalse(fn(2,-1))
        self.assertFalse(fn(2,10801))
        with self.assertRaises(NotImplementedError):
            fn(2,1000)

    def test_writer_schema_as_well_as_messages_contains_only_its_own_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'trial'
            out.mkdir()
            spec,state=workflow.initialize(out,157,None,thresholds=True)
            private=out.with_name(out.name+'-research')
            private.mkdir()
            save(private/'summary.json',{'private':'연구자 전용 37분','score':40})
            for arm,amount in [('self',7),('multi',11)]:
                old=out/'round-001'/arm
                old.mkdir(parents=True)
                save(old/'snapshot.json',dict(plan='초안',code='def allow_cancel(age_seconds, until_start_seconds):\n    return False'))
                state['arms'][arm]['version']=1
                state['answers'].append(dict(arm=arm,batch=1,source='human',text=f'확인 기간은 예약 생성 후 {amount}분입니다.'))
            def capture(path,role,system,packet,instruction,schema,seed,limit,port):
                transcript=json.dumps([packet,schema],ensure_ascii=False)
                self.assertNotIn('연구자 전용',transcript)
                self.assertNotIn('37분',transcript)
                own,other=(7,11) if role.startswith('self') else (11,7)
                self.assertNotIn(f'{other}분',transcript)
                self.assertIn(f'{own}분',transcript)
                if role.endswith('-main'):
                    self.assertIn(f'age_seconds · {own}분',json.dumps(schema,ensure_ascii=False))
                    return dict(plan='미정',questions=[],rows=[],fallback=dict(action='미정',references=[]),complete=False)
                return dict(decisions=dict.fromkeys(guide.PROMPTS,'근거가 이미 있음'),questions=[],needs_code_revision=True,reason='검토')
            with patch.object(workflow,'model_call',side_effect=capture):
                for arm in workflow.ARMS:
                    workflow.version(out,spec,state,arm,0,lambda: None)

    def test_existing_author_form_and_reviewers_use_the_source_bound_code(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            spec,state=workflow.initialize(out,157,None,bind_times=True)
            ordinary=workflow.design(157,'',ordered=True,strict_scope=True)
            self.assertEqual(spec['model_prompt_sha256'],ordinary['model_prompt_sha256'])
            old=out/'round-001'/'multi'
            old.mkdir(parents=True)
            save(old/'snapshot.json',dict(plan='초안',code='def allow_cancel(age_seconds, until_start_seconds):\n    return False'))
            state['arms']['multi']['version']=1
            state['answers'].append(dict(arm='multi',batch=1,source='human',text=LENGTH+' '+END))
            state['answers'].append(dict(arm='self',batch=1,source='human',text='예약 생성 후 9분입니다.'))
            reviews=[]
            def capture(path,role,system,packet,instruction,schema,seed,limit,port):
                self.assertNotIn('9분',json.dumps([packet,schema],ensure_ascii=False))
                if role.endswith('-main'):
                    self.assertEqual((instruction,schema),(guide.TABLE_INSTRUCTION,workflow.TABLE_AUTHOR))
                    checks=[row([dict(input='age_seconds',op='<',seconds=420)],'허용',[1,2]),
                            row([dict(input='age_seconds',op='>',seconds=540)],'거부',[])]
                    return dict(plan='수정안',questions=[],rows=checks,fallback=dict(action='거부',references=[]),complete=False)
                reviews.append(packet['검토할_코드'])
                return dict(decisions=dict.fromkeys(guide.PROMPTS,'근거가 이미 있음'),questions=[],needs_code_revision=True,reason='검토')
            with patch.object(workflow,'model_call',side_effect=capture):
                workflow.version(out,spec,state,'multi',0,lambda: None)
            folder=out/'round-002'/'multi'
            code=json.loads((folder/'snapshot.json').read_text())['code']
            self.assertEqual(reviews,[code]*3)
            self.assertIn('if age_seconds <= 420:',code)
            self.assertIn('raise NotImplementedError',code)
            self.assertNotIn('540',code)
            trace=json.loads((folder/'time-conditions.json').read_text())
            self.assertEqual([t['limit'] for t in trace],[AGE,thresholds.UNKNOWN])
