"""Dispute witnesses using public event types. Expected observations come from the owner's reply."""
import re
from .isolated import run_cases
from .live_schemas import obj


def _reserve(rid, seats, priority=1):
    return dict(op='reserve',reservation_id=rid,user_id='u'+rid,needs={'seats':seats},priority=priority)


def _change(rid, seats, priority=1):
    return dict(op='amend',reservation_id=rid,needs={'seats':seats},priority=priority)


def _capacity(seats):
    return dict(op='set_capacity',resource='seats',capacity=seats)


def panel(task, decision, finding):
    """Select paired alternatives, never labels, for the actual disputed decision."""
    question=decision['question']
    observation=finding.get('reason','')
    legal=re.search(r'(?m)^- code 값:\s*([^\n]+)',task)
    if not legal:
        return []
    codes = re.findall(r'[a-z][a-z_]*',legal[1])
    owner=decision['answer']['text']+' '+decision.get('note','')
    tokens=set(re.findall(r'\b[a-z][a-z_]*\b',owner,re.ASCII))
    outcomes = {name:name for name in codes if name in tokens}
    if not outcomes:
        return []
    cases=[]
    def witness(name, description, seats, events, path, alternatives):
        cases.append(dict(name=name, question=description, options=alternatives,path=path,
                          input=dict(initial_state={'capacities':{'seats':seats,'laptops':0,'projectors':0}},
                                     events=[dict(e,event_id='e'+str(i+1)) for i,e in enumerate(events)])))
    def result(index):
        return ['event_results',index,'code']
    if 'set_capacity' in question and re.search(r'용량|set_capacity|capacity',observation,re.I):
        witness('increase','예약 없이 좌석 총량을 1에서 2로 올릴 때 반환 코드',1,[_capacity(2)],result(0),outcomes)
        witness('same','예약 없이 좌석 총량을 2에서 같은 2로 설정할 때 반환 코드',2,[_capacity(2)],result(0),outcomes)
        used=[_reserve('a',2)]
        witness('at_usage','좌석 2개를 모두 점유 중일 때 총량을 점유량과 같은 2로 설정한 결과 코드',
                3,[*used,_capacity(2)],result(1),outcomes)
        witness('below_usage','좌석 2개를 점유 중일 때 총량을 1로 줄이는 요청의 결과 코드',
                2,[*used,_capacity(1)],result(1),outcomes)
        witness('after_refusal','좌석 2개를 점유 중일 때 총량을 1로 줄이는 요청 후의 실제 총량',
                2,[*used,_capacity(1)],['final_state','capacities','seats'],{'keep_two':2,'set_one':1})
        witness('zero','점유자가 없고 좌석 총량이 0일 때 0으로 설정한 결과 코드',0,[_capacity(0)],result(0),outcomes)
        witness('promotions','총량 1에 좌석 2개를 요청한 a가 대기 중이다. 총량을 2로 올린 사건의 admitted',
                1,[_reserve('a',2),_capacity(2)],['event_results',1,'admitted'],{'admit_a':['a'],'empty':[]})
    elif 'amend' in question and re.search(r'amend|변경|점유|승격',observation,re.I):
        occupied=[_reserve('a',2)]
        witness('replace_occupied','총량 2를 단독 점유한 a가 기존 좌석 2를 다시 2로 변경한다. 변경 결과 코드',
                2,[*occupied,_change('a',2,3)],result(1),outcomes)
        witness('oversize','총량 2를 단독 점유한 a가 좌석을 3으로 변경한다. 변경 결과 코드',
                2,[*occupied,_change('a',3,3)],result(1),outcomes)
        witness('preserve','위와 같은 실패한 변경 요청 이후 a의 기존 좌석 수',
                2,[*occupied,_change('a',3,3)],['final_state','reservations',0,'needs','seats'],{'original_two':2,'new_three':3})
        witness('keep_priority','기존 우선순위 1인 a가 불가능한 변경과 함께 우선순위 3을 요청한다. 실패 후 우선순위',
                2,[*occupied,_change('a',3,3)],['final_state','reservations',0,'priority'],{'original_one':1,'new_three':3})
        release=[*occupied,_reserve('b',1,2),_change('a',1)]
        witness('promote_on_change','총량 2를 a가 전부 점유하고 b는 1석을 기다린다. a가 1석으로 줄인 변경의 admitted',
                2,release,['event_results',2,'admitted'],{'admit_b':['b'],'empty':[]})
        waiting=[_reserve('a',1),_reserve('b',2),_change('b',1,3)]
        witness('keep_order','a가 좌석 한 개를 점유한다. 두 번째로 접수된 대기자 b를 세 번째 사건에서 변경한다. b의 order',
                1,waiting,['final_state','reservations',1,'order'],{'original_two':2,'change_three':3})
        own=[_reserve('b',2),_change('b',1)]
        witness('waiting_change','총량 1에 혼자 2석을 기다리는 b가 1석으로 변경한다. 해당 변경의 반환 코드',
                1,own,result(1),outcomes)
        witness('waiting_admission','총량 1에 혼자 2석을 기다리는 b가 1석으로 변경한다. 해당 변경의 admitted',
                1,own,['event_results',1,'admitted'],{'admit_b':['b'],'empty':[]})
        witness('missing','존재하지 않는 예약을 변경하면 반환할 코드',2,[_change('z',1)],result(0),outcomes)
        closed=[_reserve('a',1),dict(op='cancel',reservation_id='a'),_change('a',1)]
        witness('inactive','취소에 성공한 예약 a를 다시 변경할 때 반환 코드',2,closed,result(2),outcomes)
    return cases


def form(cases):
    properties = {c['name']:{'type':'string','enum':[*c['options'],'unknown']} for c in cases}
    public=[dict(name=c['name'],question=c['question'],choices=c['options']) for c in cases]
    return obj({'covers_dispute':{'type':'boolean'},'predictions':obj(properties)}), public


def confirm(source, cases, predictions):
    """Run bounded owner-derived witnesses privately. The model never receives these results."""
    if not cases or not isinstance(predictions,dict) or set(predictions)!={c['name'] for c in cases}:
        return False
    if any(predictions[c['name']] not in c['options'] for c in cases):
        return False
    rows=run_cases(source,[c['input'] for c in cases],'allocation')
    for case,row in zip(cases,rows):
        if row['error']:
            return False
        actual=row['actual']
        try:
            for key in case['path']:
                actual=actual[key]
        except (KeyError,IndexError,TypeError):
            return False
        expected=case['options'][predictions[case['name']]]
        if type(actual) is not type(expected) or actual!=expected:
            return False
    return len(rows)==len(cases)
