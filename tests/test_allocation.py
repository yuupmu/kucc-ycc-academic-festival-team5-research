import ast
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from backend.engine import Engine, validate_config
from backend.isolated import grade_isolated, check_code
from backend.live_schemas import schemas_for, main_rules, monitor_rules
from resource_allocation_benchmark import score
from resource_allocation_benchmark.evaluator import validate_dataset
from test_backend import ROOT, config, wait_for
from test_openai import FakeProvider

BENCHMARK = ROOT/'resource_allocation_benchmark'
SOURCE = (BENCHMARK/'evaluator/reference.py').read_text()
EMPTY_INPUT = {'initial_state':{'capacities':{'seats':2,'laptops':1,'projectors':0}},'events':[]}
EMPTY_RESULT = {'event_results':[], 'final_state':{'capacities':EMPTY_INPUT['initial_state']['capacities'],
                'available':EMPTY_INPUT['initial_state']['capacities'], 'reservations':[], 'waitlist':[]}, 'notifications':[]}
CHECK = {'input_json':json.dumps(EMPTY_INPUT), 'expected_json':json.dumps(EMPTY_RESULT)}


class AllocationProvider(FakeProvider):
    def invoke(self, envelope, instruction, schema):
        self.envelopes.append(copy.deepcopy(envelope))
        state = envelope['project_state']
        self.assert_contract(envelope, instruction)
        if envelope['role'] == 'monitor':
            needed = not state['decisions']
            result = {'decision':'human' if needed else 'continue', 'reason':'정책 확인',
                      'affected_decision_ids':[], 'checks':[], 'requests':[{'key':'operating_policy','question':'운영 정책은?',
                       'reason':'미확정','affected_tasks':['policy'],'priority':'high'}] if needed else []}
        elif envelope['action'] == 'plan':
            result = {'plan':['상태 전이 구현'], 'assumptions':['운영 정책 미정']}
        elif envelope['action'] == 'inspect_schedule_patch':
            fn = next(n for n in ast.parse(state['code']).body if isinstance(n, ast.FunctionDef) and n.name=='simulate')
            returns = [ast.get_source_segment(state['code'], n) for n in fn.body if isinstance(n,ast.Return)]
            result = {'decisions':[{'request_id':d['request_id'], 'status':'implemented',
                      'code_excerpt':returns[-1], 'reason':'결과에 사건 처리 후의 상태를 포함한다.'}
                      for d in state['scheduling_decisions']]}
        else:
            ready = bool(state['decisions'])
            result = {'code':SOURCE if ready else 'def simulate(initial_state, events):\n    return {}\n',
                      'summary':'구현', 'complete':ready, 'checks':[CHECK] if ready else [],
                      'applied_decision_ids':[d['request_id'] for d in state['decisions']]}
            if state.get('schedule_patch_required'):
                result.pop('code')
                result['edits'] = []
        return result, {'response_id':'test-only','usage':{}}

    def assert_contract(self, envelope, instruction):
        assert 'can_cancel' not in instruction
        assert 'def simulate(' in envelope['project_state']['task']
        assert '출력' in envelope['project_state']['task']


class AllocationTests(unittest.TestCase):
    def test_data_and_reference_in_isolation(self):
        validate_dataset.main()
        report = grade_isolated(SOURCE, BENCHMARK, 'allocation')
        self.assertEqual((report['score'],report['total'],report['errors']),(150,150,0))
        self.assertEqual(len(report['categories']),15)
        self.assertEqual(report['accuracy_percent'],100)

    def test_wrong_state_notification_order_and_type_are_not_accepted(self):
        _, key = score.load_dataset()
        rows = [{'actual':copy.deepcopy(a['expected']),'error':None} for a in key['answers']]
        rows[0]['actual']['final_state']['available']['seats'] += 1
        rows[1]['actual']['notifications'].reverse()
        rows[2]['actual']['event_results'][0]['replayed'] = 0
        report = score.grade_rows(rows)
        self.assertEqual(report['score'],147)
        self.assertEqual(report['errors'],1)
        self.assertEqual(report['components']['final_state']['correct'],148)

    def test_public_checks_use_scenario_objects(self):
        self.assertTrue(check_code(SOURCE,[CHECK],'allocation')['passed'])
        wrong = copy.deepcopy(CHECK)
        expected = copy.deepcopy(EMPTY_RESULT); expected['final_state']['available']['seats']=1
        wrong['expected_json']=json.dumps(expected)
        self.assertFalse(check_code(SOURCE,[wrong],'allocation')['passed'])
        with self.assertRaises(ValueError):
            check_code(SOURCE,[{'input_json':'{}','expected_json':'{}'}],'allocation')

    def test_invalid_review_proposals_do_not_mask_valid_or_failing_checks(self):
        impossible = copy.deepcopy(CHECK)
        wrong = copy.deepcopy(EMPTY_RESULT)
        wrong['final_state']['available']['seats'] = 1
        wrong['final_state']['capacities']['seats'] = 1
        other_input=copy.deepcopy(EMPTY_INPUT)
        other_input['initial_state']['capacities']['seats']=1
        different_capacity=dict(input_json=json.dumps(other_input),expected_json=json.dumps(wrong))
        impossible['expected_json'] = '{}'
        fixed_capacity="def simulate(initial_state, events):\n    return "+repr(EMPTY_RESULT)
        report = check_code(fixed_capacity,[impossible,CHECK,different_capacity],'allocation',proposals=True)
        self.assertFalse(report['passed'])
        self.assertEqual((report['correct'],report['total']), (1,2))
        self.assertEqual(report['rejected_checks'][0]['index'],0)

    def test_proposed_order_is_the_input_event_position(self):
        cap = dict(event_id='e1',op='set_capacity',resource='seats',capacity=2)
        reserve = dict(event_id='e2',op='reserve',reservation_id='a',user_id='u',needs={'seats':1},priority=1)
        inputs = dict(EMPTY_INPUT,events=[cap,reserve])
        expected = copy.deepcopy(EMPTY_RESULT)
        expected['event_results']=[dict(event_id='e1',code='capacity_updated',admitted=[],replayed=False),
                                   dict(event_id='e2',code='confirmed',admitted=['a'],replayed=False)]
        expected['final_state']['reservations']=[dict(reservation_id='a',user_id='u',needs={'seats':1},
                                                       priority=1,status='confirmed',order=1)]
        report=check_code(SOURCE,[dict(input_json=json.dumps(inputs),expected_json=json.dumps(expected))],
                          'allocation',proposals=True)
        self.assertEqual(report['total'],0)
        self.assertIn('order',report['rejected_checks'][0]['reason'])

    def test_task_config_legacy_default_and_validation(self):
        self.assertEqual(validate_config(config())['task_id'],'cancellation')
        cfg=config(); cfg['task_id']='allocation'
        with self.assertRaises(ValueError): validate_config(cfg)
        cfg['mode']='openai'
        self.assertEqual(validate_config(cfg)['task_id'],'allocation')
        cfg['task_id']='../../private'
        with self.assertRaises(ValueError): validate_config(cfg)

    def test_new_workflow_answers_checks_and_manual_150_case_grading(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(ROOT,data_dir=temp)
            try:
                provider=AllocationProvider(); engine.api_client=provider
                cfg=config(); cfg.update(task_id='allocation',mode='openai')
                state=engine.start(cfg)
                state=wait_for(engine,state['id'],lambda s:len(s['requests'])==1)
                for call in state['calls']:
                    text=json.dumps(call['input'],ensure_ascii=False)
                    for secret in ['skip_unfit','higher_first','cancelled_id_reuse','RA-01-01', 'answer_key']:
                        self.assertNotIn(secret,text)
                engine.answer(state['id'],state['requests'][0]['id'],{'text':'모든 사건을 처리한 뒤의 상태를 결과에 포함해 주세요.'})
                state=wait_for(engine,state['id'],lambda s:s['status']=='completed')
                self.assertEqual(state['test']['status'],'not_run')
                self.assertTrue(state['verification']['passed'])
                engine.test(state['id'])
                state=wait_for(engine,state['id'],lambda s:s['test']['status']!='running',timeout=20)
                self.assertEqual(state['test']['status'],'completed',state['test'])
                self.assertEqual(state['test']['report']['score'],150)
                self.assertEqual(state['config']['mainAgent']['prompt'],cfg['mainAgent']['prompt'])
                engine.close()
                engine=Engine(ROOT,data_dir=temp)
                self.assertEqual(engine.get(state['id'])['config']['task_id'],'allocation')
            finally:
                engine.close()

    def test_task_specific_schemas_and_prompts(self):
        self.assertEqual(set(schemas_for('allocation')[0]['properties']['checks']['items']['properties']),{'input_json','expected_json'})
        self.assertIn('simulate(initial_state, events)',main_rules('allocation'))
        self.assertNotIn('expected bool',monitor_rules('allocation'))
        self.assertIn('can_cancel',main_rules('cancellation'))

    def test_second_disputed_answer_cannot_roll_back_a_correct_scoped_edit(self):
        first='접수할 때는 queued를 사용합니다.'
        second='취소할 때는 cancelled를 사용합니다.'
        source=("def status(op):\n    if op == 'reserve':\n        return 'old_a'\n    return 'old_b'\n"
                "def simulate(initial_state, events):\n    return {'codes': [status(e['op']) for e in events]}\n")
        attempts=[]
        class Provider(AllocationProvider):
            def invoke(self, envelope, instruction, schema):
                p=envelope['project_state']
                if envelope['action']=='implement':
                    attempts.append((p['code'],p['editable_decision_ids']))
                    key, old, new = ('a','old_a','queued') if len(attempts)==1 else ('b','old_b','cancelled')
                    return dict(edits=[dict(request_id=key,quote='H1',before=repr(old),after=repr(new))],
                                checks=[],complete=True,summary='',applied_decision_ids=list(p['editable_decision_ids']),
                                context_decision_ids=[]),{}
                d=p['scheduling_decisions'][0]
                key=d['request_id']
                ok=repr('queued' if key=='a' else 'cancelled') in p['code']
                return {'decisions':[dict(request_id=key,status='implemented' if ok else 'mismatch',
                                          code_excerpt='L3' if key=='a' else 'L4',reason='담당자 답변과 반환값 대조')]},{}
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(ROOT,data_dir=temp)
            try:
                engine.api_client=Provider()
                cfg=config();cfg.update(task_id='allocation',mode='openai')
                with patch.object(engine,'_spawn'):
                    saved=engine.start(cfg)
                s=engine._state(saved['id'])
                s.update(artifact=dict(code=source),code_version=1)
                for key,answer in [('a',first),('b',second)]:
                    s['requests'].append(dict(id=key,key=key,question='처리 결과는?',status='waiting',sources=[1]))
                    engine.answer(s['id'],key,{'text':answer})
                result,_=engine._live_implement(s['id'],'allocation',0)
                self.assertEqual(attempts,[(source,['a','b']), (source.replace('old_a','queued'),['b'])])
                self.assertEqual(result['code'],source.replace('old_a','queued').replace('old_b','cancelled'))
                self.assertEqual(s['artifact']['code'],source)
            finally:
                engine.close()

    def test_explicit_monitor_verification_executes_its_checks_without_exposing_other_results(self):
        actions=[]
        class Observer(AllocationProvider):
            def invoke(self,envelope,instruction,schema):
                actions.append(envelope['action'])
                if envelope['action']=='observe':
                    self_limit=schema['properties']['checks']['maxItems']
                    assert self_limit==0
                    return dict(decision='verify',reason='빈 사건의 반환 구조',requests=[],checks=[],
                                affected_decision_ids=[]),{}
                assert 'code' not in envelope['project_state'] and 'verification' not in envelope['project_state']
                return dict(checks=[CHECK]),{}
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(ROOT,data_dir=temp)
            try:
                provider=Observer()
                engine.api_client=provider
                cfg=config();cfg.update(task_id='allocation',mode='openai')
                with patch.object(engine,'_spawn'):
                    saved=engine.start(cfg)
                s=engine._state(saved['id'])
                s.update(artifact=dict(code=SOURCE),code_version=1)
                env=dict(role='monitor',action='observe',project_state=engine._live_context(s))
                call=dict(id='m1',input=env,agent='monitor-1',status='running',execution_epoch=0)
                s['calls'].append(call)
                engine._live_monitor(s['id'],1,env,call,provider,0)
                self.assertEqual(actions,['observe','specify_schedule_checks'])
                self.assertEqual(s['monitors'][0]['verification']['correct'],1)
                self.assertEqual(s['review_log'][0]['checks'],[CHECK])
                engine._restore_review_log(s)
                self.assertEqual(len(s['review_log']),1)
            finally:
                engine.close()

    def test_closed_pending_branch_needs_current_confirmations_and_no_actionable_review(self):
        state=dict(code_version=7, artifact={'code':"def simulate(initial_state, events):\n    return {}",'sha256':'code7'},
                   decisions=[{'request_id':'q'}], requests=[{'status':'applied'}],
                   monitors=[dict(status='observed',version=7,decision='continue') for _ in range(3)],
                   review_log=[dict(decision='continue',requests=[],affected_decision_ids=[])],
                   scheduling_confirmations={'q':{'code_sha256':'code7'}})
        env=dict(project_state={'schedule_patch_required':True,'pending_code_sites':{'@pending:2:4':'pass'}})
        result=dict(complete=False,edits=[{'request_id':'q'}])
        self.assertTrue(Engine._reviewed_schedule_repair(state,env,result))
        state['review_log'][0]['affected_decision_ids']=['q']
        self.assertFalse(Engine._reviewed_schedule_repair(state,env,result))
        state['review_log']=[]
        state['scheduling_confirmations']['q']['code_sha256']='older'
        self.assertFalse(Engine._reviewed_schedule_repair(state,env,result))
