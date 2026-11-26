import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import human_intervention as common, intervention_operator as operator
from experiments import intervention_research as research, question_guide as guide, scoped_intervention as workflow
from experiments.blind_candidates import digest
from experiments.monitor_cycles import read, save


CODE = 'def allow_cancel(age_seconds, until_start_seconds):\n    return True'
PARTIAL = 'def allow_cancel(age_seconds, until_start_seconds):\n    raise NotImplementedError'


class HumanInterventionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)/'run'
        self.run_dir.mkdir()

    def test_proxy_only_answers_the_distinction_that_was_asked(self):
        for question, fact in operator.FORM_FACTS.items():
            with self.subTest(question=question):
                text, parts, attribution = operator.scoped_response([question])
                self.assertEqual(set(parts), {fact})
                self.assertEqual(attribution, {question:[fact]})
                self.assertEqual(text, parts[fact])
        edge, _, _ = operator.scoped_response([guide.PROMPTS[2]])
        self.assertNotIn('10분',edge)
        ordinary, facts, _ = operator.scoped_response(['이용이 시작되면 일반 취소는 마감되나요?'])
        self.assertEqual(set(facts),{'public_start'})
        self.assertNotIn('정정',ordinary)
        self.assertEqual(operator.scoped_response([]),('',{},{}))
        vague, facts, _ = operator.scoped_response(['추가 정책을 알려주세요.'])
        self.assertFalse(facts)
        self.assertIn('구체적으로',vague)
        for question, fact in [('예약 생성 후 정정할 수 있는 기간은 10분인가요?','correction_period'),
                               ('정정 기간이 끝나는 순간에 정정을 요청하면 허용되나요?','correction_edge')]:
            self.assertEqual(operator.asked_facts(question),{fact})
        range_only='일반 마감이 지난 예약과 막 이용이 시작된 예약에 대해서도 정정 요청을 받습니다. 이는 until_start_seconds의 어떤 범위에 해당하나요?'
        text,parts,_=operator.scoped_response([range_only])
        self.assertEqual(parts,{})
        self.assertNotIn('정정할 수 있습니다',text)
        self.assertEqual(operator.scoped_response(['일반 마감이 지난 예약에 대한 정정 요청을 받는 시간대는 언제인가요?'])[1],{})
        self.assertEqual(set(operator.scoped_response(['정정 시간은 이용 시작 전 몇 초까지 허용되나요?'])[1]),{'correction_reference'})
        echoed='정정 기간 안이면 일반 취소 마감이 지난 예약도 정정할 수 있습니다. 정정 기간은 예약 생성 후 10분입니다.'
        self.assertEqual(operator.scoped_response([echoed])[1],{})
        self.assertEqual(set(operator.scoped_response(['일반 마감 뒤에도 정정 요청이 접수됩니다. 정정 기간은 몇 분인가요?'])[1]),{'correction_period'})

    def test_only_literal_model_selected_questions_reach_the_operator(self):
        spec, state = workflow.initialize(self.run_dir,131,None,True)
        self.assertIn('담당자에게 구체적으로 질문',spec['public_task'])
        initial=spec['public_task']+workflow.WRITE+workflow.CHECK+guide.TABLE_INSTRUCTION+guide.REVIEW_INSTRUCTION+''.join(guide.PROMPTS)
        for private_claim in ('10분','600초','정정 기간이 정확히 끝나는 순간도 포함합니다.'):
            self.assertNotIn(private_claim,initial)
        chosen = guide.PROMPTS[2]
        def answer(path, role, system, packet, instruction, schema, seed, limit, port):
            if role=='shared-main':
                return dict(plan='계획',code=PARTIAL,links=[],questions=[],complete=False)
            self.assertNotIn('직전_자기검토',packet)
            choices=dict.fromkeys(guide.PROMPTS,'이 결정과 무관함')
            if role=='multi-review-2':
                choices[chosen]=guide.ASK
            return dict(decisions=choices,questions=['정정 기간입니다.'],needs_code_revision=False,reason='')
        observed = []
        with patch.object(workflow,'model_call',side_effect=answer):
            workflow.version(self.run_dir,spec,state,'multi',0,lambda: observed.append(not (self.run_dir/'submissions.json').exists()))
        self.assertEqual(observed,[True])
        self.assertEqual(state['arms']['multi']['status'],'awaiting_human')
        pending=workflow.pending(self.run_dir,state,'multi')
        self.assertEqual(pending['groups'],[dict(question=chosen,sources=['multi-review-2'])])
        text, parts, mapping = operator.scoped_response([chosen])
        workflow.reply(self.run_dir,state,'multi',1,text,'delegated_policy_card',parts,mapping)
        before=read(self.run_dir/'state.json')
        workflow.reply(self.run_dir,state,'multi',1,text,'delegated_policy_card',parts,mapping)
        self.assertEqual(read(self.run_dir/'state.json'),before)
        self.assertEqual(workflow.context(spec,state,'multi')['담당자 자연어 답변'],[text])
        self.assertEqual(workflow.context(spec,state,'self')['담당자 자연어 답변'],[])
        with self.assertRaises(ValueError):
            workflow.reply(self.run_dir,state,'multi',1,'바뀐 답','human')
        with self.assertRaises(ValueError):
            workflow.reply(self.run_dir,state,'self',1,'다른 실행','human')
        with self.assertRaises(ValueError):
            workflow.initialize(self.run_dir,157,None,True)

    def test_private_scores_cannot_change_messages_or_stop_a_run(self):
        def replay(folder,private_value):
            spec,state=workflow.initialize(folder,131,None,True)
            private=research.research_directory(folder)
            private.mkdir()
            save(private/'summary.json',dict(score=private_value,expected='PRIVATE_CANARY'))
            # This fixture supplies no decision. The author claims completion despite that.
            logs=[]
            def generate(port,model,messages,seed,limit,thinking,fmt):
                logs.append(messages)
                props=fmt['json_schema']['schema']['properties']
                if 'code' in props:
                    output=dict(plan='계획',questions=[],code=CODE,links=[],complete=True)
                else:
                    output=dict(decisions=dict.fromkeys(guide.PROMPTS,'근거가 이미 있음'),
                                questions=[],needs_code_revision=False,reason='검토')
                return dict(model=model,text=json.dumps(output),usage={'total_tokens':12},elapsed_seconds=0,
                            request=dict(model=model,messages=messages,seed=seed,max_tokens=limit,response_format=fmt))
            with patch('experiments.monitor_cycles.generate',side_effect=generate):
                workflow.version(folder,spec,state,'multi',0,lambda: None)
            for f in folder.glob('round-*/calls/*.json'):
                self.assertNotIn('PRIVATE_CANARY',str(read(f)['request']))
            self.assertNotEqual(state['arms']['multi']['status'],'completed')
            self.assertFalse((folder/'submissions.json').exists())
            return logs,state['arms'],read(folder/'round-001/multi/review.json')
        second=Path(self.tmp.name)/'second'
        second.mkdir()
        self.assertEqual(replay(self.run_dir,0),replay(second,40))

    def test_partial_manual_answer_is_verbatim_and_does_not_close_other_gaps(self):
        spec,state=workflow.initialize(self.run_dir,131,None)
        branch=self.run_dir/'round-001/multi'
        branch.mkdir(parents=True)
        save(branch/'questions.json',dict(issued_at=0,groups=[dict(question=guide.PROMPTS[2])]))
        state['arms']['multi'].update(status='awaiting_human',version=1)
        text='정정 기간의 마지막 순간은 포함합니다. 나머지는 미정입니다.'
        workflow.reply(self.run_dir,state,'multi',1,text,'human')
        self.assertEqual(workflow.context(spec,state,'multi')['담당자 자연어 답변'],[text])
        self.assertEqual(state['answers'][0]['source'],'human')
        self.assertEqual(workflow.stated_facts([text]),{'correction_edge'})
        self.assertFalse(common.finishable(PARTIAL))
        source=Path(self.tmp.name)/'answer.txt'
        for value in ('점수는 24/40점입니다.','{"score": 24}','채점 결과를 확인하세요.'):
            source.write_text(value)
            with self.assertRaises(ValueError):
                common.natural_text(source)
        source.write_text(text)
        self.assertEqual(common.natural_text(source),text)
        private=research.research_directory(self.run_dir)
        private.mkdir()
        (private/'notes.md').write_text(text)
        with self.assertRaises(ValueError):
            common.natural_text(private/'notes.md')

    def test_citations_must_point_to_executable_source(self):
        self.assertEqual(guide.citable_sentences(['기한은 3일입니다. 어떤 경우인지 말씀해 주세요. 나머지는 미정입니다.']),['기한은 3일입니다.'])
        src = ('def allow_cancel(age_seconds, until_start_seconds):\n'
               '    # [3]\n    if age_seconds == 1:  # [1, 2]\n'
               '        return True\n    return False  # [9]')
        self.assertEqual(guide.source_links(src,['a','b','c']),
                         [dict(quote=x,line='if age_seconds == 1:') for x in ('a','b')])
        self.assertFalse(workflow.evidence_ok([dict(quote='a',line='# [3]')],src,['a']))
        self.assertFalse(workflow.evidence_ok([dict(quote='unknown',line='return True')],src,['a']))

    def test_ordered_rules_preserve_authored_order_boundary_units_and_fallback(self):
        a=dict(input='age_seconds',op='<',seconds=37)
        b=dict(input='until_start_seconds',op='>=',seconds=9)
        first=dict(when=[a,b],action='거부',references=[2])
        second=dict(when=[b],action='허용',references=[1])
        plan=dict(rows=[first,second],fallback=dict(action='미정',references=[]))
        src,links=guide.render_table(plan,['first','second'])
        self.assertLess(src.index('if age_seconds < 37 and until_start_seconds >= 9:'),src.index('if until_start_seconds >= 9:'))
        self.assertIn('return False',src)
        self.assertIn('raise NotImplementedError',src)
        self.assertEqual([item['quote'] for item in links],['second','first'])
        self.assertFalse(common.finishable(src))
        plan['rows'].reverse()
        plan['fallback']['action']='거부'
        reversed_src,_=guide.render_table(plan,[])
        self.assertTrue(common.finishable(reversed_src))
        self.assertLess(reversed_src.index('if until_start_seconds'),reversed_src.index('if age_seconds'))

    def test_completed_arm_seals_without_waiting_for_the_other_arm(self):
        spec,state=workflow.initialize(self.run_dir,131,None,ordered=True)
        branch=self.run_dir/'round-001/multi'
        branch.mkdir(parents=True)
        save(branch/'snapshot.json',dict(plan='초안',code=PARTIAL))
        save(branch/'questions.json',dict(issued_at=0,groups=[dict(question=q) for q in guide.PROMPTS]))
        state['arms']['multi'].update(status='awaiting_human',version=1)
        text,parts,attribution=operator.scoped_response(guide.PROMPTS)
        workflow.reply(self.run_dir,state,'multi',1,text,'delegated_policy_card',parts,attribution)
        def model(path,role,system,packet,instruction,schema,seed,limit,port):
            if role=='multi-main':
                self.assertEqual(packet['담당자 자연어 답변'],[text])
                self.assertNotIn('검토',packet)
                def row(field,op,seconds,action,refs):
                    return dict(when=[dict(input=field,op=op,seconds=seconds)],action=action,references=refs)
                return dict(plan='담당자가 설명한 순서',questions=[],complete=True,
                            rows=[row('until_start_seconds','<=',0,'거부',[5,6]),
                                  row('until_start_seconds','>=',86400,'허용',[1]),
                                  row('age_seconds','<=',600,'허용',[2,3,4])],
                            fallback=dict(action='거부',references=[]))
            return dict(decisions=dict.fromkeys(guide.PROMPTS,'근거가 이미 있음'),questions=[],needs_code_revision=False,reason='확인')
        with patch.object(workflow,'model_call',side_effect=model):
            workflow.version(self.run_dir,spec,state,'multi',0,lambda: None)
        self.assertEqual(state['arms']['multi']['status'],'completed')
        final=self.run_dir/'round-002/multi/submission.json'
        self.assertEqual(read(final),read(final.with_name('snapshot.json')))
        self.assertEqual(state['arms']['self']['version'],0)
        self.assertFalse((self.run_dir/'submissions.json').exists())

    def test_malformed_model_output_is_unsubmitted_and_other_arm_continues(self):
        def fail(out,spec,state,arm,port,notify):
            if arm=='multi':
                raise workflow.IncompleteModelOutput('multi-review-2',Path('multi-review-2.json'))
            state['arms'][arm]['status']='incomplete_limit'
            workflow.persist(out,state)
        with patch.object(workflow,'version',side_effect=fail), patch.object(workflow,'local_server'), patch.object(common,'observe_separately'), patch('builtins.print'):
            workflow.run(self.run_dir,0,ordered=True)
        state=read(self.run_dir/'state.json')
        self.assertEqual(state['status'],'incomplete_output')
        self.assertEqual(state['arms']['multi']['failed_role'],'multi-review-2')
        self.assertEqual(state['arms']['self']['status'],'incomplete_limit')
        self.assertFalse((self.run_dir/'submissions.json').exists())

    def test_observer_scores_while_waiting_and_retries_unavailable_grades(self):
        _,state=workflow.initialize(self.run_dir,131,None)
        state['arms']['multi']={'status':'awaiting_human','version':2}
        workflow.persist(self.run_dir,state)
        for num,value in enumerate((PARTIAL,CODE),1):
            branch=common.round_path(self.run_dir,num)/'multi'
            branch.mkdir(parents=True)
            common.freeze(branch/'snapshot.json',dict(version=num,arm='multi',code=value,sha256=digest(value)))
        def grade(passed):
            return dict(total=1,score=int(passed),results=[dict(id='research-only',passed=passed,error=None if passed else 'abstained')])
        with patch.object(research,'grade_isolated',side_effect=[RuntimeError('unavailable'),grade(True)]):
            first=research.observe(self.run_dir)
        self.assertEqual([r['score'] for r in first['versions']],[None,1])
        with patch.object(research,'grade_isolated',return_value=grade(False)) as grading:
            second=research.observe(self.run_dir)
        grading.assert_called_once()
        self.assertEqual(second['versions'][1]['corrected'],1)
        self.assertEqual(second['arm_status']['multi']['status'],'awaiting_human')
        self.assertFalse((self.run_dir/'submissions.json').exists())
        self.assertIn('return True',(research.research_directory(self.run_dir)/'round-002/multi/change.diff').read_text())
        with self.assertRaises(ValueError):
            common.freeze(self.run_dir/'round-001/multi/snapshot.json',{'code':'changed'})
