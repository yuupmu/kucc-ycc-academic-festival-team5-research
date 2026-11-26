import unittest

from backend import allocation_repair as repair
from backend.allocation_dispatch import capacity_options


SOURCE = '''def schedule(events):
    recorded = []
    for event in events:
        if event == "hold":
            raise NotImplementedError("담당자 답변 대기")
        recorded.append(("other", event))
    return recorded
'''
DECISION = {'request_id':'one', 'answer':{'text':'보류 요청은 한 번만 기록하고 다음 사건으로 넘어갑니다.'}, 'note':''}


class SchedulingRepairTests(unittest.TestCase):
    def test_approved_pending_branch_fills_all_effects_preserving_every_other_byte(self):
        site, = repair.pending_sites(SOURCE)
        edit = dict(request_id='one', quote='H1', before=site, after='recorded.append(("hold", event))\ncontinue')
        code = repair.apply_edits(SOURCE,[edit],[DECISION],{'one'})
        self.assertEqual(code, SOURCE.replace('raise NotImplementedError("담당자 답변 대기")',
                                              'recorded.append(("hold", event))\n            continue'))
        self.assertFalse(repair.pending_sites(code))
        namespace = {}
        exec(code, namespace)
        self.assertEqual(namespace['schedule'](['left','hold','right']),
                         [('other','left'),('hold','hold'),('other','right')])

    def test_active_scope_and_owner_quote_are_required_for_a_pending_site(self):
        site, = repair.pending_sites(SOURCE)
        good = dict(request_id='one',quote='H1',before=site,after='continue')
        for changes, active in [({}, set()), ({'quote':'질문의 제안일 뿐입니다.'},{'one'}),
                                ({'request_id':'two'}, {'one','two'}), ({'after':'    continue\nreturn []'}, {'one'})]:
            candidate = dict(good, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                repair.apply_edits(SOURCE,[candidate],[DECISION],active)

    def test_empty_or_still_deferred_implementation_does_not_count(self):
        site, = repair.pending_sites(SOURCE)
        for replacement in ['# later', 'pass', 'raise NotImplementedError()', 'def replace_other():\n    pass']:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                repair.apply_edits(SOURCE,[dict(request_id='one',quote='H1',before=site,after=replacement)],
                                   [DECISION],{'one'})

    def test_a_prior_approval_is_preserved_until_the_owner_or_watcher_reopens_it(self):
        requests = [dict(id='one', status='applied', applied_version=1),
                    dict(id='two', status='acknowledged', acknowledged_version=1),
                    dict(id='three', status='answered'), dict(id='four',status='applied')]
        self.assertEqual(repair.carried_decisions({'requests':requests,'editable_decision_ids':['one']}),
                         {'two':'acknowledged'})

    def test_model_receives_owner_text_for_the_point_under_review_without_scores(self):
        other = dict(request_id='two', key='old', question='이전 질문', answer={'text':'이전 답'}, note='')
        current = dict(DECISION,key='hold',question='보류 처리 기준은?')
        context = dict(code=SOURCE,schedule_patch_required=True,editable_decision_ids=['one'],
                       required_decision_ids=['one','two'],scheduling_decisions=[other,current],
                       decisions=[other,current],requests=[dict(id='one',status='answered',answer=current['answer']),
                                                           dict(id='two',status='applied',applied_version=1)])
        wire = repair.model_view(dict(action='implement',project_state=context))['project_state']
        self.assertEqual(wire['required_decision_ids'],['one'])
        self.assertEqual(wire['owner_passages']['one']['H1'],DECISION['answer']['text'])
        self.assertEqual(wire['preserved_decisions'],[dict(request_id='two',key='old')])
        self.assertEqual(context['scheduling_decisions'], [other,current])
        self.assertFalse(repair.has_code_evidence(SOURCE,'L1'))
        self.assertTrue(repair.has_code_evidence(SOURCE,'L6'))

    def test_capacity_completion_uses_this_programs_names_owner_code_and_event_tail(self):
        src = """def settle(pool):
    return pool['seats']

def simulate(initial_state, events):
    pool = dict(initial_state['capacities'])
    log = []
    for item in events:
        verdict = None
        admitted = -1
        if verdict is None:
            action = item['op']
            if action == 'set_capacity':
                raise NotImplementedError()
            verdict = item['reservation_id']
            admitted = settle(pool)
        log.append((verdict, admitted))
    return log
"""
        answer = dict(request_id='x',question='set_capacity 결과는?',answer={'text':'변경을 수용하면 refreshed를 반환하고 배정을 실행합니다.'})
        context = dict(code=src, task='- code 값: refreshed, denied.', pending_code_sites=repair.pending_sites(src),
                       editable_decision_ids=['x'],scheduling_decisions=[answer])
        choices = capacity_options(context)
        self.assertEqual(len(choices),2)
        entry, = [o for o in choices.values() if '기존 배정 함수' in o['description']]
        self.assertTrue(all('refreshed' in name for name in choices))
        code = repair.apply_edits(src,[dict(request_id='x',quote='H1',before=entry['before'],after=entry['after'])],
                                  [answer],{'x'})
        ns = {}
        exec(code,ns)
        self.assertEqual(ns['simulate']({'capacities':{'seats':2}},[
            dict(op='reserve',reservation_id='old'),dict(op='set_capacity',resource='seats',capacity=0),
            dict(op='reserve',reservation_id='next')]), [('old',2),('refreshed',0),('next',0)])
        self.assertEqual(capacity_options(dict(context,editable_decision_ids=[])),{})
        answer['answer']['text']='아직 정하지 않았습니다.'
        self.assertEqual(capacity_options(context),{})
